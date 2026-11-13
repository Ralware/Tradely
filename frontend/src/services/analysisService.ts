import { apiRequest } from './api';
import type {
  AnalysisResponse,
  FundamentalsResponse,
  IndicatorSeriesResponse,
  Market,
  SignalsHistoryResponse,
} from '../types/api';

export interface AnalysisQuery {
  symbol: string;
  market: Market;
  exchange?: string | null;
  interval?: string;
  days?: number;
  provider?: string;
}

const LONG_TIMEOUT = 120_000;

function analysisQuery(query: AnalysisQuery) {
  return {
    symbol: query.symbol,
    market: query.market,
    exchange: query.exchange ?? undefined,
    interval: query.interval ?? '1d',
    days: query.days ?? 500,
    provider: query.provider ?? 'auto',
  };
}

export const analysisService = {
  getAnalysis(query: AnalysisQuery, signal?: AbortSignal): Promise<AnalysisResponse> {
    return apiRequest<AnalysisResponse>(
      `/api/instruments/${encodeURIComponent(query.symbol)}/analysis`,
      { query: analysisQuery(query), signal, timeoutMs: LONG_TIMEOUT },
    );
  },

  getIndicatorSeries(
    query: AnalysisQuery & { limit?: number },
    signal?: AbortSignal,
  ): Promise<IndicatorSeriesResponse> {
    return apiRequest<IndicatorSeriesResponse>(
      `/api/instruments/${encodeURIComponent(query.symbol)}/indicators`,
      {
        query: { ...analysisQuery(query), limit: query.limit ?? 300 },
        signal,
        timeoutMs: LONG_TIMEOUT,
      },
    );
  },

  getFundamentals(
    query: { symbol: string; market: Market; exchange?: string | null },
    signal?: AbortSignal,
  ): Promise<FundamentalsResponse> {
    return apiRequest<FundamentalsResponse>(
      `/api/instruments/${encodeURIComponent(query.symbol)}/fundamentals`,
      {
        query: {
          market: query.market,
          exchange: query.exchange ?? undefined,
        },
        signal,
        timeoutMs: LONG_TIMEOUT,
      },
    );
  },

  getSignalsHistory(limit = 50, signal?: AbortSignal): Promise<SignalsHistoryResponse> {
    return apiRequest<SignalsHistoryResponse>('/api/signals/history', {
      query: { limit },
      signal,
      timeoutMs: 15_000,
    });
  },
};
