import { apiRequest } from './api';
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
const MAX_CACHED_RESPONSES = 40;
const MAX_MARKET_CACHE_BYTES = 64 * 1024 * 1024;
const TIMEFRAME_PREFETCH_CONCURRENCY = 2;

const marketDataCache = new Map<string, {
  baseKey: string;
  instrumentId: string;
  data: MarketDataResponse;
  expiresAt: number;
  sizeBytes: number;
}>();
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

function cacheTtlForInterval(interval: string): number {
  // Intraday candles move more frequently; higher timeframes can be held longer.
  if (interval === '1m') return 5_000;
  if (interval === '3m' || interval === '5m') return 10_000;
  if (interval === '15m' || interval === '30m' || interval === '45m') return 20_000;
  if (['1h', '2h', '4h', '6h', '8h', '12h'].includes(interval)) return 45_000;
  if (interval === '1d') return 90_000;
  if (interval === '1wk') return 5 * 60_000;
  if (interval === '1mo') return 10 * 60_000;
  return 60_000;
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

function estimateSizeBytes(data: MarketDataResponse): number {
  try {
    // JSON strings are UTF-16 in JS; x2 is a conservative in-memory estimate.
    return JSON.stringify(data).length * 2;
  } catch {
    return 0;
  }
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
  const cachedKey = cacheAliases.get(baseKey);
  const cached = cachedKey ? marketDataCache.get(cachedKey) : undefined;

  if (!options.forceRefresh && cached && cached.expiresAt > Date.now()) {
    if (signal?.aborted) {
      return Promise.reject(new DOMException('The operation was aborted.', 'AbortError'));
    }
    // Promote the entry to most-recently-used.
    marketDataCache.delete(cachedKey!);
    marketDataCache.set(cachedKey!, cached);
    return Promise.resolve(cached.data as T);
  }
  if (cachedKey) removeCacheEntry(cachedKey);

  const instrumentId = canonicalIdentity(query);
  const generation = cacheGenerations.get(instrumentId) ?? 0;

  return request().then((data) => {
    if (!signal?.aborted && (cacheGenerations.get(instrumentId) ?? 0) === generation) {
      const fingerprint = data.fingerprint ?? `${data.interval ?? query.interval ?? '1d'}:${'as_of' in data ? String((data as { as_of?: string }).as_of ?? '') : ''}`;
      const variantKey = JSON.stringify([baseKey, data.source, data.is_adjusted ?? null, fingerprint]);
      removeCacheEntry(variantKey);
      const sizeBytes = estimateSizeBytes(data);
      marketDataCache.set(variantKey, {
        baseKey,
        instrumentId,
        data,
        expiresAt: Date.now() + cacheTtlForInterval(query.interval ?? '1d'),
        sizeBytes,
      });
      marketCacheBytes += sizeBytes;
      cacheAliases.set(baseKey, variantKey);

      while (
        marketDataCache.size > MAX_CACHED_RESPONSES
        || marketCacheBytes > MAX_MARKET_CACHE_BYTES
      ) {
        const oldestKey = marketDataCache.keys().next().value;
        if (oldestKey === undefined) break;
        removeCacheEntry(oldestKey);
      }
    }
    return data;
  });
}

function clearCachedInstrument(instrumentId: string): void {
  cacheGenerations.set(instrumentId, (cacheGenerations.get(instrumentId) ?? 0) + 1);
  for (const [key, value] of marketDataCache) {
    if (value.instrumentId === instrumentId) removeCacheEntry(key);
  }
}

export const analysisService = {
  getAnalysis(query: AnalysisQuery, signal?: AbortSignal): Promise<AnalysisResponse> {
    return cachedResponse<AnalysisResponse>(
      'analysis', query, '', signal,
      () => apiRequest<AnalysisResponse>(
        `/api/instruments/${identityPath(query)}/analysis`,
        { query: identityQuery(query), signal, timeoutMs: LONG_TIMEOUT },
      ),
    );
  },

  getIndicatorSeries(query: AnalysisQuery, signal?: AbortSignal): Promise<IndicatorSeriesResponse> {
    return cachedResponse<IndicatorSeriesResponse>(
      'indicators', query, '', signal,
      () => apiRequest<IndicatorSeriesResponse>(
        `/api/instruments/${identityPath(query)}/indicators`,
        { query: identityQuery(query), signal, timeoutMs: LONG_TIMEOUT },
      ),
    );
  },

  getTechnicals(query: AnalysisQuery, signal?: AbortSignal): Promise<TechnicalSummaryResponse> {
    return cachedResponse<TechnicalSummaryResponse>(
      'technicals-v3', query, '', signal,
      () => apiRequest<TechnicalSummaryResponse>(
        `/api/instruments/${identityPath(query)}/technical-ratings`,
        { query: identityQuery(query), signal, timeoutMs: LONG_TIMEOUT },
      ),
    );
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
        { query: requestQuery, signal, timeoutMs: LONG_TIMEOUT },
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
    const targets = [...new Set(intervals)].filter(
      (interval) => interval !== (query.interval ?? '1d'),
    );
    const result: PrefetchResult = { total: targets.length, completed: 0, failures: [] };
    if (signal?.aborted || targets.length === 0) {
      return result;
    }

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
            signal,
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

  invalidateInstrumentCache(instrumentId: string): void {
    clearCachedInstrument(instrumentId);
  },
};
