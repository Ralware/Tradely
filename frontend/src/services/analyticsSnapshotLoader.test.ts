import { describe, expect, it, vi } from 'vitest';
import { loadAnalyticsSnapshot, type SnapshotLoadDependencies } from './analyticsSnapshotLoader';
import type { PreparedSnapshot } from './snapshotStore';

const identity = 'global:NASDAQ:MSFT';
function snapshot(overrides: Record<string, unknown> = {}): PreparedSnapshot {
  const fp = 'fingerprint-1';
  return {
    schema_version: 1,
    interval: '1d',
    fingerprint: fp,
    generated_at: '2026-11-22T10:00:00Z',
    analysis: { fingerprint: fp, is_stale: false, candles: [{ close: 12 }] },
    indicator_series: { series: [{ close: 12 }] },
    technical_ratings: { fingerprint: fp, summary: { overall: { available: 1 } } },
    strategy_variants: Object.fromEntries([
      'long_only:NONE', 'long_only:LONG', 'long_only:SHORT',
      'short_only:NONE', 'short_only:LONG', 'short_only:SHORT',
      'long_short:NONE', 'long_short:LONG', 'long_short:SHORT',
    ].map((key) => [key, { state: 'READY' }])),
    provenance: { instrument_id: identity, data_freshness: 'fresh' },
    ...overrides,
  } as PreparedSnapshot;
}
function dependencies(overrides: Partial<SnapshotLoadDependencies> = {}): SnapshotLoadDependencies {
  return {
    readLocal: vi.fn(async () => undefined),
    writeLocal: vi.fn(async () => undefined),
    request: vi.fn(async () => snapshot()),
    ...overrides,
  };
}

describe('loadAnalyticsSnapshot', () => {
  it('reuses a complete fresh local snapshot without a market request', async () => {
    const local = snapshot();
    const io = dependencies({ readLocal: vi.fn(async () => local) });
    const onCached = vi.fn();

    const loaded = await loadAnalyticsSnapshot(identity, '1d', { dependencies: io, onCached });

    expect(loaded).toBe(local);
    expect(onCached).toHaveBeenCalledWith(local);
    expect(io.request).not.toHaveBeenCalled();
    expect(io.writeLocal).not.toHaveBeenCalled();
  });

  it('fetches, validates, and persists one timeframe on a cache miss', async () => {
    const live = snapshot();
    const io = dependencies({ request: vi.fn(async () => live) });

    const loaded = await loadAnalyticsSnapshot(identity, '1d', { dependencies: io });

    expect(loaded).toBe(live);
    expect(io.request).toHaveBeenCalledWith(identity, '1d', undefined);
    expect(io.writeLocal).toHaveBeenCalledWith(identity, '1d', live);
  });

  it('does not trust an incomplete local record and repairs it via the live path', async () => {
    const incomplete = snapshot({ strategy_variants: { 'long_only:NONE': {} } });
    const live = snapshot({ fingerprint: 'repaired' });
    live.analysis.fingerprint = 'repaired';
    live.technical_ratings.fingerprint = 'repaired';
    const io = dependencies({
      readLocal: vi.fn(async () => incomplete),
      request: vi.fn(async () => live),
    });

    await expect(loadAnalyticsSnapshot(identity, '1d', { dependencies: io })).resolves.toBe(live);
    expect(io.request).toHaveBeenCalledTimes(1);
    expect(io.writeLocal).toHaveBeenCalledTimes(1);
  });

  it('keeps the cached last-known-good value visible when a stale-data refresh fails', async () => {
    const stale = snapshot({ provenance: { instrument_id: identity, data_freshness: 'stale' } });
    const io = dependencies({
      readLocal: vi.fn(async () => stale),
      request: vi.fn(async () => { throw new Error('provider unavailable'); }),
    });
    const onCached = vi.fn();

    await expect(loadAnalyticsSnapshot(identity, '1d', { dependencies: io, onCached }))
      .rejects.toThrow('provider unavailable');
    expect(onCached).toHaveBeenCalledWith(stale);
    expect(io.writeLocal).not.toHaveBeenCalled();
  });

  it('does not start a live request after the selected instrument request is cancelled', async () => {
    let releaseRead!: (value: PreparedSnapshot | undefined) => void;
    const io = dependencies({
      readLocal: vi.fn((): Promise<PreparedSnapshot | undefined> =>
        new Promise((resolve) => { releaseRead = resolve; })),
    });
    const controller = new AbortController();
    const pending = loadAnalyticsSnapshot(identity, '1d', { dependencies: io, signal: controller.signal });
    controller.abort();
    releaseRead(undefined);

    await expect(pending).rejects.toMatchObject({ name: 'AbortError' });
    expect(io.request).not.toHaveBeenCalled();
    expect(io.writeLocal).not.toHaveBeenCalled();
  });

  it('continues with durable server data when browser storage is unavailable', async () => {
    const live = snapshot();
    const io = dependencies({
      readLocal: vi.fn(async () => { throw new Error('IndexedDB unavailable'); }),
      request: vi.fn(async () => live),
      writeLocal: vi.fn(async () => { throw new Error('browser quota exceeded'); }),
    });
    const warning = vi.spyOn(console, 'warn').mockImplementation(() => undefined);

    await expect(loadAnalyticsSnapshot(identity, '1d', { dependencies: io })).resolves.toBe(live);
    expect(io.request).toHaveBeenCalledTimes(1);
    expect(io.writeLocal).toHaveBeenCalledTimes(1);
    expect(warning).toHaveBeenCalledTimes(2);
    warning.mockRestore();
  });
});
