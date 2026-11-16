import { apiRequest } from './api';
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

export const marketService = {
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
