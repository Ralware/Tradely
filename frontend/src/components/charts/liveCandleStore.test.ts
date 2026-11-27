import { beforeEach, describe, expect, it } from 'vitest';
import type { Candle } from '../../types/api';
import { clearCachedLiveCandles, getCachedLiveCandles, setCachedLiveCandles } from './liveCandleStore';

const candle: Candle = {
  timestamp: '2026-11-27T18:00:00.000Z',
  open: 59_800,
  high: 60_100,
  low: 59_700,
  close: 59_950,
  volume: 25,
};

beforeEach(() => clearCachedLiveCandles());

describe('live candle session cache', () => {
  it('restores the full OHLC for the same instrument and timeframe', () => {
    const key = 'crypto:BINANCE:BTCUSDT\u00002h';
    setCachedLiveCandles(key, [candle]);

    expect(getCachedLiveCandles(key)).toEqual([candle]);
  });

  it('keeps different instruments and timeframes isolated', () => {
    setCachedLiveCandles('crypto:BINANCE:BTCUSDT\u00002h', [candle]);

    expect(getCachedLiveCandles('crypto:BINANCE:BTCUSDT\u00001h')).toBeUndefined();
    expect(getCachedLiveCandles('crypto:BINANCE:ETHUSDT\u00002h')).toBeUndefined();
  });
});
