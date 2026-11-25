import { apiRequest } from './api';
import { cacheEvent } from './cacheDiagnostics';
import type {
  AnalysisResponse,
  AnalyticsSnapshotResponse,
  DirectionMode,
  IndicatorSeriesResponse,
  Market,
  TechnicalSummaryResponse,
} from '../types/api';
import { defaultDaysFor } from '../utils/timeframes';

/**
 * A market-data request is identified by one canonical instrument id. Legacy
 * symbol/market/exchange fields remain for previously recorded identifiers.
 */
export interface AnalysisQuery {
  instrumentId?: string | null;
  symbol?: string;
  market?: Market;
  exchange?: string | null;
  interval?: string;
  days?: number;
  provider?: string;
  directionMode?: DirectionMode;
}

export interface PrefetchFailure {
  interval: string;
  error: string;
}

export interface PrefetchResult {
  total: number;
  completed: number;
  failures: PrefetchFailure[];
}

export type PrefetchProgress = (result: PrefetchResult) => void;

const LONG_TIMEOUT = 120_000;
const MAX_CACHED_RESPONSES = 60;
const MAX_MARKET_CACHE_BYTES = 96 * 1024 * 1024;
const TIMEFRAME_PREFETCH_CONCURRENCY = 2;

interface CacheEntry {
  baseKey: string;
  instrumentId: string;
  data: MarketDataResponse;
  /** Entries are served without a network request until this timestamp. */
  expiresAt: number;
  /** Entries are served while a background refresh runs until this timestamp. */
  staleUntil: number;
  sizeBytes: number;
}

const marketDataCache = new Map<string, CacheEntry>();
const inFlightResponses = new Map<string, Promise<MarketDataResponse>>();
const cacheAliases = new Map<string, string>();
const cacheGenerations = new Map<string, number>();
let marketCacheBytes = 0;

type MarketDataResponse = {
  source: string;
  is_adjusted?: boolean | null;
  fingerprint?: string;
  interval?: string;
};

function identityPath(query: AnalysisQuery): string {
  const value = query.instrumentId || query.symbol;
  if (!value) {
    throw new Error('No instrument selected');
  }
  return encodeURIComponent(value);
}

function identityQuery(query: AnalysisQuery) {
  const interval = query.interval ?? '1d';
  return {
    instrument_id: query.instrumentId ?? undefined,
    symbol: query.symbol ?? undefined,
    market: query.market ?? undefined,
    exchange: query.exchange ?? undefined,
    interval,
    days: query.days ?? defaultDaysFor(interval),
    provider: query.provider ?? 'auto',
    direction_mode: query.directionMode ?? 'long_only',
  };
}

function canonicalIdentity(query: AnalysisQuery): string {
  return query.instrumentId
    ?? [query.market ?? '', query.exchange ?? '', query.symbol ?? ''].join(':');
}

function cacheBaseKey(kind: string, query: AnalysisQuery, extra = ''): string {
  return JSON.stringify([
    kind,
    canonicalIdentity(query),
    query.interval ?? '1d',
    query.days ?? defaultDaysFor(query.interval ?? '1d'),
    query.provider ?? 'auto',
    kind === 'analysis' || kind === 'analytics-snapshot'
      ? query.directionMode ?? 'long_only'
      : '',
    extra,
  ]);
}

/**
 * Historical market data is retained much longer than live quotes. The short
 * "fresh" window avoids re-requesting data that cannot have changed; the
 * longer "stale" window lets navigation render immediately while a single
 * background refresh revalidates the entry.
 */
function cacheTtlForInterval(interval: string): { freshMs: number; staleMs: number } {
  switch (interval) {
    case '1m':
      return { freshMs: 15_000, staleMs: 2 * 60_000 };
    case '3m':
      return { freshMs: 20_000, staleMs: 3 * 60_000 };
    case '5m':
      return { freshMs: 30_000, staleMs: 5 * 60_000 };
    case '15m':
    case '30m':
    case '45m':
      return { freshMs: 60_000, staleMs: 15 * 60_000 };
    case '1h':
    case '2h':
    case '4h':
    case '6h':
    case '8h':
    case '12h':
      return { freshMs: 5 * 60_000, staleMs: 60 * 60_000 };
    case '1d':
    case '3d':
      return { freshMs: 15 * 60_000, staleMs: 6 * 60 * 60_000 };
    case '1wk':
    case '1w':
      return { freshMs: 60 * 60_000, staleMs: 24 * 60 * 60_000 };
    case '1mo':
    case '1M':
      return { freshMs: 6 * 60 * 60_000, staleMs: 72 * 60 * 60_000 };
    default:
      return { freshMs: 5 * 60_000, staleMs: 60 * 60_000 };
  }
}

function removeCacheEntry(key: string): void {
  const entry = marketDataCache.get(key);
  if (!entry) return;
  marketDataCache.delete(key);
  marketCacheBytes = Math.max(0, marketCacheBytes - entry.sizeBytes);
  if (cacheAliases.get(entry.baseKey) === key) {
    cacheAliases.delete(entry.baseKey);
  }
}

function evictIfNeeded(): void {
  while (
    marketDataCache.size > MAX_CACHED_RESPONSES
    || marketCacheBytes > MAX_MARKET_CACHE_BYTES
  ) {
    const oldestKey = marketDataCache.keys().next().value;
    if (oldestKey === undefined) break;
    removeCacheEntry(oldestKey);
  }
}

function responseTimestamp(data: MarketDataResponse): number | null {
  const record = data as unknown as Record<string, unknown>;
  const value = record.generated_at ?? record.as_of ?? record.last_candle_at ?? record.latest_candle_timestamp;
  if (!value) return null;
  const parsed = Date.parse(String(value));
  return Number.isNaN(parsed) ? null : parsed;
}

function estimateSizeBytes(data: MarketDataResponse): number {
  try {
    // JSON strings are UTF-16 in JS; x2 is a conservative in-memory estimate.
    return JSON.stringify(data).length * 2;
  } catch {
    return 0;
  }
}

function promoteCacheEntry(key: string, entry: CacheEntry): void {
  marketDataCache.delete(key);
  marketDataCache.set(key, entry);
}

function lookupCachedEntry(
  kind: string,
  query: AnalysisQuery,
  extra = '',
): { key: string; entry: CacheEntry } | null {
  const baseKey = cacheBaseKey(kind, query, extra);
  const cachedKey = cacheAliases.get(baseKey);
  if (!cachedKey) return null;
  const entry = marketDataCache.get(cachedKey);
  if (!entry) {
    cacheAliases.delete(baseKey);
    return null;
  }
  return { key: cachedKey, entry };
}

function peekCachedResponse<T extends MarketDataResponse>(
  kind: string,
  query: AnalysisQuery,
  extra = '',
): T | null {
  const cached = lookupCachedEntry(kind, query, extra);
  if (!cached) return null;
  if (cached.entry.staleUntil <= Date.now()) {
    removeCacheEntry(cached.key);
    return null;
  }
  // A cache hit is promoted to most-recently-used without issuing a request.
  promoteCacheEntry(cached.key, cached.entry);
  return cached.entry.data as T;
}

/** True when the exact request is already cached and does not need a fetch. */
function hasCachedResponse(
  kind: string,
  query: AnalysisQuery,
  extra = '',
): boolean {
  const cached = lookupCachedEntry(kind, query, extra);
  return Boolean(cached && cached.entry.staleUntil > Date.now());
}

function inFlightKeyFor(
  baseKey: string,
  query: AnalysisQuery,
  forceRefresh: boolean,
): string {
  const generation = cacheGenerations.get(canonicalIdentity(query)) ?? 0;
  return JSON.stringify([baseKey, generation, forceRefresh ? 'force' : 'normal']);
}

function sharedRequest<T extends MarketDataResponse>(
  kind: string,
  query: AnalysisQuery,
  baseKey: string,
  forceRefresh: boolean,
  request: () => Promise<T>,
): Promise<T> {
  const instrumentId = canonicalIdentity(query);
  const generation = cacheGenerations.get(instrumentId) ?? 0;
  const inFlightKey = inFlightKeyFor(baseKey, query, forceRefresh);
  const inFlight = inFlightResponses.get(inFlightKey);
  if (inFlight) {
    cacheEvent('dedupe', { kind, key: baseKey });
    return inFlight as Promise<T>;
  }

  cacheEvent('request', { kind, key: baseKey, forceRefresh });
  const pending = request().then((data) => {
    if ((cacheGenerations.get(instrumentId) ?? 0) !== generation) {
      // The instrument was invalidated while this response was in flight.
      return data;
    }

    // Never let a slower, older response replace newer cached analytics for
    // the same instrument/timeframe.
    const existingKey = cacheAliases.get(baseKey);
    const existing = existingKey ? marketDataCache.get(existingKey) : undefined;
    const incomingTime = responseTimestamp(data);
    const existingTime = existing ? responseTimestamp(existing.data) : null;
    if (
      existing
      && incomingTime !== null
      && existingTime !== null
      && incomingTime < existingTime
    ) {
      cacheEvent('skip', { kind, key: baseKey, reason: 'older-response' });
      return existing.data as unknown as T;
    }

    const fingerprint = data.fingerprint
      ?? `${data.interval ?? query.interval ?? '1d'}:${'as_of' in data ? String((data as { as_of?: string }).as_of ?? '') : ''}`;
    const variantKey = JSON.stringify([
      baseKey,
      data.source,
      data.is_adjusted ?? null,
      fingerprint,
    ]);
    const previousVariant = cacheAliases.get(baseKey);
    if (previousVariant && previousVariant !== variantKey) {
      removeCacheEntry(previousVariant);
    }
    removeCacheEntry(variantKey);
    const sizeBytes = estimateSizeBytes(data);
    const ttl = cacheTtlForInterval(query.interval ?? '1d');
    const now = Date.now();
    marketDataCache.set(variantKey, {
      baseKey,
      instrumentId,
      data,
      expiresAt: now + ttl.freshMs,
      staleUntil: now + ttl.freshMs + ttl.staleMs,
      sizeBytes,
    });
    marketCacheBytes += sizeBytes;
    cacheAliases.set(baseKey, variantKey);
    evictIfNeeded();
    cacheEvent('store', { kind, key: baseKey });
    return data;
  });

  inFlightResponses.set(inFlightKey, pending as Promise<MarketDataResponse>);
  void pending.then(
    () => {
      if (inFlightResponses.get(inFlightKey) === pending) inFlightResponses.delete(inFlightKey);
    },
    () => {
      if (inFlightResponses.get(inFlightKey) === pending) inFlightResponses.delete(inFlightKey);
    },
  );
  return pending;
}

function cachedResponse<T extends MarketDataResponse>(
  kind: string,
  query: AnalysisQuery,
  extra: string,
  signal: AbortSignal | undefined,
  request: () => Promise<T>,
  options: { forceRefresh?: boolean } = {},
): Promise<T> {
  const baseKey = cacheBaseKey(kind, query, extra);
  const cached = lookupCachedEntry(kind, query, extra);
  const now = Date.now();

  if (!options.forceRefresh && cached) {
    if (cached.entry.expiresAt > now) {
      if (signal?.aborted) {
        return Promise.reject(new DOMException('The operation was aborted.', 'AbortError'));
      }
      promoteCacheEntry(cached.key, cached.entry);
      cacheEvent('hit', { kind, key: baseKey });
      return Promise.resolve(cached.entry.data as T);
    }
    if (cached.entry.staleUntil > now) {
      if (signal?.aborted) {
        return Promise.reject(new DOMException('The operation was aborted.', 'AbortError'));
      }
      cacheEvent('background-refresh', { kind, key: baseKey });
      // Serve the cached payload immediately; the shared refresh repopulates
      // the cache for the next consumer without blocking this one.
      void sharedRequest(kind, query, baseKey, false, request).catch(() => undefined);
      return Promise.resolve(cached.entry.data as T);
    }
    removeCacheEntry(cached.key);
  } else if (cached) {
    removeCacheEntry(cached.key);
  }

  if (signal?.aborted) {
    // If another consumer already owns a shared request, let this caller join
    // it; aborting one subscription must not cancel work others still need.
    if (!inFlightResponses.has(inFlightKeyFor(baseKey, query, Boolean(options.forceRefresh)))) {
      cacheEvent('cancel', { kind, key: baseKey });
      return Promise.reject(new DOMException('The operation was aborted.', 'AbortError'));
    }
  }

  return sharedRequest(
    kind,
    query,
    baseKey,
    Boolean(options.forceRefresh),
    request,
  );
}

function clearCachedInstrument(instrumentId: string): void {
  cacheGenerations.set(instrumentId, (cacheGenerations.get(instrumentId) ?? 0) + 1);
  for (const [key, value] of marketDataCache) {
    if (value.instrumentId === instrumentId) removeCacheEntry(key);
  }
  cacheEvent('invalidate', { instrumentId });
}

export const analysisService = {
  getAnalysis(query: AnalysisQuery, signal?: AbortSignal): Promise<AnalysisResponse> {
    return cachedResponse<AnalysisResponse>(
      'analysis', query, '', signal,
      () => apiRequest<AnalysisResponse>(
        `/api/instruments/${identityPath(query)}/analysis`,
        { query: identityQuery(query), timeoutMs: LONG_TIMEOUT },
      ),
    );
  },

  getIndicatorSeries(query: AnalysisQuery, signal?: AbortSignal): Promise<IndicatorSeriesResponse> {
    return cachedResponse<IndicatorSeriesResponse>(
      'indicators', query, '', signal,
      () => apiRequest<IndicatorSeriesResponse>(
        `/api/instruments/${identityPath(query)}/indicators`,
        { query: identityQuery(query), timeoutMs: LONG_TIMEOUT },
      ),
    );
  },

  getTechnicals(query: AnalysisQuery, signal?: AbortSignal): Promise<TechnicalSummaryResponse> {
    return cachedResponse<TechnicalSummaryResponse>(
      'technicals-v3', query, '', signal,
      () => apiRequest<TechnicalSummaryResponse>(
        `/api/instruments/${identityPath(query)}/technical-ratings`,
        { query: identityQuery(query), timeoutMs: LONG_TIMEOUT },
      ),
    );
  },

  getCachedAnalyticsSnapshot(query: AnalysisQuery): AnalyticsSnapshotResponse | null {
    return peekCachedResponse<AnalyticsSnapshotResponse>('analytics-snapshot', query);
  },

  hasCachedAnalyticsSnapshot(query: AnalysisQuery): boolean {
    return hasCachedResponse('analytics-snapshot', query);
  },

  getAnalyticsSnapshot(
    query: AnalysisQuery,
    signal?: AbortSignal,
    options: { forceRefresh?: boolean; prefetch?: boolean } = {},
  ): Promise<AnalyticsSnapshotResponse> {
    const requestQuery = {
      ...identityQuery(query),
      refresh: options.forceRefresh ? true : undefined,
      prefetch: options.prefetch ? true : undefined,
    };
    return cachedResponse<AnalyticsSnapshotResponse>(
      'analytics-snapshot', query, '', signal,
      () => apiRequest<AnalyticsSnapshotResponse>(
        `/api/instruments/${identityPath(query)}/analytics-snapshot`,
        { query: requestQuery, timeoutMs: LONG_TIMEOUT },
      ),
      options,
    );
  },

  async prefetchTimeframes(
    query: AnalysisQuery,
    intervals: string[],
    signal?: AbortSignal,
    onProgress?: PrefetchProgress,
  ): Promise<PrefetchResult> {
    const activeInterval = query.interval ?? '1d';
    // Only genuinely missing timeframes are fetched. A cached timeframe is
    // returned instantly by getAnalyticsSnapshot, so asking for it again would
    // only add bookkeeping, not value.
    const targets = [...new Set(intervals)].filter((interval) => {
      if (interval === activeInterval) return false;
      const targetQuery = { ...query, interval, days: defaultDaysFor(interval) };
      if (hasCachedResponse('analytics-snapshot', targetQuery)) {
        cacheEvent('hit', { kind: 'prefetch', interval });
        return false;
      }
      return true;
    });
    const result: PrefetchResult = { total: targets.length, completed: 0, failures: [] };
    if (signal?.aborted || targets.length === 0) {
      return result;
    }
    cacheEvent('prefetch', { instrument: canonicalIdentity(query), intervals: targets });

    let nextIndex = 0;
    const worker = async (): Promise<void> => {
      while (!signal?.aborted) {
        const index = nextIndex;
        nextIndex += 1;
        if (index >= targets.length) return;
        const interval = targets[index];
        if (!interval) return;
        try {
          await this.getAnalyticsSnapshot(
            { ...query, interval, days: defaultDaysFor(interval) },
            undefined,
            { prefetch: true },
          );
        } catch (error) {
          if (signal?.aborted || (error instanceof DOMException && error.name === 'AbortError')) {
            return;
          }
          result.failures.push({
            interval,
            error: error instanceof Error ? error.message : 'Timeframe preparation failed',
          });
        } finally {
          if (!signal?.aborted) {
            result.completed += 1;
            onProgress?.({ ...result, failures: [...result.failures] });
          }
        }
      }
    };

    const workers = Math.min(TIMEFRAME_PREFETCH_CONCURRENCY, targets.length);
    await Promise.all(Array.from({ length: workers }, () => worker()));
    return { ...result, failures: [...result.failures] };
  },

  async prefetchWatchlistSnapshots(
    instruments: Array<Pick<AnalysisQuery, 'instrumentId' | 'symbol' | 'market' | 'exchange'>>,
    query: Pick<AnalysisQuery, 'interval' | 'days' | 'provider' | 'directionMode'>,
    skipInstrumentId?: string,
    signal?: AbortSignal,
  ): Promise<void> {
    const seen = new Set<string>();
    const targets = instruments.filter((instrument) => {
      const identity = canonicalIdentity(instrument);
      if (identity === skipInstrumentId || seen.has(identity)) return false;
      seen.add(identity);
      const targetQuery = { ...instrument, ...query };
      if (hasCachedResponse('analytics-snapshot', targetQuery)) {
        cacheEvent('hit', { kind: 'watchlist-prefetch', instrument: identity });
        return false;
      }
      return true;
    });
    if (signal?.aborted || targets.length === 0) return;
    cacheEvent('prefetch', { kind: 'watchlist', instruments: targets.length });

    let nextIndex = 0;
    const worker = async (): Promise<void> => {
      while (!signal?.aborted) {
        const instrument = targets[nextIndex];
        nextIndex += 1;
        if (!instrument) return;
        try {
          // Stop scheduling when the page context changes, but let an already
          // started request finish and populate the shared cache.
          await this.getAnalyticsSnapshot(
            { ...instrument, ...query },
            undefined,
            { prefetch: true },
          );
        } catch {
          // A failed warm-up must not block other watchlist instruments.
        }
      }
    };

    const workers = Math.min(TIMEFRAME_PREFETCH_CONCURRENCY, targets.length);
    await Promise.all(Array.from({ length: workers }, () => worker()));
  },

  invalidateInstrumentCache(instrumentId: string): void {
    clearCachedInstrument(instrumentId);
  },
};
