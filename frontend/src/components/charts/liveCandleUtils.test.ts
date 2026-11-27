import { describe, expect, it } from 'vitest';
import { isPlausibleLiveCandle, isPlausibleLivePrice, replaceFormingCandle } from './liveCandleUtils';
import type { Candle } from '../../types/api';

const btcReference = 60_000;
const candle = (overrides: Partial<Candle> = {}): Candle => ({
  timestamp: '2026-11-27T18:00:00.000Z',
  open: 59_800,
  high: 60_100,
  low: 59_700,
  close: 59_950,
  volume: 25,
  ...overrides,
});

describe('live candle sanity checks', () => {
  it('rejects an isolated tiny quote against a high-priced instrument', () => {
    expect(isPlausibleLivePrice(0.08, btcReference)).toBe(false);
  });

  it('allows normal prices and large but plausible market moves', () => {
    expect(isPlausibleLivePrice(60_001, btcReference)).toBe(true);
    expect(isPlausibleLivePrice(6_000, btcReference)).toBe(true);
    expect(isPlausibleLivePrice(600_000, btcReference)).toBe(true);
  });

  it('rejects malformed OHLC relationships and outlier lows', () => {
    expect(isPlausibleLiveCandle(candle(), btcReference)).toBe(true);
    expect(isPlausibleLiveCandle(candle({ low: 0.08 }), btcReference)).toBe(false);
    expect(isPlausibleLiveCandle(candle({ high: 59_000 }), btcReference)).toBe(false);
  });

  it('accepts any positive finite quote before a completed reference candle exists', () => {
    expect(isPlausibleLivePrice(0.08, null)).toBe(true);
    expect(isPlausibleLivePrice(0, null)).toBe(false);
  });

  it('uses authoritative OHLCV values exactly instead of synthesizing from ticker state', () => {
    const cached = candle({ open: 60_050, high: 60_100, low: 59_700, close: 60_000, volume: 5 });
    const authoritative = candle({ open: 59_800, high: 60_200, low: 59_650, close: 60_050, volume: 42 });
    expect(replaceFormingCandle([cached], authoritative)).toEqual([authoritative]);
  });

  it('deduplicates by candle opening timestamp and keeps a new interval chronological', () => {
    const previous = candle();
    const current = candle({ timestamp: '2026-11-27T19:00:00.000Z', open: 60_000, high: 60_100, low: 59_900, close: 60_050, volume: 8 });
    expect(replaceFormingCandle([previous, current], { ...current, close: 60_075, volume: 9 }))
      .toEqual([previous, { ...current, close: 60_075, volume: 9 }]);
  });
});
