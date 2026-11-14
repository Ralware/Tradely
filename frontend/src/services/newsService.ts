import { apiRequest } from './api';
import type { Market, NewsResponse } from '../types/api';

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
};
