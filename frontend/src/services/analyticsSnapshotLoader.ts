import { apiRequest } from './api';
import { snapshotDatabase } from './snapshotDatabase';
import { snapshotStore } from './snapshotStore';
import type { PreparedSnapshot } from './snapshotStore';

export function isCompleteSnapshot(value: PreparedSnapshot | undefined): value is PreparedSnapshot {
  if (!value || value.schema_version !== 1 || !value.fingerprint) return false;
  const candles = value.analysis?.candles;
  const series = value.indicator_series?.series;
  const variants = value.strategy_variants;
  const expectedVariants = [
    'long_only:NONE', 'long_only:LONG', 'long_only:SHORT',
    'short_only:NONE', 'short_only:LONG', 'short_only:SHORT',
    'long_short:NONE', 'long_short:LONG', 'long_short:SHORT',
  ];
  if (!variants || expectedVariants.some((key) => !variants[key] || typeof variants[key] !== 'object')) return false;
  return Array.isArray(candles) && candles.length > 0
    && Array.isArray(series) && series.length === candles.length
    && Boolean(value.technical_ratings?.summary)
    && value.analysis?.fingerprint === value.fingerprint
    && value.technical_ratings?.fingerprint === value.fingerprint;
}

export interface SnapshotLoadDependencies {
  readLocal: (instrumentId: string, interval: string) => Promise<PreparedSnapshot | undefined>;
  writeLocal: (instrumentId: string, interval: string, snapshot: PreparedSnapshot) => Promise<void>;
  request: (instrumentId: string, interval: string, signal?: AbortSignal) => Promise<PreparedSnapshot>;
}

const defaultDependencies: SnapshotLoadDependencies = {
  async readLocal(instrumentId, interval) {
    const memory = snapshotStore.getSnapshot(instrumentId, interval);
    if (isCompleteSnapshot(memory)) return memory;
    return (await snapshotDatabase.get(instrumentId, interval))?.payload;
  },
  async writeLocal(instrumentId, interval, payload) {
    await snapshotDatabase.put({
      instrumentId,
      interval,
      fingerprint: payload.fingerprint,
      schemaVersion: Number(payload.schema_version),
      syncedAt: new Date().toISOString(),
      payload,
    });
  },
  request(instrumentId, interval, signal) {
    return apiRequest<PreparedSnapshot>(
      `/api/analytics/on-demand/${encodeURIComponent(instrumentId)}/${encodeURIComponent(interval)}`,
      { signal, timeoutMs: 120_000 },
    );
  },
};

function isFresh(snapshot: PreparedSnapshot): boolean {
  return snapshot.analysis?.is_stale !== true && snapshot.provenance?.data_freshness !== 'stale';
}

export async function loadAnalyticsSnapshot(
  instrumentId: string,
  interval: string,
  options: {
    signal?: AbortSignal;
    onCached?: (snapshot: PreparedSnapshot) => void;
    dependencies?: SnapshotLoadDependencies;
  } = {},
): Promise<PreparedSnapshot> {
  const dependencies = options.dependencies ?? defaultDependencies;
  let local: PreparedSnapshot | undefined;
  try {
    local = await dependencies.readLocal(instrumentId, interval);
  } catch (error) {
    // Browser storage is an optimization; the backend SQLite cache remains authoritative.
    console.warn('[CACHE] browser snapshot read failed; continuing to backend', error);
  }
  if (isCompleteSnapshot(local)) {
    options.onCached?.(local);
    if (isFresh(local)) return local;
  }
  if (options.signal?.aborted) throw new DOMException('The operation was aborted.', 'AbortError');

  const remote = await dependencies.request(instrumentId, interval, options.signal);
  if (!isCompleteSnapshot(remote) || remote.interval !== interval
    || remote.provenance?.instrument_id !== instrumentId) {
    throw new Error('The server returned an incomplete or mismatched analytics snapshot.');
  }
  if (options.signal?.aborted) throw new DOMException('The operation was aborted.', 'AbortError');
  try {
    await dependencies.writeLocal(instrumentId, interval, remote);
  } catch (error) {
    // The on-demand API has already published the validated bundle to local SQLite.
    console.warn('[CACHE] browser snapshot write failed; keeping validated backend result', error);
  }
  return remote;
}
