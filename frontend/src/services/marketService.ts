import { apiRequest } from './api';
import { cacheEvent } from './cacheDiagnostics';
import type {
  CandlesResponse,
  Market,
  ScannerResponse,
} from '../types/api';

export interface CandleQuery {
  instrumentId?: string | null;
  symbol?: string;
  market?: Market;
  exchange?: string | null;
  interval?: string;
  days?: number;
  provider?: string;
}

const LONG_TIMEOUT = 120_000;

interface CandleCacheEntry {
  data: CandlesResponse;
  fetchedAt: number;
}

const candleCache = new Map<string, CandleCacheEntry>();
const candleInFlight = new Map<string, Promise<CandlesResponse>>();
let candleGeneration = 0;

function candleKey(query: CandleQuery): string {
  return JSON.stringify([
    query.instrumentId ?? query.symbol ?? '',
    query.market ?? '',
    query.exchange ?? '',
    query.interval ?? '1d',
    query.days ?? 365,
    query.provider ?? 'auto',
  ]);
}

function candleTtl(interval: string): number {
  switch (interval) {
    case '1m':
      return 30_000;
    case '3m':
    case '5m':
      return 60_000;
    case '15m':
    case '30m':
    case '45m':
      return 2 * 60_000;
    case '1h':
    case '2h':
    case '4h':
    case '6h':
    case '8h':
    case '12h':
      return 5 * 60_000;
    case '1d':
    case '3d':
      return 15 * 60_000;
    case '1wk':
    case '1w':
      return 60 * 60_000;
    case '1mo':
    case '1M':
      return 6 * 60 * 60_000;
    default:
      return 5 * 60_000;
  }
}

function normalizeQuery(query: CandleQuery) {
  return {
    instrument_id: query.instrumentId ?? undefined,
    symbol: query.symbol ?? undefined,
    market: query.market ?? undefined,
    exchange: query.exchange ?? undefined,
    interval: query.interval ?? '1d',
    days: query.days ?? 365,
    provider: query.provider ?? 'auto',
  };
}

export const marketService = {
  /**
   * Historical candles are cached by instrument + interval + history window.
   * The cache is application-scoped, so opening the same instrument again (or
   * the watchlist sparkline for it) does not re-request historical data.
   */
  getCandles(
    query: CandleQuery,
    signal?: AbortSignal,
    options: { force?: boolean } = {},
  ): Promise<CandlesResponse> {
    void signal;
    const key = candleKey(query);
    const interval = query.interval ?? '1d';
    const cached = candleCache.get(key);
    if (!options.force && cached && Date.now() - cached.fetchedAt < candleTtl(interval)) {
      cacheEvent('hit', { kind: 'candles', key });
      return Promise.resolve(cached.data);
    }
    const pending = candleInFlight.get(key);
    if (pending) {
      cacheEvent('dedupe', { kind: 'candles', key });
      return pending;
    }

    const generation = candleGeneration;
    cacheEvent('request', { kind: 'candles', key, force: Boolean(options.force) });
    let request: Promise<CandlesResponse>;
    request = apiRequest<CandlesResponse>('/api/market/candles', {
      query: normalizeQuery(query),
      timeoutMs: LONG_TIMEOUT,
    }).then((data) => {
      if (generation === candleGeneration) {
        candleCache.set(key, { data, fetchedAt: Date.now() });
        cacheEvent('store', { kind: 'candles', key });
      }
      return data;
    }).finally(() => {
      if (candleInFlight.get(key) === request) candleInFlight.delete(key);
    });
    candleInFlight.set(key, request);
    return request;
  },

  getCachedCandles(query: CandleQuery): CandlesResponse | null {
    return candleCache.get(candleKey(query))?.data ?? null;
  },

  invalidateCandles(query?: CandleQuery): void {
    if (query) {
      candleCache.delete(candleKey(query));
      return;
    }
    candleGeneration += 1;
    candleCache.clear();
    candleInFlight.clear();
    cacheEvent('invalidate', { kind: 'candles' });
  },

  getScanner(signal?: AbortSignal): Promise<ScannerResponse> {
    return apiRequest<ScannerResponse>('/api/scanner/watchlist', {
      signal,
      timeoutMs: LONG_TIMEOUT,
    });
  },
};
