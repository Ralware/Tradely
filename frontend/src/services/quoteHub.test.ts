import { describe, expect, it } from 'vitest';
import type { Quote } from '../types/api';
import { resolveQuoteUpdate } from './quoteHub';

function quote(overrides: Partial<Quote> = {}): Quote {
  return {
    instrument_id: 'crypto:BINANCE:BTCUSDT',
    symbol: 'BTCUSDT',
    market: 'crypto',
    exchange: 'BINANCE',
    currency: 'USDT',
    provider: 'Binance Spot Public Market Data',
    price: 100,
    previous_close: 95,
    day_change: 5,
    day_change_pct: 5.26,
    day_high: 102,
    day_low: 94,
    volume: 1000,
    quote_time: '2026-01-01T00:00:00+00:00',
    retrieved_at: '2026-01-01T00:00:01+00:00',
    quote_type: 'real_time',
    freshness: 'live',
    is_stale: false,
    age_seconds: 1,
    market_status: '24/7',
    error: null,
    ...overrides,
  };
}

describe('resolveQuoteUpdate', () => {
  it('accepts the first quote for an instrument', () => {
    const candidate = quote();
    expect(resolveQuoteUpdate(undefined, candidate)).toBe(candidate);
  });

  it('accepts a newer live tick', () => {
    const current = quote();
    const candidate = quote({
      price: 101,
      quote_time: '2026-01-01T00:00:10+00:00',
      retrieved_at: '2026-01-01T00:00:11+00:00',
    });
    expect(resolveQuoteUpdate(current, candidate)?.price).toBe(101);
  });

  it('never lets an older tick overwrite a newer price', () => {
    const current = quote({
      price: 101,
      quote_time: '2026-01-01T00:00:10+00:00',
      retrieved_at: '2026-01-01T00:00:11+00:00',
    });
    const candidate = quote({
      price: 99,
      quote_time: '2026-01-01T00:00:05+00:00',
      retrieved_at: '2026-01-01T00:00:06+00:00',
    });
    expect(resolveQuoteUpdate(current, candidate)).toBeNull();
  });

  it('does not erase a valid price with an unavailable response', () => {
    const current = quote();
    const candidate = quote({
      price: null,
      quote_type: 'unavailable',
      freshness: 'unavailable',
      quote_time: null,
      retrieved_at: '2026-01-01T00:00:20+00:00',
      error: null,
    });
    expect(resolveQuoteUpdate(current, candidate)).toBeNull();
  });

  it('updates metadata when the price and quote timestamp are unchanged', () => {
    const current = quote();
    const candidate = quote({
      retrieved_at: '2026-01-01T00:00:20+00:00',
      freshness: 'delayed',
    });
    const merged = resolveQuoteUpdate(current, candidate);
    expect(merged?.price).toBe(100);
    expect(merged?.freshness).toBe('delayed');
  });

  it('ignores identical replays instead of triggering re-renders', () => {
    const current = quote();
    expect(resolveQuoteUpdate(current, quote())).toBeNull();
  });

  it('rejects a quote without instrument identity', () => {
    expect(resolveQuoteUpdate(undefined, quote({ instrument_id: '' }))).toBeNull();
  });
});
