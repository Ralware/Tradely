import { apiRequest } from './api';
import type { Instrument } from '../types/api';

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

interface Cached<T> { value: T; storedAt: number }
const CACHE_MS = 25_000;
const feedCache = new Map<string, Cached<NewsFeedResponse>>();
const inFlight = new Map<string, Promise<NewsFeedResponse>>();
const searchCache = new Map<string, Cached<NewsSearchResponse>>();

function getFresh<T>(cache: Map<string, Cached<T>>, key: string): T | undefined {
  const entry = cache.get(key);
  if (entry && Date.now() - entry.storedAt < CACHE_MS) return entry.value;
  return undefined;
}

function cached<T>(cache: Map<string, Cached<T>>, key: string, value: T): T {
  cache.set(key, { value, storedAt: Date.now() });
  return value;
}

export const newsService = {
  cachedSymbol(instrumentId: string, page = 1, pageSize = 10, filters: { q?: string; dateFrom?: string; dateTo?: string } = {}): NewsFeedResponse | undefined {
    return feedCache.get(symbolKey(instrumentId, page, pageSize, filters))?.value;
  },

  symbolFeed(
    instrumentId: string,
    symbol: string,
    options: { page?: number; pageSize?: number; q?: string; dateFrom?: string; dateTo?: string; signal?: AbortSignal } = {},
  ): Promise<NewsFeedResponse> {
    const page = options.page ?? 1;
    const pageSize = options.pageSize ?? 10;
    const key = symbolKey(instrumentId, page, pageSize, options);
    const fresh = getFresh(feedCache, key);
    if (fresh) return Promise.resolve(fresh);
    const existing = inFlight.get(key);
    if (existing) return existing;
    const request = apiRequest<NewsFeedResponse>(`/api/news/${encodeURIComponent(symbol)}`, {
      query: { instrument_id: instrumentId, page, page_size: pageSize, q: options.q, date_from: options.dateFrom, date_to: options.dateTo },
      signal: options.signal,
      timeoutMs: 15_000,
    }).then((value) => cached(feedCache, key, value)).finally(() => inFlight.delete(key));
    inFlight.set(key, request);
    return request;
  },

  cachedGeneral(params: { page?: number; pageSize?: number; q?: string; dateFrom?: string; dateTo?: string }): NewsFeedResponse | undefined {
    const key = generalKey(params);
    return feedCache.get(key)?.value;
  },

  generalFeed(
    params: { page?: number; pageSize?: number; q?: string; dateFrom?: string; dateTo?: string; signal?: AbortSignal },
  ): Promise<NewsFeedResponse> {
    const key = generalKey(params);
    const fresh = getFresh(feedCache, key);
    if (fresh) return Promise.resolve(fresh);
    const existing = inFlight.get(key);
    if (existing) return existing;
    const request = apiRequest<NewsFeedResponse>('/api/news', {
      query: {
        page: params.page ?? 1,
        page_size: params.pageSize ?? 20,
        q: params.q,
        date_from: params.dateFrom,
        date_to: params.dateTo,
        sort: 'newest',
      },
      signal: params.signal,
      timeoutMs: 15_000,
    }).then((value) => cached(feedCache, key, value)).finally(() => inFlight.delete(key));
    inFlight.set(key, request);
    return request;
  },

  search(query: string, signal?: AbortSignal): Promise<NewsSearchResponse> {
    const key = `search:${query.trim().toLocaleLowerCase()}`;
    const fresh = getFresh(searchCache, key);
    if (fresh) return Promise.resolve(fresh);
    return apiRequest<NewsSearchResponse>('/api/news/search', {
      query: { q: query.trim() }, signal, timeoutMs: 12_000,
    }).then((value) => cached(searchCache, key, value));
  },

  refresh(symbol: string, instrumentId: string, signal?: AbortSignal): Promise<{ status: string }> {
    return apiRequest<{ status: string }>(`/api/news/${encodeURIComponent(symbol)}/refresh`, {
      method: 'POST', query: { instrument_id: instrumentId }, signal, timeoutMs: 8_000,
    });
  },
};

function generalKey(params: { page?: number; pageSize?: number; q?: string; dateFrom?: string; dateTo?: string }): string {
  return `general:${params.page ?? 1}:${params.pageSize ?? 20}:${params.q ?? ''}:${params.dateFrom ?? ''}:${params.dateTo ?? ''}`;
}

function symbolKey(instrumentId: string, page: number, pageSize: number, filters: { q?: string; dateFrom?: string; dateTo?: string }): string {
  return `symbol:${instrumentId}:${page}:${pageSize}:${filters.q ?? ''}:${filters.dateFrom ?? ''}:${filters.dateTo ?? ''}`;
}
