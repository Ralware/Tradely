import { apiRequest } from './api';
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

export const portfolioService = {
  getTransactions(signal?: AbortSignal): Promise<TransactionsResponse> {
    return apiRequest<TransactionsResponse>('/api/portfolio/transactions', {
      signal,
      timeoutMs: SHORT_TIMEOUT,
    });
  },

  addTransaction(payload: TransactionRequest): Promise<AddTransactionResponse> {
    return apiRequest<AddTransactionResponse>('/api/portfolio/transactions', {
      method: 'POST',
      body: payload,
      timeoutMs: QUOTE_TIMEOUT,
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
    });
  },

  getPositions(signal?: AbortSignal, force = false): Promise<PositionsResponse> {
    return apiRequest<PositionsResponse>('/api/portfolio/positions', {
      query: { force },
      signal,
      timeoutMs: QUOTE_TIMEOUT,
    });
  },

  getSummary(signal?: AbortSignal, force = false): Promise<PortfolioSummary> {
    return apiRequest<PortfolioSummary>('/api/portfolio/summary', {
      query: { force },
      signal,
      timeoutMs: QUOTE_TIMEOUT,
    });
  },

  getPositionDetail(
    instrumentId: string,
    signal?: AbortSignal,
    options: { force?: boolean; days?: number } = {},
  ): Promise<PositionDetailResponse> {
    return apiRequest<PositionDetailResponse>(
      `/api/portfolio/positions/${encodeURIComponent(instrumentId)}`,
      {
        query: { force: options.force, days: options.days },
        signal,
        timeoutMs: QUOTE_TIMEOUT,
      },
    );
  },

  getWatchlist(signal?: AbortSignal): Promise<WatchlistResponse> {
    return apiRequest<WatchlistResponse>('/api/watchlist', { signal, timeoutMs: SHORT_TIMEOUT });
  },

  addWatchlist(payload: AddWatchlistRequest): Promise<WatchlistItem> {
    return apiRequest<WatchlistItem>('/api/watchlist', {
      method: 'POST',
      body: payload,
      timeoutMs: SHORT_TIMEOUT,
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
      );
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
    );
  },
};
