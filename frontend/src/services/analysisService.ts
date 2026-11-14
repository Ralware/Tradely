import { apiRequest } from './api';
import type {
  AnalysisResponse,
  IndicatorSeriesResponse,
  Market,
  SignalsHistoryResponse,
  TechnicalSummaryResponse,
} from '../types/api';

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
}

const LONG_TIMEOUT = 120_000;

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
    days: query.days ?? 500,
    provider: query.provider ?? 'auto',
  };
}

export const analysisService = {
  getAnalysis(query: AnalysisQuery, signal?: AbortSignal): Promise<AnalysisResponse> {
    return apiRequest<AnalysisResponse>(
      `/api/instruments/${identityPath(query)}/analysis`,
      { query: identityQuery(query), signal, timeoutMs: LONG_TIMEOUT },
    );
  },

  getIndicatorSeries(
    query: AnalysisQuery & { limit?: number },
    signal?: AbortSignal,
  ): Promise<IndicatorSeriesResponse> {
    return apiRequest<IndicatorSeriesResponse>(
      `/api/instruments/${identityPath(query)}/indicators`,
      {
        query: { ...identityQuery(query), limit: query.limit ?? 300 },
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
      `/api/instruments/${identityPath(query)}/technicals`,
      {
        query: identityQuery(query),
        signal,
        timeoutMs: LONG_TIMEOUT,
      },
    );
  },
};
