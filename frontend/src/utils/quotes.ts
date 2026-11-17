import type { BadgeTone } from '../components/common/Badge';
import type { Quote, WatchlistItem } from '../types/api';
import type { QuoteRef } from '../services/quoteHub';
import { titleCase } from './format';

const typeLabels: Record<string, string> = {
  real_time: 'Real-Time',
  delayed: 'Delayed',
  last_available: 'Last Available',
  previous_close: 'Previous Close',
  end_of_day: 'End-Of-Day',
  historical: 'Historical',
  cached: 'Cached',
  stale: 'Stale',
  unavailable: 'Unavailable',
};

export function quoteLabel(quote: Quote | null | undefined): string {
  if (!quote || quote.price === null || quote.quote_type === 'unavailable') {
    return 'Unavailable';
  }
  if (quote.freshness === 'stale') {
    return 'Stale';
  }
  if (quote.quote_type === 'cached' || quote.freshness === 'cached') {
    return 'Cached';
  }
  return typeLabels[quote.quote_type] ?? 'Last Available';
}

export function quoteTone(quote: Quote | null | undefined): BadgeTone {
  if (!quote || quote.price === null || quote.quote_type === 'unavailable') {
    return 'neutral';
  }
  if (quote.freshness === 'stale' || quote.quote_type === 'cached') {
    return 'warning';
  }
  if (quote.quote_type === 'historical' || quote.freshness === 'historical') {
    return 'violet';
  }
  if (quote.quote_type === 'real_time' && quote.freshness === 'live') {
    return 'positive';
  }
  return 'neutral';
}

/**
 * Label for the immutable quote snapshot stored on a ledger row. Ledger rows
 * carry the provider quote type as a plain string, not a full quote object.
 */
export function quoteTypeLabel(quoteType: string | null | undefined): string {
  if (!quoteType) {
    return 'Not Recorded';
  }
  return typeLabels[quoteType] ?? titleCase(quoteType);
}

export function quoteTypeTone(
  quoteType: string | null | undefined,
  quoteStatus?: string | null,
): BadgeTone {
  const type = (quoteType ?? '').toLowerCase();
  const status = (quoteStatus ?? '').toLowerCase();
  if (type === 'historical' || status === 'historical') {
    return 'violet';
  }
  if (type === 'real_time' || status === 'live') {
    return 'positive';
  }
  if (type === 'stale' || type === 'cached' || status === 'stale' || status === 'cached') {
    return 'warning';
  }
  return 'neutral';
}

export function marketStatusLabel(status: string | undefined): string {
  if (!status) {
    return 'Unknown Session';
  }
  if (status === '24/7') {
    return '24/7 Market';
  }
  return status === 'open' ? 'Market Open' : 'Market Closed';
}

export function formatAge(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) {
    return '—';
  }
  if (seconds < 5) {
    return 'Just Now';
  }
  if (seconds < 60) {
    return `${Math.round(seconds)}s Ago`;
  }
  if (seconds < 3600) {
    return `${Math.round(seconds / 60)}m Ago`;
  }
  if (seconds < 86_400) {
    return `${Math.round(seconds / 3600)}h Ago`;
  }
  return `${Math.round(seconds / 86_400)}d Ago`;
}

export function quoteRefFromWatchlist(item: WatchlistItem): QuoteRef {
  return {
    instrument_id: item.instrument_id ?? `${item.market}:${item.exchange}:${item.symbol}`,
    symbol: item.symbol,
    market: item.market,
    exchange: item.exchange,
    currency: item.currency,
  };
}

