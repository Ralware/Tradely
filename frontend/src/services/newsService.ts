import { apiRequest } from './api';
import type {
  EventsResponse,
  Market,
  NewsResponse,
  SecFilingsResponse,
} from '../types/api';

export const newsService = {
  getNews(
    query: { symbol: string; market: Market; companyName?: string | null; limit?: number },
    signal?: AbortSignal,
  ): Promise<NewsResponse> {
    return apiRequest<NewsResponse>(`/api/instruments/${encodeURIComponent(query.symbol)}/news`, {
      query: {
        market: query.market,
        company_name: query.companyName ?? undefined,
        limit: query.limit ?? 20,
      },
      signal,
      timeoutMs: 60_000,
    });
  },

  getEvents(
    query: { symbol: string; market: Market },
    signal?: AbortSignal,
  ): Promise<EventsResponse> {
    return apiRequest<EventsResponse>(
      `/api/instruments/${encodeURIComponent(query.symbol)}/events`,
      {
        query: { market: query.market },
        signal,
        timeoutMs: 30_000,
      },
    );
  },

  getSecFilings(cik: string, signal?: AbortSignal): Promise<SecFilingsResponse> {
    return apiRequest<SecFilingsResponse>(`/api/us/issuers/${encodeURIComponent(cik)}/filings`, {
      signal,
      timeoutMs: 30_000,
    });
  },
};
