import { apiRequest } from './api';
import { cacheEvent } from './cacheDiagnostics';
import type {
  AddTransactionResponse,
  AddWatchlistRequest,
  Market,
  PortfolioSummary,
  PositionDetailResponse,
  PositionsResponse,
  TransactionPreviewResponse,
  TransactionRequest,
  TransactionsResponse,
  WatchlistItem,
  WatchlistResponse,
} from '../types/api';

const SHORT_TIMEOUT = 15_000;
const QUOTE_TIMEOUT = 45_000;
const POSITIONS_TTL = 15_000;
const SUMMARY_TTL = 15_000;
const TRANSACTIONS_TTL = 30_000;
const POSITION_DETAIL_TTL = 60_000;

interface TimedCache<T> {
  data: T;
  fetchedAt: number;
}

/**
 * A small, application-scoped query cache for portfolio and watchlist data.
 * Entries survive component unmounts, so navigating away and back renders the
 * last coherent snapshot immediately instead of re-running the full request
 * set. Manual refreshes and mutations invalidate the relevant entries.
 */
const positionsCache = new Map<string, TimedCache<PositionsResponse>>();
const summaryCache = new Map<string, TimedCache<PortfolioSummary>>();
const transactionsCache = new Map<string, TimedCache<TransactionsResponse>>();
const detailCache = new Map<string, TimedCache<PositionDetailResponse>>();
const positionsInFlight = new Map<string, Promise<PositionsResponse>>();
const summaryInFlight = new Map<string, Promise<PortfolioSummary>>();
const transactionsInFlight = new Map<string, Promise<TransactionsResponse>>();
const detailInFlight = new Map<string, Promise<PositionDetailResponse>>();
let portfolioGeneration = 0;

let watchlistCache: WatchlistResponse | null = null;
let watchlistFetchedAt = 0;
let watchlistInFlight: Promise<WatchlistResponse> | null = null;
let watchlistGeneration = 0;
const watchlistListeners = new Set<() => void>();

function notifyWatchlist(): void {
  watchlistListeners.forEach((listener) => listener());
}

function watchlistKey(item: Pick<WatchlistItem, 'instrument_id' | 'market' | 'exchange' | 'symbol'>): string {
  return item.instrument_id ?? `${item.market}:${item.exchange}:${item.symbol}`;
}

function cachedQuery<T>(
  cache: Map<string, TimedCache<T>>,
  inFlight: Map<string, Promise<T>>,
  key: string,
  freshMs: number,
  force: boolean,
  load: () => Promise<T>,
): Promise<T> {
  const now = Date.now();
  const cached = cache.get(key);
  if (!force && cached && now - cached.fetchedAt < freshMs) {
    cacheEvent('hit', { kind: 'portfolio', key });
    return Promise.resolve(cached.data);
  }
  const refreshKey = key + '\u0000refresh';
  const requestKey = force ? refreshKey : key;
  const pending = inFlight.get(refreshKey) ?? (!force && inFlight.get(key));
  if (pending) {
    cacheEvent('dedupe', { kind: 'portfolio', key });
    return pending;
  }

  const generation = portfolioGeneration;
  cacheEvent('request', { kind: 'portfolio', key, force });
  let request: Promise<T>;
  request = load()
    .then((data) => {
      if (generation === portfolioGeneration && inFlight.get(requestKey) === request) {
        cache.set(key, { data, fetchedAt: Date.now() });
        cacheEvent('store', { kind: 'portfolio', key });
      }
      return data;
    })
    .finally(() => {
      if (inFlight.get(requestKey) === request) inFlight.delete(requestKey);
    });
  if (force) inFlight.delete(key);
  inFlight.set(requestKey, request);
  return request;
}

function invalidatePortfolioCaches(): void {
  portfolioGeneration += 1;
  positionsCache.clear();
  summaryCache.clear();
  transactionsCache.clear();
  detailCache.clear();
  // Requests started before the mutation may still resolve, but they must not
  // be joined by the post-mutation reload (their payload predates the change).
  positionsInFlight.clear();
  summaryInFlight.clear();
  transactionsInFlight.clear();
  detailInFlight.clear();
  cacheEvent('invalidate', { kind: 'portfolio' });
}

function mergeWatchlistItem(item: WatchlistItem): void {
  if (!watchlistCache) {
    // No cached list yet; the next read will fetch the authoritative list.
    return;
  }
  const key = watchlistKey(item);
  const items = watchlistCache.items.filter((existing) => watchlistKey(existing) !== key);
  watchlistCache = { items: [...items, item] };
  watchlistFetchedAt = Date.now();
  notifyWatchlist();
  cacheEvent('store', { kind: 'watchlist', key });
}

function removeWatchlistItem(payload: {
  instrumentId?: string | null;
  symbol?: string;
  market?: Market;
  exchange?: string | null;
}): void {
  if (!watchlistCache) return;
  const key = payload.instrumentId
    ?? `${payload.market ?? ''}:${payload.exchange ?? ''}:${payload.symbol ?? ''}`;
  watchlistCache = {
    items: watchlistCache.items.filter((item) => {
      if (payload.instrumentId && item.instrument_id === payload.instrumentId) return false;
      if (payload.symbol && item.symbol === payload.symbol
        && (!payload.market || item.market === payload.market)) return false;
      return watchlistKey(item) !== key;
    }),
  };
  watchlistFetchedAt = Date.now();
  notifyWatchlist();
  cacheEvent('store', { kind: 'watchlist', key });
}

export const portfolioService = {
  getTransactions(signal?: AbortSignal, force = false): Promise<TransactionsResponse> {
    void signal;
    return cachedQuery(
      transactionsCache,
      transactionsInFlight,
      'transactions',
      TRANSACTIONS_TTL,
      force,
      () => apiRequest<TransactionsResponse>('/api/portfolio/transactions', {
        timeoutMs: SHORT_TIMEOUT,
      }),
    );
  },

  getCachedTransactions(): TransactionsResponse | null {
    return transactionsCache.get('transactions')?.data ?? null;
  },

  addTransaction(payload: TransactionRequest): Promise<AddTransactionResponse> {
    return apiRequest<AddTransactionResponse>('/api/portfolio/transactions', {
      method: 'POST',
      body: payload,
      timeoutMs: QUOTE_TIMEOUT,
    }).then((response) => {
      invalidatePortfolioCaches();
      return response;
    });
  },

  previewTransaction(
    payload: TransactionRequest,
    signal?: AbortSignal,
  ): Promise<TransactionPreviewResponse> {
    return apiRequest<TransactionPreviewResponse>('/api/portfolio/transactions/preview', {
      method: 'POST',
      body: payload,
      signal,
      timeoutMs: QUOTE_TIMEOUT,
    });
  },

  deleteTransaction(id: number): Promise<unknown> {
    return apiRequest<unknown>(`/api/portfolio/transactions/${id}`, {
      method: 'DELETE',
      timeoutMs: SHORT_TIMEOUT,
    }).then((response) => {
      invalidatePortfolioCaches();
      return response;
    });
  },

  getPositions(signal?: AbortSignal, force = false): Promise<PositionsResponse> {
    void signal;
    return cachedQuery(
      positionsCache,
      positionsInFlight,
      'positions',
      POSITIONS_TTL,
      force,
      () => apiRequest<PositionsResponse>('/api/portfolio/positions', {
        query: { force },
        timeoutMs: QUOTE_TIMEOUT,
      }),
    );
  },

  getCachedPositions(): PositionsResponse | null {
    return positionsCache.get('positions')?.data ?? null;
  },

  getSummary(signal?: AbortSignal, force = false): Promise<PortfolioSummary> {
    void signal;
    return cachedQuery(
      summaryCache,
      summaryInFlight,
      'summary',
      SUMMARY_TTL,
      force,
      () => apiRequest<PortfolioSummary>('/api/portfolio/summary', {
        query: { force },
        timeoutMs: QUOTE_TIMEOUT,
      }),
    );
  },

  getCachedSummary(): PortfolioSummary | null {
    return summaryCache.get('summary')?.data ?? null;
  },

  getPositionDetail(
    instrumentId: string,
    signal?: AbortSignal,
    options: { force?: boolean; days?: number } = {},
  ): Promise<PositionDetailResponse> {
    void signal;
    const key = `${instrumentId}\u0000${options.days ?? ''}`;
    return cachedQuery(
      detailCache,
      detailInFlight,
      key,
      POSITION_DETAIL_TTL,
      Boolean(options.force),
      () => apiRequest<PositionDetailResponse>(
        `/api/portfolio/positions/${encodeURIComponent(instrumentId)}`,
        {
          query: { force: options.force, days: options.days },
          timeoutMs: QUOTE_TIMEOUT,
        },
      ),
    );
  },

  getCachedPositionDetail(instrumentId: string, days?: number): PositionDetailResponse | null {
    return detailCache.get(`${instrumentId}\u0000${days ?? ''}`)?.data ?? null;
  },

  getWatchlist(
    signal?: AbortSignal,
    options: { force?: boolean } = {},
  ): Promise<WatchlistResponse> {
    void signal;
    if (!options.force && watchlistCache) {
      cacheEvent('hit', { kind: 'watchlist' });
      return Promise.resolve(watchlistCache);
    }
    if (watchlistInFlight) {
      cacheEvent('dedupe', { kind: 'watchlist' });
      return watchlistInFlight;
    }

    const generation = watchlistGeneration;
    cacheEvent('request', { kind: 'watchlist', force: Boolean(options.force) });
    const request = apiRequest<WatchlistResponse>('/api/watchlist', {
      timeoutMs: SHORT_TIMEOUT,
    }).then((response) => {
      if (generation === watchlistGeneration) {
        watchlistCache = response;
        watchlistFetchedAt = Date.now();
        notifyWatchlist();
        cacheEvent('store', { kind: 'watchlist' });
      }
      return response;
    }).finally(() => {
      if (watchlistInFlight === request) watchlistInFlight = null;
    });
    watchlistInFlight = request;
    return request;
  },

  getCachedWatchlist(): WatchlistResponse | null {
    return watchlistCache;
  },

  getWatchlistFetchedAt(): number {
    return watchlistFetchedAt;
  },

  invalidateWatchlist(): void {
    watchlistGeneration += 1;
    watchlistCache = null;
    watchlistFetchedAt = 0;
    watchlistInFlight = null;
    notifyWatchlist();
    cacheEvent('invalidate', { kind: 'watchlist' });
  },

  subscribeWatchlist(listener: () => void): () => void {
    watchlistListeners.add(listener);
    return () => {
      watchlistListeners.delete(listener);
    };
  },

  addWatchlist(payload: AddWatchlistRequest): Promise<WatchlistItem> {
    return apiRequest<WatchlistItem>('/api/watchlist', {
      method: 'POST',
      body: payload,
      timeoutMs: SHORT_TIMEOUT,
    }).then((item) => {
      watchlistGeneration += 1;
      watchlistInFlight = null;
      mergeWatchlistItem(item);
      return item;
    });
  },

  removeWatchlist(payload: {
    instrumentId?: string | null;
    symbol?: string;
    market?: Market;
    exchange?: string | null;
  }): Promise<{ removed: boolean }> {
    if (payload.instrumentId) {
      return apiRequest<{ removed: boolean }>(
        `/api/watchlist/instruments/${encodeURIComponent(payload.instrumentId)}`,
        { method: 'DELETE', timeoutMs: SHORT_TIMEOUT },
      ).then((response) => {
        watchlistGeneration += 1;
        watchlistInFlight = null;
        removeWatchlistItem(payload);
        return response;
      });
    }
    if (!payload.market || !payload.symbol) {
      throw new Error('Provide instrument id or symbol and market');
    }
    return apiRequest<{ removed: boolean }>(
      `/api/watchlist/${encodeURIComponent(payload.market)}/${encodeURIComponent(payload.symbol)}`,
      {
        method: 'DELETE',
        query: { exchange: payload.exchange ?? undefined },
        timeoutMs: SHORT_TIMEOUT,
      },
    ).then((response) => {
      watchlistGeneration += 1;
      watchlistInFlight = null;
      removeWatchlistItem(payload);
      return response;
    });
  },

  invalidateValuations() {
    positionsCache.clear();
    summaryCache.clear();
    positionsInFlight.clear();
    summaryInFlight.clear();
  },

  invalidatePortfolioCaches,
};
