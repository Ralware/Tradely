import { apiRequest } from './api';
import { cacheEvent } from './cacheDiagnostics';
import type {
  Instrument,
  InstrumentResolutionResponse,
  InstrumentSearchResponse,
} from '../types/api';

const SHORT_TIMEOUT = 15_000;
const INSTRUMENT_TTL = 24 * 60 * 60_000;
const RESOLUTION_TTL = 5 * 60_000;

interface TimedEntry<T> {
  data: T;
  fetchedAt: number;
}

const instrumentCache = new Map<string, TimedEntry<Instrument>>();
const instrumentInFlight = new Map<string, Promise<Instrument>>();
const resolutionCache = new Map<string, TimedEntry<InstrumentResolutionResponse>>();
const resolutionInFlight = new Map<string, Promise<InstrumentResolutionResponse>>();

function cacheEventFor(kind: string, key: string, event: 'hit' | 'request' | 'dedupe' | 'store') {
  cacheEvent(event, { kind, key });
}

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

  resolve(query: string, _signal?: AbortSignal): Promise<InstrumentResolutionResponse> {
    const key = query.trim().toLowerCase();
    const cached = resolutionCache.get(key);
    if (cached && Date.now() - cached.fetchedAt < RESOLUTION_TTL) {
      cacheEventFor('instrument-resolution', key, 'hit');
      return Promise.resolve(cached.data);
    }
    const pending = resolutionInFlight.get(key);
    if (pending) {
      cacheEventFor('instrument-resolution', key, 'dedupe');
      return pending;
    }
    cacheEventFor('instrument-resolution', key, 'request');
    let request: Promise<InstrumentResolutionResponse>;
    request = apiRequest<InstrumentResolutionResponse>('/api/instruments/resolve', {
      query: { query },
      timeoutMs: SHORT_TIMEOUT,
    }).then((response) => {
      resolutionCache.set(key, { data: response, fetchedAt: Date.now() });
      cacheEventFor('instrument-resolution', key, 'store');
      return response;
    }).finally(() => {
      if (resolutionInFlight.get(key) === request) resolutionInFlight.delete(key);
    });
    resolutionInFlight.set(key, request);
    return request;
  },

  get(instrumentId: string, signal?: AbortSignal): Promise<Instrument> {
    void signal;
    const cached = instrumentCache.get(instrumentId);
    if (cached && Date.now() - cached.fetchedAt < INSTRUMENT_TTL) {
      cacheEventFor('instrument', instrumentId, 'hit');
      return Promise.resolve(cached.data);
    }
    const pending = instrumentInFlight.get(instrumentId);
    if (pending) {
      cacheEventFor('instrument', instrumentId, 'dedupe');
      return pending;
    }
    cacheEventFor('instrument', instrumentId, 'request');
    let request: Promise<Instrument>;
    request = apiRequest<Instrument>(
      `/api/instruments/${encodeURIComponent(instrumentId)}`,
      { timeoutMs: SHORT_TIMEOUT },
    ).then((instrument) => {
      instrumentCache.set(instrumentId, { data: instrument, fetchedAt: Date.now() });
      cacheEventFor('instrument', instrumentId, 'store');
      return instrument;
    }).finally(() => {
      if (instrumentInFlight.get(instrumentId) === request) instrumentInFlight.delete(instrumentId);
    });
    instrumentInFlight.set(instrumentId, request);
    return request;
  },

  getCached(instrumentId: string): Instrument | null {
    return instrumentCache.get(instrumentId)?.data ?? null;
  },

  invalidate(instrumentId?: string): void {
    if (instrumentId) {
      instrumentCache.delete(instrumentId);
      return;
    }
    instrumentCache.clear();
    instrumentInFlight.clear();
    resolutionCache.clear();
    resolutionInFlight.clear();
    cacheEvent('invalidate', { kind: 'instrument' });
  },
};
