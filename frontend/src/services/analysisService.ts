import { apiRequest } from './api';
import type {
  AnalysisResponse,
  IndicatorSeriesResponse,
  Market,
  SignalsHistoryResponse,
  TechnicalSummaryResponse,
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

  getSignalsHistory(limit = 50, signal?: AbortSignal): Promise<SignalsHistoryResponse> {
    return apiRequest<SignalsHistoryResponse>('/api/signals/history', {
      query: { limit },
      signal,
      timeoutMs: 15_000,
    });
  },

  getTechnicals(query: AnalysisQuery, signal?: AbortSignal): Promise<TechnicalSummaryResponse> {
    return apiRequest<TechnicalSummaryResponse>(
      `/api/instruments/${encodeURIComponent(query.symbol)}/technicals`,
      {
        query: analysisQuery(query),
        signal,
        timeoutMs: LONG_TIMEOUT,
      },
    );
  },
};
