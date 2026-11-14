import { describe, expect, it } from 'vitest';
import type { Quote } from '../types/api';
import { formatAge, marketStatusLabel, quoteLabel, quoteTone, quoteTypeLabel, quoteTypeTone } from './quotes';

function quote(overrides: Partial<Quote> = {}): Quote {
  return {
    instrument_id: 'india:NSE:RELIANCE',
    symbol: 'RELIANCE',
    market: 'india',
    exchange: 'NSE',
    currency: 'INR',
    provider: 'TejHQ',
    price: 2500,
    previous_close: 2450,
    day_change: 50,
    day_change_pct: 2.04,
    day_high: 2520,
    day_low: 2440,
    volume: 1000,
    quote_time: '2026-01-01T10:00:00+00:00',
    retrieved_at: '2026-01-01T10:01:00+00:00',
    quote_type: 'end_of_day',
    freshness: 'eod',
    is_stale: false,
    age_seconds: 60,
    market_status: 'closed',
    error: null,
    ...overrides,
  };
}

describe('quote labels', () => {
  it('distinguishes provider freshness categories', () => {
    expect(quoteLabel(quote({ quote_type: 'real_time', freshness: 'live' }))).toBe('Real-Time');
    expect(quoteLabel(quote({ quote_type: 'delayed', freshness: 'delayed' }))).toBe('Delayed');
    expect(quoteLabel(quote({ quote_type: 'last_available', freshness: 'delayed' }))).toBe('Last Available');
    expect(quoteLabel(quote({ quote_type: 'previous_close', freshness: 'delayed' }))).toBe('Previous Close');
    expect(quoteLabel(quote({ quote_type: 'end_of_day', freshness: 'eod' }))).toBe('End-Of-Day');
    expect(quoteLabel(quote({ quote_type: 'historical', freshness: 'historical' }))).toBe(
      'Historical',
    );
    expect(quoteLabel(quote({ quote_type: 'cached', freshness: 'cached' }))).toBe('Cached');
    expect(quoteLabel(quote({ quote_type: 'stale', freshness: 'stale' }))).toBe('Stale');
    expect(quoteLabel(quote({ price: null, quote_type: 'unavailable', freshness: 'unavailable' }))).toBe(
      'Unavailable',
    );
  });

  it('maps live and stale states to visual tones', () => {
    expect(quoteTone(quote({ quote_type: 'real_time', freshness: 'live' }))).toBe('positive');
    expect(quoteTone(quote({ quote_type: 'cached', freshness: 'cached' }))).toBe('warning');
    expect(quoteTone(quote({ quote_type: 'stale', freshness: 'stale' }))).toBe('warning');
    expect(quoteTone(quote({ quote_type: 'historical', freshness: 'historical' }))).toBe('violet');
    expect(quoteTone(quote({ price: null }))).toBe('neutral');
  });

  it('labels stored ledger quote snapshots', () => {
    expect(quoteTypeLabel('historical')).toBe('Historical');
    expect(quoteTypeLabel('end_of_day')).toBe('End-Of-Day');
    expect(quoteTypeLabel('')).toBe('Not Recorded');
    expect(quoteTypeTone('historical', 'historical')).toBe('violet');
    expect(quoteTypeTone('real_time', 'live')).toBe('positive');
    expect(quoteTypeTone('end_of_day', 'eod')).toBe('neutral');
    expect(quoteTypeTone('stale', 'stale')).toBe('warning');
  });

  it('formats quote age and market status', () => {
    expect(formatAge(3)).toBe('Just Now');
    expect(formatAge(90)).toBe('2m Ago');
    expect(formatAge(7200)).toBe('2h Ago');
    expect(marketStatusLabel('24/7')).toBe('24/7 Market');
    expect(marketStatusLabel('open')).toBe('Market Open');
    expect(marketStatusLabel('closed')).toBe('Market Closed');
  });
});
