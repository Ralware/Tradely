import { apiRequest } from './api';
import type {
  AnalysisResponse,
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

const LONG_TIMEOUT = 120_000;
const MARKET_DATA_CACHE_TTL_MS = 60_000;
const MAX_CACHED_RESPONSES = 120;
const MAX_PREFETCH_INTERVALS = 2;
const marketDataCache = new Map<string, {
  baseKey: string;
  instrumentId: string;
  data: MarketDataResponse;
  expiresAt: number;
}>();
const cacheAliases = new Map<string, string>();

type MarketDataResponse = {
  source: string;
  is_adjusted?: boolean;
};

function identityPath(query: AnalysisQuery): string {
  const value = query.instrumentId || query.symbol;
  if (!value) {
    throw new Error('No instrument selected');
  }
  return encodeURIComponent(value);
}

function identityQuery(query: AnalysisQuery) {
  return {
    instrument_id: query.instrumentId ?? undefined,
    symbol: query.symbol ?? undefined,
    market: query.market ?? undefined,
    exchange: query.exchange ?? undefined,
    interval: query.interval ?? '1d',
    days: query.days ?? defaultDaysFor(query.interval ?? '1d'),
    provider: query.provider ?? 'auto',
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
    kind === 'analysis' ? query.directionMode ?? 'long_only' : '',
    extra,
  ]);
}

function cachedResponse<T extends MarketDataResponse>(
  kind: string,
  query: AnalysisQuery,
  extra: string,
  signal: AbortSignal | undefined,
  request: () => Promise<T>,
): Promise<T> {
  const baseKey = cacheBaseKey(kind, query, extra);
  const cachedKey = cacheAliases.get(baseKey);
  const cached = cachedKey ? marketDataCache.get(cachedKey) : undefined;

  if (cached && cached.expiresAt > Date.now()) {
    if (signal?.aborted) {
      return Promise.reject(new DOMException('The operation was aborted.', 'AbortError'));
    }
    return Promise.resolve(cached.data as T);
  }
  if (cachedKey) {
    marketDataCache.delete(cachedKey);
    cacheAliases.delete(baseKey);
  }

  return request().then((data) => {
    if (!signal?.aborted) {
      const variantKey = JSON.stringify([
        baseKey,
        data.source,
        data.is_adjusted ?? null,
      ]);
      marketDataCache.delete(variantKey);
      marketDataCache.set(variantKey, {
        baseKey,
        instrumentId: canonicalIdentity(query),
        data,
        expiresAt: Date.now() + MARKET_DATA_CACHE_TTL_MS,
      });
      cacheAliases.set(baseKey, variantKey);

      while (marketDataCache.size > MAX_CACHED_RESPONSES) {
        const oldestKey = marketDataCache.keys().next().value;
        if (oldestKey === undefined) {
          break;
        }
        const oldest = marketDataCache.get(oldestKey);
        marketDataCache.delete(oldestKey);
        if (oldest && cacheAliases.get(oldest.baseKey) === oldestKey) {
          cacheAliases.delete(oldest.baseKey);
        }
      }
    }
    return data;
  });
}

function clearCachedInstrument(instrumentId: string): void {
  for (const [key, value] of marketDataCache) {
    if (value.instrumentId !== instrumentId) {
      continue;
    }
    marketDataCache.delete(key);
    if (cacheAliases.get(value.baseKey) === key) {
      cacheAliases.delete(value.baseKey);
    }
  }
}

export const analysisService = {
  getAnalysis(query: AnalysisQuery, signal?: AbortSignal): Promise<AnalysisResponse> {
    return cachedResponse<AnalysisResponse>(
      'analysis',
      query,
      '',
      signal,
      () => apiRequest<AnalysisResponse>(
        `/api/instruments/${identityPath(query)}/analysis`,
        {
          query: {
            ...identityQuery(query),
            direction_mode: query.directionMode ?? 'long_only',
          },
          signal,
          timeoutMs: LONG_TIMEOUT,
        },
      ),
    );
  },

  getIndicatorSeries(
    query: AnalysisQuery,
    signal?: AbortSignal,
  ): Promise<IndicatorSeriesResponse> {
    return cachedResponse<IndicatorSeriesResponse>(
      'indicators',
      query,
      '',
      signal,
      () => apiRequest<IndicatorSeriesResponse>(
        `/api/instruments/${identityPath(query)}/indicators`,
        {
          query: identityQuery(query),
          signal,
          timeoutMs: LONG_TIMEOUT,
        },
      ),
    );
  },

  getTechnicals(query: AnalysisQuery, signal?: AbortSignal): Promise<TechnicalSummaryResponse> {
    return cachedResponse<TechnicalSummaryResponse>(
      'technicals',
      query,
      '',
      signal,
      () => apiRequest<TechnicalSummaryResponse>(
        `/api/instruments/${identityPath(query)}/technicals`,
        {
          query: identityQuery(query),
          signal,
          timeoutMs: LONG_TIMEOUT,
        },
      ),
    );
  },

  async prefetchTimeframes(
    query: AnalysisQuery,
    intervals: string[],
    signal?: AbortSignal,
  ): Promise<void> {
    const targets = [...new Set(intervals)]
      .filter((interval) => interval !== (query.interval ?? '1d'))
      .slice(0, MAX_PREFETCH_INTERVALS);

    for (const interval of targets) {
      if (signal?.aborted) {
        return;
      }
      await analysisService.getAnalysis(
        { ...query, interval, days: defaultDaysFor(interval) },
        signal,
      );
    }
  },

  invalidateInstrumentCache(instrumentId: string): void {
    clearCachedInstrument(instrumentId);
  },
};
