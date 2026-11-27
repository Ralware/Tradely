import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { PreparedSnapshot } from './snapshotStore';
import { snapshotStore } from './snapshotStore';

const mocks = vi.hoisted(() => ({
  apiRequest: vi.fn(),
  getWatchlist: vi.fn(),
  getMany: vi.fn(),
  put: vi.fn(),
}));

vi.mock('./api', () => ({ apiRequest: mocks.apiRequest }));
vi.mock('./portfolioService', () => ({
  portfolioService: { getWatchlist: mocks.getWatchlist },
}));
vi.mock('./snapshotDatabase', () => ({
  snapshotDatabase: {
    getMany: mocks.getMany,
    put: mocks.put,
    get: vi.fn(),
  },
}));

import { snapshotHydrator } from './snapshotHydrator';

const identity = 'global:NASDAQ:MSFT';
const fingerprint = 'fp-1';

function snapshot(): PreparedSnapshot {
  return {
    schema_version: 3,
    interval: '1d',
    fingerprint,
    generated_at: '2026-11-24T10:00:00Z',
    analysis: {
      fingerprint,
      is_stale: false,
      candles: [{ close: 12 }],
      as_of: '2026-11-24T10:00:00Z',
    },
    indicator_series: { series: [{ close: 12 }] },
    technical_ratings: { fingerprint, summary: { overall: { available: 1 } } },
    strategy_variants: Object.fromEntries(
      [
        'long_only:NONE', 'long_only:LONG', 'long_only:SHORT',
        'short_only:NONE', 'short_only:LONG', 'short_only:SHORT',
        'long_short:NONE', 'long_short:LONG', 'long_short:SHORT',
      ].map((key) => [key, { state: 'READY' }]),
    ),
    provenance: {
      instrument_id: identity,
      latest_candle_timestamp: '2026-11-24T10:00:00Z',
    },
  } as PreparedSnapshot;
}

const manifestItem = {
  instrument_id: identity,
  interval: '1d',
  status: 'READY',
  snapshot_id: 'snap-1',
  fingerprint,
  latest_candle_at: '2026-11-24T10:00:00Z',
  candle_count: 1,
  generated_at: '2026-11-24T10:00:00Z',
};

function manifestCalls(): number {
  return mocks.apiRequest.mock.calls.filter(
    ([path]) => String(path).endsWith('/index'),
  ).length;
}
function snapshotCalls(): number {
  return mocks.apiRequest.mock.calls.filter(
    ([path]) => String(path).includes('/analytics/precomputed/') && !String(path).endsWith('/index'),
  ).length;
}

beforeEach(() => {
  snapshotHydrator.stop();
  snapshotStore.clear();
  vi.clearAllMocks();
  mocks.getWatchlist.mockResolvedValue({ items: [{ instrument_id: identity }] });
  mocks.getMany.mockResolvedValue([undefined]);
  mocks.put.mockResolvedValue(undefined);
  mocks.apiRequest.mockImplementation((path: string) => {
    if (path.endsWith('/index')) {
      return Promise.resolve({ items: [manifestItem] });
    }
    return Promise.resolve(snapshot());
  });
});

describe('snapshotHydrator', () => {
  it('downloads a ready snapshot once and persists it', async () => {
    await snapshotHydrator.start();

    expect(manifestCalls()).toBe(1);
    expect(snapshotCalls()).toBe(1);
    expect(mocks.getMany).toHaveBeenCalledTimes(1);
    expect(mocks.put).toHaveBeenCalledTimes(1);
    expect(snapshotStore.getSnapshot(identity, '1d')?.fingerprint).toBe(fingerprint);
    expect(snapshotHydrator.getProgress().phase).toBe('ready');
  });

  it('skips unchanged manifest entries without reading IndexedDB again', async () => {
    await snapshotHydrator.start();
    expect(snapshotCalls()).toBe(1);

    await snapshotHydrator.refresh(false);

    expect(manifestCalls()).toBe(2);
    expect(snapshotCalls()).toBe(1);
    expect(mocks.getMany).toHaveBeenCalledTimes(1);
    expect(mocks.put).toHaveBeenCalledTimes(1);
  });

  it('reuses a matching local bundle without a snapshot download', async () => {
    mocks.getMany.mockResolvedValue([{
      instrumentId: identity,
      interval: '1d',
      fingerprint,
      schemaVersion: 3,
      syncedAt: '2026-11-24T10:00:00Z',
      payload: snapshot(),
    }]);

    await snapshotHydrator.start();

    expect(mocks.getMany).toHaveBeenCalledTimes(1);
    expect(snapshotCalls()).toBe(0);
    expect(mocks.put).not.toHaveBeenCalled();
    expect(snapshotStore.getSnapshot(identity, '1d')?.fingerprint).toBe(fingerprint);
  });

  it('deduplicates concurrent synchronizations into one manifest and one download', async () => {
    await Promise.all([
      snapshotHydrator.refresh(false),
      snapshotHydrator.refresh(false),
    ]);

    expect(manifestCalls()).toBe(1);
    expect(snapshotCalls()).toBe(1);
    expect(mocks.getMany).toHaveBeenCalledTimes(1);
  });

  it('keeps progress and reports per-entry errors', async () => {
    mocks.apiRequest.mockImplementation((path: string) => {
      if (path.endsWith('/index')) {
        return Promise.resolve({ items: [manifestItem] });
      }
      return Promise.reject(new Error('snapshot unavailable'));
    });

    await snapshotHydrator.start();

    const progress = snapshotHydrator.getProgress();
    expect(progress.phase).toBe('error');
    expect(progress.total).toBe(1);
    expect(progress.completed).toBe(1);
    expect(progress.errors[0]).toContain('snapshot unavailable');
  });
});
