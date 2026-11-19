import { describe, expect, it } from 'vitest';
import type { Quote, WatchlistItem } from '../types/api';
import {
  buildWatchlistRows,
  nextWatchlistSort,
  sortWatchlistRows,
  watchlistItemKey,
} from './watchlistSort';

function item(symbol: string, overrides: Partial<WatchlistItem> = {}): WatchlistItem {
  return {
    id: 1,
    symbol,
    market: 'india',
    exchange: 'NSE',
    display_name: symbol,
    created_at: '2026-01-01T00:00:00+00:00',
    instrument_id: `india:NSE:${symbol}`,
    ...overrides,
  };
}

function quote(symbol: string, overrides: Partial<Quote> = {}): Quote {
  return {
    instrument_id: `india:NSE:${symbol}`,
    symbol,
    market: 'india',
    exchange: 'NSE',
    currency: 'INR',
    provider: 'TradingView',
    price: 100,
    previous_close: 99,
    day_change: 1,
    day_change_pct: 1,
    day_high: 101,
    day_low: 98,
    volume: 1000,
    quote_time: '2026-01-01T10:00:00+00:00',
    retrieved_at: '2026-01-01T10:01:00+00:00',
    quote_type: 'real_time',
    freshness: 'live',
    is_stale: false,
    age_seconds: 30,
    market_status: 'open',
    error: null,
    ...overrides,
  };
}

function rowsFor(entries: Array<[string, Partial<Quote>]>) {
  const items = entries.map(([symbol]) => item(symbol));
  const quotes = new Map(entries.map(([symbol, overrides]) => [watchlistItemKey(item(symbol)), quote(symbol, overrides)]));
  return buildWatchlistRows(items, quotes);
}

function symbols(rows: ReturnType<typeof rowsFor>): string[] {
  return rows.map((row) => row.item.symbol);
}

describe('watchlist sorting', () => {
  it('sorts prices numerically in both directions, including decimals', () => {
    const rows = rowsFor([
      ['A', { price: 1367.45 }],
      ['B', { price: 99.5 }],
      ['C', { price: 25000.75 }],
      ['D', { price: 1.05 }],
    ]);

    expect(symbols(sortWatchlistRows(rows, 'price', 'asc'))).toEqual(['D', 'B', 'A', 'C']);
    expect(symbols(sortWatchlistRows(rows, 'price', 'desc'))).toEqual(['C', 'A', 'B', 'D']);
  });

  it('orders negative absolute changes from most negative to most positive', () => {
    const rows = rowsFor([
      ['A', { day_change: 1.2 }],
      ['B', { day_change: -2.3 }],
      ['C', { day_change: -10.5 }],
      ['D', { day_change: 0 }],
    ]);

    expect(symbols(sortWatchlistRows(rows, 'change', 'asc'))).toEqual(['C', 'B', 'D', 'A']);
    expect(symbols(sortWatchlistRows(rows, 'change', 'desc'))).toEqual(['A', 'D', 'B', 'C']);
  });

  it('orders percentage changes from largest decline to largest gain', () => {
    const rows = rowsFor([
      ['A', { day_change_pct: 0.42 }],
      ['B', { day_change_pct: -1.08 }],
      ['C', { day_change_pct: -7.25 }],
      ['D', { day_change_pct: 3.1 }],
    ]);

    expect(symbols(sortWatchlistRows(rows, 'changePct', 'asc'))).toEqual(['C', 'B', 'A', 'D']);
    expect(symbols(sortWatchlistRows(rows, 'changePct', 'desc'))).toEqual(['D', 'A', 'B', 'C']);
  });

  it('keeps unavailable values at the bottom in both directions', () => {
    const rows = rowsFor([
      ['A', { price: 250 }],
      ['B', { price: null }],
      ['C', { price: 10 }],
      ['D', { price: undefined }],
      ['E', { price: Number.NaN }],
    ]);

    expect(symbols(sortWatchlistRows(rows, 'price', 'asc'))).toEqual(['C', 'A', 'B', 'D', 'E']);
    expect(symbols(sortWatchlistRows(rows, 'price', 'desc'))).toEqual(['A', 'C', 'B', 'D', 'E']);
  });

  it('keeps instruments without a quote at the bottom', () => {
    const rows = buildWatchlistRows([item('A'), item('B')], new Map([
      ['india:NSE:A', quote('A', { price: 42, day_change: -1 })],
    ]));

    expect(symbols(sortWatchlistRows(rows, 'change', 'asc'))).toEqual(['A', 'B']);
    expect(symbols(sortWatchlistRows(rows, 'change', 'desc'))).toEqual(['A', 'B']);
  });

  it('does not mutate the saved order and keeps ties stable', () => {
    const rows = rowsFor([
      ['A', { price: 50 }],
      ['B', { price: 50 }],
      ['C', { price: 10 }],
    ]);
    const original = symbols(rows);

    const sorted = sortWatchlistRows(rows, 'price', 'desc');

    expect(symbols(rows)).toEqual(original);
    expect(symbols(sorted)).toEqual(['A', 'B', 'C']);
  });

  it('associates each quote with its own instrument', () => {
    const items = [
      item('A'),
      item('B', { instrument_id: 'global:NASDAQ:B', market: 'global', exchange: 'NASDAQ' }),
    ];
    const quotes = new Map([
      ['india:NSE:A', quote('A', { currency: 'INR', price: 10 })],
      ['global:NASDAQ:B', quote('B', { currency: 'USD', price: 500, market: 'global', exchange: 'NASDAQ' })],
    ]);

    const rows = buildWatchlistRows(items, quotes);

    expect(rows.map((row) => [row.item.symbol, row.quote?.currency, row.quote?.price])).toEqual([
      ['A', 'INR', 10],
      ['B', 'USD', 500],
    ]);
  });

  it('falls back to the symbol when a quote key has no instrument id', () => {
    const rows = buildWatchlistRows([item('A', { instrument_id: undefined })], new Map([
      ['A', quote('A', { price: 77 })],
    ]));

    expect(rows[0].quote?.price).toBe(77);
  });

  it('toggles the sort direction only for the active column', () => {
    expect(nextWatchlistSort(null, 'price')).toEqual({ column: 'price', direction: 'asc' });
    expect(nextWatchlistSort({ column: 'price', direction: 'asc' }, 'price')).toEqual({
      column: 'price',
      direction: 'desc',
    });
    expect(nextWatchlistSort({ column: 'price', direction: 'desc' }, 'change')).toEqual({
      column: 'change',
      direction: 'asc',
    });
  });
});
