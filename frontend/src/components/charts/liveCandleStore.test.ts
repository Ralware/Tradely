import { beforeEach, describe, expect, it } from 'vitest';
import type { Candle } from '../../types/api';
import type { LiveCandleEntry } from './candleReconcile';
import {
  clearCachedLiveCandles,
  getCachedLiveCandles,
  pruneCachedLiveCandles,
  setCachedLiveCandles,
  upsertCachedLiveCandle,
} from './liveCandleStore';

const BASE = Math.floor(Date.UTC(2026, 10, 27, 18, 0, 0) / 1000);

function candle(time: number, close = 100): Candle {
  return {
    timestamp: new Date(time * 1000).toISOString(),
    open: close - 1,
    high: close + 1,
    low: close - 2,
    close,
    volume: 10,
  };
}

function entry(
  time: number,
  status: 'forming' | 'final' = 'forming',
  sequence = 1,
): LiveCandleEntry {
  return {
    time,
    candle: candle(time),
    status,
    interval: '1m',
    sequence,
    updatedAt: sequence,
  };
}

beforeEach(() => clearCachedLiveCandles());

describe('live candle session cache', () => {
  it('restores entries in chronological order', () => {
    const key = 'crypto:BINANCE:BTCUSDT\u00002h';
    setCachedLiveCandles(key, [entry(BASE + 60), entry(BASE)]);

    expect(getCachedLiveCandles(key)?.map((item) => item.time)).toEqual([BASE, BASE + 60]);
  });

  it('keeps different instruments and timeframes isolated', () => {
    setCachedLiveCandles('crypto:BINANCE:BTCUSDT\u00002h', [entry(BASE)]);

    expect(getCachedLiveCandles('crypto:BINANCE:BTCUSDT\u00001h')).toBeUndefined();
    expect(getCachedLiveCandles('crypto:BINANCE:ETHUSDT\u00002h')).toBeUndefined();
  });

  it('upgrades forming to final and never resurrects a final bar as forming', () => {
    const key = 'crypto:BINANCE:BTCUSDT\u00001m';
    upsertCachedLiveCandle(key, entry(BASE, 'forming', 1));
    upsertCachedLiveCandle(key, entry(BASE, 'final', 2));

    expect(getCachedLiveCandles(key)?.[0].status).toBe('final');

    upsertCachedLiveCandle(key, entry(BASE, 'forming', 3));
    expect(getCachedLiveCandles(key)?.[0].status).toBe('final');
  });

  it('lets a final bar win even when its sequence is lower after a remount', () => {
    const key = 'crypto:BINANCE:BTCUSDT\u00001m';
    upsertCachedLiveCandle(key, entry(BASE, 'forming', 500));
    upsertCachedLiveCandle(key, entry(BASE, 'final', 1));

    expect(getCachedLiveCandles(key)?.[0].status).toBe('final');
  });

  it('expires a forming entry when it is finalized', () => {
    const key = 'crypto:BINANCE:BTCUSDT\u00001m';
    setCachedLiveCandles(key, [entry(BASE, 'forming')]);

    pruneCachedLiveCandles(key, {
      interval: '1m',
      market: 'crypto',
      now: BASE + 30,
      finalizedTimes: [BASE],
    });

    expect(getCachedLiveCandles(key)).toEqual([]);
  });

  it('expires a forming entry when its interval has ended but keeps final entries', () => {
    const key = 'crypto:BINANCE:BTCUSDT\u00001m';
    setCachedLiveCandles(key, [entry(BASE, 'forming'), entry(BASE + 60, 'final')]);

    pruneCachedLiveCandles(key, {
      interval: '1m',
      market: 'crypto',
      now: BASE + 120,
    });

    expect(getCachedLiveCandles(key)?.map((item) => item.status)).toEqual(['final']);
  });

  it('evicts the least-recently-used chart', () => {
    for (let index = 0; index < 50; index += 1) {
      setCachedLiveCandles(`key${index}`, [entry(BASE + index)]);
    }
    // Touch key0 so key1 becomes the oldest.
    expect(getCachedLiveCandles('key0')).toBeDefined();
    setCachedLiveCandles('key50', [entry(BASE + 50)]);

    expect(getCachedLiveCandles('key0')).toBeDefined();
    expect(getCachedLiveCandles('key1')).toBeUndefined();
    expect(getCachedLiveCandles('key50')).toBeDefined();
  });
});
