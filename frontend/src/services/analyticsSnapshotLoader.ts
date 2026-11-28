import { apiRequest } from './api';
import { cacheEvent } from './cacheDiagnostics';
import { snapshotDatabase } from './snapshotDatabase';
import { snapshotStore } from './snapshotStore';
import type { PreparedSnapshot } from './snapshotStore';
import { isTimestampFresh } from '../utils/freshness';

export const ANALYTICS_SCHEMA_VERSION = 3;

export function isCompleteSnapshot(value: PreparedSnapshot | undefined): value is PreparedSnapshot {
  if (!value || value.schema_version !== ANALYTICS_SCHEMA_VERSION || !value.fingerprint) return false;
  const candles = value.analysis?.candles;
  const series = value.indicator_series?.series;
  return Array.isArray(candles) && candles.length > 0
    && Array.isArray(series) && series.length === candles.length
    && Boolean(value.technical_ratings?.summary)
    && value.indicator_series?.fingerprint === value.fingerprint
    && value.provenance?.ohlcv_fingerprint === value.fingerprint
    && value.analysis?.fingerprint === value.fingerprint
    && value.technical_ratings?.fingerprint === value.fingerprint;
}

export interface SnapshotLoadDependencies {
  readLocal: (instrumentId: string, interval: string) => Promise<PreparedSnapshot | undefined>;
  writeLocal: (instrumentId: string, interval: string, snapshot: PreparedSnapshot) => Promise<void>;
  request: (instrumentId: string, interval: string, signal?: AbortSignal, refreshLatest?: boolean) => Promise<PreparedSnapshot>;
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
  request(instrumentId, interval, signal, refreshLatest) {
    return apiRequest<PreparedSnapshot>(
      `/api/analytics/on-demand/${encodeURIComponent(instrumentId)}/${encodeURIComponent(interval)}`,
      { query: refreshLatest ? { refresh_latest: true } : undefined, signal, timeoutMs: 120_000 },
    );
  },
};

export function isSnapshotFresh(
  snapshot: PreparedSnapshot,
  now: Date = new Date(),
): boolean {
  if (!snapshot || snapshot.analysis?.is_stale === true || snapshot.technical_ratings?.is_stale === true) return false;
  if (snapshot.provenance?.data_freshness === 'stale') return false;
  const interval = String(snapshot.interval ?? snapshot.analysis?.interval ?? '1d');
  const market = String(snapshot.analysis?.market ?? snapshot.market ?? '');
  // The candle timestamp is authoritative; a snapshot generated hours ago for
  // an intraday timeframe must not be reused just because its flags said fresh.
  const latest =
    snapshot.provenance?.latest_candle_timestamp
    ?? snapshot.analysis?.as_of
    ?? snapshot.generated_at;
  return isTimestampFresh(latest, market, interval, now);
}

/**
 * How long a successful validation is trusted for navigation purposes. If the
 * user leaves Analytics and returns inside this window, the complete local
 * snapshot is served without another on-demand calculation. The window is
 * deliberately short for intraday data and longer for daily/weekly bars.
 */
function revalidateAfterMs(interval: string): number {
  switch (interval) {
    case '1m': return 15_000;
    case '3m': return 20_000;
    case '5m': return 30_000;
    case '15m':
    case '30m':
    case '45m': return 60_000;
    case '1h':
    case '2h':
    case '4h':
    case '6h':
    case '8h':
    case '12h': return 5 * 60_000;
    case '1d':
    case '3d': return 15 * 60_000;
    case '1wk':
    case '1w': return 60 * 60_000;
    case '1mo':
    case '1M': return 6 * 60 * 60_000;
    default: return 5 * 60_000;
  }
}

function snapshotKey(instrumentId: string, interval: string): string {
  return `${instrumentId}\u0000${interval}`;
}

const lastValidated = new Map<string, number>();
const inFlight = new Map<string, Promise<PreparedSnapshot>>();

export interface LoadAnalyticsSnapshotOptions {
  signal?: AbortSignal;
  onCached?: (snapshot: PreparedSnapshot) => void;
  dependencies?: SnapshotLoadDependencies;
  /** Bypass the local snapshot and the navigation validation window. */
  forceRefresh?: boolean;
  /** Keep the local snapshot visible, then ask the backend to refresh the latest candle tail. */
  refreshLatest?: boolean;
  /**
   * Serve a complete local snapshot without revalidating when it was already
   * validated recently. The Analytics workspace enables this; loader tests and
   * callers that need strict freshness leave it off.
   */
  reuseRecentlyValidated?: boolean;
}

export async function loadAnalyticsSnapshot(
  instrumentId: string,
  interval: string,
  options: LoadAnalyticsSnapshotOptions = {},
): Promise<PreparedSnapshot> {
  const dependencies = options.dependencies ?? defaultDependencies;
  const key = snapshotKey(instrumentId, interval);

  let local: PreparedSnapshot | undefined;
  try {
    local = await dependencies.readLocal(instrumentId, interval);
  } catch (error) {
    // Browser storage is an optimization; the backend SQLite cache remains authoritative.
    console.warn('[CACHE] browser snapshot read failed; continuing to backend', error);
  }

  if (
    isCompleteSnapshot(local)
    && local.interval === interval
    && local.provenance?.instrument_id === instrumentId
  ) {
    options.onCached?.(local);
    if (!options.forceRefresh) {
      if (isSnapshotFresh(local) && !options.refreshLatest) {
        lastValidated.set(key, Date.now());
        cacheEvent('hit', { kind: 'snapshot', key, fresh: true });
        return local;
      }
      const validatedAt = lastValidated.get(key) ?? 0;
      if (
        !options.refreshLatest
        && options.reuseRecentlyValidated
        && Date.now() - validatedAt < revalidateAfterMs(interval)
      ) {
        cacheEvent('hit', { kind: 'snapshot', key, fresh: false, recentlyValidated: true });
        return local;
      }
    }
  }

  if (options.signal?.aborted) {
    const pending = inFlight.get(`${key}${options.forceRefresh ? '\u0000force' : ''}`);
    if (!pending) {
      cacheEvent('cancel', { kind: 'snapshot', key });
      throw new DOMException('The operation was aborted.', 'AbortError');
    }
  }

  const requestKey = `${key}${options.forceRefresh ? '\u0000force' : ''}`;
  let pending = inFlight.get(requestKey);
  if (pending) {
    cacheEvent('dedupe', { kind: 'snapshot', key });
  } else {
    cacheEvent('request', { kind: 'snapshot', key, force: Boolean(options.forceRefresh) });
    // The network request deliberately does not receive the caller's abort
    // signal: a component unmount must not discard a response that other
    // consumers (or the next navigation) can reuse from the shared cache.
    let request: Promise<PreparedSnapshot>;
    request = (options.refreshLatest
      ? dependencies.request(instrumentId, interval, undefined, true)
      : dependencies.request(instrumentId, interval, undefined))
      .then(async (remote) => {
        if (!isCompleteSnapshot(remote) || remote.interval !== interval
          || remote.provenance?.instrument_id !== instrumentId) {
          throw new Error('The server returned an incomplete or mismatched analytics snapshot.');
        }
        try {
          await dependencies.writeLocal(instrumentId, interval, remote);
        } catch (error) {
          // The on-demand API has already published the validated bundle to local SQLite.
          console.warn('[CACHE] browser snapshot write failed; keeping validated backend result', error);
        }
        lastValidated.set(key, Date.now());
        cacheEvent('store', { kind: 'snapshot', key });
        return remote;
      })
      .finally(() => {
        if (inFlight.get(requestKey) === request) inFlight.delete(requestKey);
      });
    inFlight.set(requestKey, request);
    pending = request;
  }

  return pending;
}

export function invalidateSnapshotValidation(instrumentId: string, interval: string): void {
  lastValidated.delete(snapshotKey(instrumentId, interval));
  cacheEvent('invalidate', { kind: 'snapshot', key: snapshotKey(instrumentId, interval) });
}
