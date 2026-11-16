import { apiRequest } from './api';
import type {
  Instrument,
  InstrumentResolutionResponse,
  InstrumentSearchResponse,
} from '../types/api';

const SHORT_TIMEOUT = 15_000;

export const instrumentService = {
  /** Unified recognition: exact symbols, names, aliases and crypto pairs. */
  search(
    query: string,
    signal?: AbortSignal,
    options: { limit?: number } = {},
  ): Promise<InstrumentSearchResponse> {
    return apiRequest<InstrumentSearchResponse>('/api/instruments/search', {
      query: { q: query, limit: options.limit ?? 20 },
      signal,
      timeoutMs: SHORT_TIMEOUT,
    });
  },

  resolve(query: string, signal?: AbortSignal): Promise<InstrumentResolutionResponse> {
    return apiRequest<InstrumentResolutionResponse>('/api/instruments/resolve', {
      query: { query },
      signal,
      timeoutMs: SHORT_TIMEOUT,
    });
  },

  get(instrumentId: string, signal?: AbortSignal): Promise<Instrument> {
    return apiRequest<Instrument>(
      `/api/instruments/${encodeURIComponent(instrumentId)}`,
      { signal, timeoutMs: SHORT_TIMEOUT },
    );
  },
};
