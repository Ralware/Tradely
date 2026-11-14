import type { Instrument, Market } from '../types/api';

const HISTORICAL_THRESHOLD_MS = 10 * 60 * 1000;

export function newIdempotencyKey(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

/** Display-only asset unit; accounting quantity always comes from the backend. */
export function assetUnit(
  symbol: string | null | undefined,
  market: Market | null | undefined,
  currency: string | null | undefined,
): string {
  const clean = (symbol ?? '').trim().toUpperCase();
  const quoteCurrency = (currency ?? '').trim().toUpperCase();
  if (!clean) {
    return '';
  }
  if (market === 'crypto' && quoteCurrency && clean.endsWith(quoteCurrency)) {
    return clean.slice(0, -quoteCurrency.length) || clean;
  }
  return clean;
}

export function isHistoricalEntry(tradeTime: string, now = Date.now()): boolean {
  const parsed = Date.parse(tradeTime);
  if (Number.isNaN(parsed)) {
    return false;
  }
  return now - parsed > HISTORICAL_THRESHOLD_MS;
}

export function instrumentQuoteRef(instrument: Instrument) {
  return {
    instrument_id: instrument.instrument_id,
    symbol: instrument.symbol,
    market: instrument.market,
    exchange: instrument.exchange,
    currency: instrument.currency,
  };
}
