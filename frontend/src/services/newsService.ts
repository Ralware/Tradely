import { apiRequest } from './api';
import type { Instrument } from '../types/api';
import { localDateToApiBound } from './newsDateRange';

export interface NewsArticle {
  id: string;
  title: string;
  summary: string | null;
  publisher: string | null;
  published_at: string | null;
  article_url: string;
  thumbnail_url: string | null;
  related_symbols: string[];
  primary_symbol: string | null;
  source: string;
  first_seen_at: string;
  last_updated_at: string;
}

export interface NewsFeedResponse {
  items: NewsArticle[];
  count: number;
  page: number;
  page_size: number;
  stale: boolean;
  last_updated?: string | null;
  last_successful_refresh?: string | null;
  last_attempted_refresh?: string | null;
  refresh_status?: string;
  provider_status?: string;
  error_code?: string | null;
  coverage?: string;
  instrument?: Instrument;
  symbol?: string;
  yahoo_symbol?: string;
  market?: string;
  exchange?: string;
}

export interface NewsInstrumentCandidate {
  instrument_id: string;
  symbol: string;
  yahoo_symbol: string;
  name: string;
  exchange: string;
  market: string;
  instrument_type: string;
  instrument: Instrument;
}

export interface NewsSearchResponse {
  query: string;
  items: NewsInstrumentCandidate[];
  count: number;
  provider: string;
}

// News is intentionally uncached: every consumer polls the backend, and the
// backend schedules a fresh Yahoo Finance refresh for each feed request.
const inFlight = new Map<string, Promise<NewsFeedResponse>>();

export const newsService = {
  symbolFeed(
    instrumentId: string,
    symbol: string,
    options: { page?: number; pageSize?: number; q?: string; dateFrom?: string; dateTo?: string; signal?: AbortSignal } = {},
  ): Promise<NewsFeedResponse> {
    const page = options.page ?? 1;
    const pageSize = options.pageSize ?? 10;
    const key = symbolKey(instrumentId, page, pageSize, options);
    const existing = inFlight.get(key);
    if (existing) return existing;
    const request = apiRequest<NewsFeedResponse>(`/api/news/${encodeURIComponent(symbol)}`, {
      query: {
        instrument_id: instrumentId, page, page_size: pageSize, q: options.q,
        date_from: options.dateFrom ? localDateToApiBound(options.dateFrom) : undefined,
        date_to: options.dateTo ? localDateToApiBound(options.dateTo, true) : undefined,
      },
      timeoutMs: 15_000,
    }).finally(() => inFlight.delete(key));
    inFlight.set(key, request);
    return request;
  },

  generalFeed(
    params: { page?: number; pageSize?: number; q?: string; dateFrom?: string; dateTo?: string; signal?: AbortSignal },
  ): Promise<NewsFeedResponse> {
    const key = generalKey(params);
    const existing = inFlight.get(key);
    if (existing) return existing;
    const request = apiRequest<NewsFeedResponse>('/api/news', {
      query: {
        page: params.page ?? 1,
        page_size: params.pageSize ?? 20,
        q: params.q,
        date_from: params.dateFrom ? localDateToApiBound(params.dateFrom) : undefined,
        date_to: params.dateTo ? localDateToApiBound(params.dateTo, true) : undefined,
        sort: 'newest',
      },
      timeoutMs: 15_000,
    }).finally(() => inFlight.delete(key));
    inFlight.set(key, request);
    return request;
  },

  search(query: string, signal?: AbortSignal): Promise<NewsSearchResponse> {
    return apiRequest<NewsSearchResponse>('/api/news/search', {
      query: { q: query.trim() }, signal, timeoutMs: 12_000,
    });
  },

  refresh(symbol: string, instrumentId: string, signal?: AbortSignal): Promise<{ status: string }> {
    return apiRequest<{ status: string }>(`/api/news/${encodeURIComponent(symbol)}/refresh`, {
      method: 'POST', query: { instrument_id: instrumentId }, signal, timeoutMs: 8_000,
    });
  },
};

function generalKey(params: { page?: number; pageSize?: number; q?: string; dateFrom?: string; dateTo?: string }): string {
  const startBound = params.dateFrom ? localDateToApiBound(params.dateFrom) ?? '' : '';
  const endBound = params.dateTo ? localDateToApiBound(params.dateTo, true) ?? '' : '';
  return `general:${params.page ?? 1}:${params.pageSize ?? 20}:${params.q ?? ''}:${params.dateFrom ?? ''}:${params.dateTo ?? ''}:${startBound}:${endBound}`;
}

function symbolKey(instrumentId: string, page: number, pageSize: number, filters: { q?: string; dateFrom?: string; dateTo?: string }): string {
  const startBound = filters.dateFrom ? localDateToApiBound(filters.dateFrom) ?? '' : '';
  const endBound = filters.dateTo ? localDateToApiBound(filters.dateTo, true) ?? '' : '';
  return `symbol:${instrumentId}:${page}:${pageSize}:${filters.q ?? ''}:${filters.dateFrom ?? ''}:${filters.dateTo ?? ''}:${startBound}:${endBound}`;
}
