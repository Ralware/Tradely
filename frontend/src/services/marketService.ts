import { apiRequest } from './api';
import type {
  CandlesResponse,
  HealthResponse,
  Market,
  ProvidersResponse,
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

export const marketService = {
  getHealth(signal?: AbortSignal): Promise<HealthResponse> {
    return apiRequest<HealthResponse>('/api/health', { signal, timeoutMs: 10_000 });
  },

  getProviders(signal?: AbortSignal): Promise<ProvidersResponse> {
    return apiRequest<ProvidersResponse>('/api/providers/status', { signal, timeoutMs: 10_000 });
  },

  getCandles(query: CandleQuery, signal?: AbortSignal): Promise<CandlesResponse> {
    return apiRequest<CandlesResponse>('/api/market/candles', {
      query: {
        instrument_id: query.instrumentId ?? undefined,
        symbol: query.symbol ?? undefined,
        market: query.market ?? undefined,
        exchange: query.exchange ?? undefined,
        interval: query.interval ?? '1d',
        days: query.days ?? 365,
        provider: query.provider ?? 'auto',
      },
      signal,
      timeoutMs: LONG_TIMEOUT,
    });
  },

  getScanner(signal?: AbortSignal): Promise<ScannerResponse> {
    return apiRequest<ScannerResponse>('/api/scanner/watchlist', {
      signal,
      timeoutMs: LONG_TIMEOUT,
    });
  },
};
