import { apiRequest } from './api';
import type {
  AddWatchlistRequest,
  Market,
  PositionsResponse,
  TransactionRequest,
  TransactionsResponse,
  WatchlistItem,
  WatchlistResponse,
} from '../types/api';

export const portfolioService = {
  getTransactions(signal?: AbortSignal): Promise<TransactionsResponse> {
    return apiRequest<TransactionsResponse>('/api/portfolio/transactions', {
      signal,
      timeoutMs: 15_000,
    });
  },

  addTransaction(payload: TransactionRequest): Promise<unknown> {
    return apiRequest<unknown>('/api/portfolio/transactions', {
      method: 'POST',
      body: payload,
      timeoutMs: 15_000,
    });
  },

  getPositions(signal?: AbortSignal): Promise<PositionsResponse> {
    return apiRequest<PositionsResponse>('/api/portfolio/positions', {
      signal,
      timeoutMs: 15_000,
    });
  },

  getWatchlist(signal?: AbortSignal): Promise<WatchlistResponse> {
    return apiRequest<WatchlistResponse>('/api/watchlist', { signal, timeoutMs: 15_000 });
  },

  addWatchlist(payload: AddWatchlistRequest): Promise<WatchlistItem> {
    return apiRequest<WatchlistItem>('/api/watchlist', {
      method: 'POST',
      body: payload,
      timeoutMs: 15_000,
    });
  },

  removeWatchlist(payload: {
    symbol: string;
    market: Market;
    exchange?: string | null;
  }): Promise<{ removed: boolean }> {
    return apiRequest<{ removed: boolean }>(
      `/api/watchlist/${encodeURIComponent(payload.market)}/${encodeURIComponent(payload.symbol)}`,
      {
        method: 'DELETE',
        query: { exchange: payload.exchange ?? undefined },
        timeoutMs: 15_000,
      },
    );
  },
};
