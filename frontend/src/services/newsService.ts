import { apiRequest } from './api';
import type { Market, NewsResponse } from '../types/api';

export const newsService = {
  getNews(
    query: {
      instrumentId?: string | null;
      symbol?: string;
      market?: Market;
      companyName?: string | null;
      limit?: number;
    },
    signal?: AbortSignal,
  ): Promise<NewsResponse> {
    const path = query.instrumentId || query.symbol;
    if (!path) {
      throw new Error('No instrument selected');
    }
    return apiRequest<NewsResponse>(`/api/instruments/${encodeURIComponent(path)}/news`, {
      query: {
        instrument_id: query.instrumentId ?? undefined,
        market: query.instrumentId ? undefined : query.market,
        company_name: query.companyName ?? undefined,
        limit: query.limit ?? 20,
      },
      signal,
      timeoutMs: 60_000,
    });
  },
};
