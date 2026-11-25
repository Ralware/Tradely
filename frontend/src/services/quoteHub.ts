import { buildApiUrl } from './api';
import type { Market, Quote } from '../types/api';

export interface QuoteRef {
  instrument_id: string;
  symbol: string;
  market: Market;
  exchange: string;
  currency?: string;
}

type Listener = () => void;

const STREAM_PATH = '/api/market/quotes/stream';
const QUOTES_PATH = '/api/market/quotes';
const FALLBACK_POLL_MS = 30_000;
const REFRESH_DEBOUNCE_MS = 120;
// A quote fetched this recently is still authoritative enough to render while
// the stream reconnects, so remounting a view must not trigger another batch.
const REUSE_QUOTE_MS = 15_000;

function timestamp(value: string | null | undefined): number {
  if (!value) {
    return 0;
  }
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? 0 : parsed;
}

function isNewer(candidate: Quote, current: Quote): boolean {
  const candidateTime = timestamp(candidate.quote_time);
  const currentTime = timestamp(current.quote_time);
  if (candidateTime !== currentTime) {
    return candidateTime > currentTime;
  }
  return timestamp(candidate.retrieved_at) > timestamp(current.retrieved_at);
}

/**
 * Decides whether a quote may replace the cached value. A provider response
 * with an older timestamp can never overwrite a newer price, and an unavailable
 * response without a price never erases the last valid valuation.
 */
export function resolveQuoteUpdate(current: Quote | undefined, candidate: Quote): Quote | null {
  if (!candidate?.instrument_id) {
    return null;
  }
  if (!current) {
    return candidate;
  }
  if (candidate.price === null && current.price !== null && !candidate.error) {
    return null;
  }
  if (!isNewer(candidate, current)) {
    // Same timestamp but fresher retrieval metadata: keep the price and update
    // freshness/error fields without inventing a new valuation.
    if (
      timestamp(candidate.retrieved_at) > timestamp(current.retrieved_at) &&
      candidate.price === current.price
    ) {
      return { ...current, ...candidate };
    }
    return null;
  }
  return candidate;
}

/**
 * One app-wide quote cache shared by the watchlist, portfolio and analysis
 * surfaces. It keeps a single REST batch and a single SSE subscription per
 * instrument set, so the same provider response is never requested twice for
 * the same visual state.
 */
class QuoteHub {
  private entries = new Map<string, { ref: QuoteRef; count: number }>();
  private quotes = new Map<string, Quote>();
  private listeners = new Set<Listener>();
  private eventSource: EventSource | null = null;
  private streamSignature = '';
  private restController: AbortController | null = null;
  private restInflight = false;
  private restQueued = false;
  private queuedForce = false;
  private refreshTimer: number | null = null;
  private pollTimer: number | null = null;
  private visibilityBound = false;

  retain(instruments: QuoteRef[]): () => void {
    const keys: string[] = [];
    for (const instrument of instruments) {
      if (!instrument.instrument_id) {
        continue;
      }
      const existing = this.entries.get(instrument.instrument_id);
      if (existing) {
        existing.count += 1;
        existing.ref = { ...existing.ref, ...instrument };
      } else {
        this.entries.set(instrument.instrument_id, { ref: instrument, count: 1 });
      }
      keys.push(instrument.instrument_id);
    }
    if (keys.length > 0) {
      this.bindVisibility();
      const needsRefresh = instruments.some((instrument) => {
        const cached = this.quotes.get(instrument.instrument_id);
        if (!cached) return true;
        return Date.now() - timestamp(cached.retrieved_at) > REUSE_QUOTE_MS;
      });
      if (needsRefresh) {
        this.scheduleRefresh();
      }
      this.ensureStream();
    }
    return () => {
      for (const key of keys) {
        const entry = this.entries.get(key);
        if (!entry) {
          continue;
        }
        entry.count -= 1;
        if (entry.count <= 0) {
          this.entries.delete(key);
        }
      }
      if (this.entries.size === 0) {
        this.teardown();
      } else {
        this.ensureStream();
      }
    };
  }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  }

  get(instrumentId: string): Quote | undefined {
    return this.quotes.get(instrumentId);
  }

  has(instrumentId: string): boolean {
    return this.quotes.has(instrumentId);
  }

  refresh(force = true): void {
    this.queuedForce = this.queuedForce || force;
    this.scheduleRefresh(0);
  }

  private notify(): void {
    for (const listener of this.listeners) {
      listener();
    }
  }

  private bindVisibility(): void {
    if (this.visibilityBound || typeof document === 'undefined') {
      return;
    }
    this.visibilityBound = true;
    document.addEventListener('visibilitychange', this.handleVisibility);
  }

  private handleVisibility = (): void => {
    if (document.hidden) {
      this.closeStream();
      this.stopPolling();
      return;
    }
    this.scheduleRefresh();
    this.ensureStream();
  };

  private identifiers(): string[] {
    return [...this.entries.keys()].sort();
  }

  private scheduleRefresh(delay = REFRESH_DEBOUNCE_MS): void {
    if (typeof window === 'undefined') {
      return;
    }
    if (this.refreshTimer !== null) {
      window.clearTimeout(this.refreshTimer);
    }
    this.refreshTimer = window.setTimeout(() => {
      this.refreshTimer = null;
      void this.fetchQuotes();
    }, delay);
  }

  private async fetchQuotes(): Promise<void> {
    if (typeof document !== 'undefined' && document.hidden) {
      return;
    }
    const ids = this.identifiers();
    if (ids.length === 0) {
      return;
    }
    if (this.restInflight) {
      this.restQueued = true;
      return;
    }
    const force = this.queuedForce;
    this.queuedForce = false;
    this.restInflight = true;
    this.restController?.abort();
    const controller = new AbortController();
    this.restController = controller;
    try {
      const url = buildApiUrl(QUOTES_PATH, { instrument_id: ids, force });
      const response = await fetch(url, { signal: controller.signal, headers: { Accept: 'application/json' } });
      if (!response.ok) {
        throw new Error(`Quote request failed: HTTP ${response.status}`);
      }
      const payload = (await response.json()) as { quotes?: Quote[] };
      let changed = false;
      for (const quote of payload.quotes ?? []) {
        if (this.merge(quote)) {
          changed = true;
        }
      }
      if (force) {
        this.queuedForce = false;
      }
      if (changed) {
        this.notify();
      }
      this.startPolling();
    } catch (error) {
      if (!(error instanceof DOMException && error.name === 'AbortError')) {
        this.startPolling();
      }
    } finally {
      this.restInflight = false;
      if (this.restController === controller) {
        this.restController = null;
      }
      if (this.restQueued) {
        this.restQueued = false;
        this.scheduleRefresh(0);
      }
    }
  }

  private merge(quote: Quote): boolean {
    if (!quote?.instrument_id) {
      return false;
    }
    const next = resolveQuoteUpdate(this.quotes.get(quote.instrument_id), quote);
    if (!next) {
      return false;
    }
    this.quotes.set(quote.instrument_id, next);
    return true;
  }

  private streamUrl(ids: string[]): string {
    return buildApiUrl(STREAM_PATH, { instrument_id: ids });
  }

  private ensureStream(): void {
    if (typeof window === 'undefined' || typeof EventSource === 'undefined') {
      return;
    }
    if (document.hidden) {
      return;
    }
    const ids = this.identifiers();
    if (ids.length === 0) {
      this.closeStream();
      return;
    }
    const signature = ids.join(',');
    if (this.eventSource && this.streamSignature === signature) {
      return;
    }
    this.closeStream();
    this.streamSignature = signature;
    const source = new EventSource(this.streamUrl(ids));
    this.eventSource = source;
    source.addEventListener('quote', (event) => {
      try {
        const quote = JSON.parse((event as MessageEvent<string>).data) as Quote;
        if (this.merge(quote)) {
          this.notify();
        }
      } catch {
        // Ignore malformed frames; the REST fallback remains authoritative.
      }
    });
    source.onerror = () => {
      // Native EventSource retries automatically. Keep a slow REST poll alive so
      // the UI still recovers if the stream endpoint is unavailable.
      this.startPolling();
    };
  }

  private closeStream(): void {
    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
    }
    this.streamSignature = '';
  }

  private startPolling(): void {
    if (typeof window === 'undefined' || this.pollTimer !== null) {
      return;
    }
    if (document.hidden) {
      return;
    }
    this.pollTimer = window.setInterval(() => {
      void this.fetchQuotes();
    }, FALLBACK_POLL_MS);
  }

  private stopPolling(): void {
    if (this.pollTimer !== null) {
      window.clearInterval(this.pollTimer);
      this.pollTimer = null;
    }
  }

  private teardown(): void {
    this.closeStream();
    this.stopPolling();
    this.restController?.abort();
    this.restController = null;
    if (this.refreshTimer !== null) {
      window.clearTimeout(this.refreshTimer);
      this.refreshTimer = null;
    }
  }
}

export const quoteHub = new QuoteHub();
export type { QuoteHub };
