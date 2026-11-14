import { describe, expect, it } from 'vitest';
import type { Instrument } from '../types/api';
import {
  assetUnit,
  instrumentQuoteRef,
  isHistoricalEntry,
  newIdempotencyKey,
} from './transaction';

function instrument(overrides: Partial<Instrument> = {}): Instrument {
  return {
    instrument_id: 'crypto:BINANCE:BTCUSDT',
    symbol: 'BTCUSDT',
    name: 'BTCUSDT',
    market: 'crypto',
    exchange: 'BINANCE',
    currency: 'USDT',
    asset_type: 'crypto',
    provider: 'Binance Spot Public Market Data',
    provider_symbol: 'BTCUSDT',
    ...overrides,
  };
}

describe('transaction amount entry helpers', () => {
  it('derives the display asset unit from the quote currency', () => {
    expect(assetUnit('BTCUSDT', 'crypto', 'USDT')).toBe('BTC');
    expect(assetUnit('ETHUSDT', 'crypto', 'USDT')).toBe('ETH');
    expect(assetUnit('BTCFDUSD', 'crypto', 'FDUSD')).toBe('BTC');
    expect(assetUnit('RELIANCE', 'india', 'INR')).toBe('RELIANCE');
    expect(assetUnit('AAPL', 'global', 'USD')).toBe('AAPL');
    expect(assetUnit('', 'crypto', 'USDT')).toBe('');
  });

  it('identifies backdated entries beyond the live-quote window', () => {
    const now = Date.parse('2026-02-01T12:00:00Z');
    expect(isHistoricalEntry('2026-02-01T11:59:00Z', now)).toBe(false);
    expect(isHistoricalEntry('2026-02-01T11:45:00Z', now)).toBe(true);
    expect(isHistoricalEntry('not-a-date', now)).toBe(false);
  });

  it('builds quote refs from the resolved instrument identity', () => {
    expect(instrumentQuoteRef(instrument())).toEqual({
      instrument_id: 'crypto:BINANCE:BTCUSDT',
      symbol: 'BTCUSDT',
      market: 'crypto',
      exchange: 'BINANCE',
      currency: 'USDT',
    });
    expect(
      instrumentQuoteRef(instrument({ instrument_id: 'india:NSE:RELIANCE', symbol: 'RELIANCE' })),
    ).toMatchObject({ instrument_id: 'india:NSE:RELIANCE', symbol: 'RELIANCE' });
  });

  it('generates distinct idempotency keys', () => {
    const first = newIdempotencyKey();
    const second = newIdempotencyKey();
    expect(first.length).toBeGreaterThan(0);
    expect(second.length).toBeGreaterThan(0);
    expect(first).not.toBe(second);
  });
});
