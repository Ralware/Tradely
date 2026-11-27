import type { Candle } from '../../types/api';

const MAX_CACHED_LIVE_BARS = 1_000;
const MAX_CACHED_CHARTS = 50;
const cache = new Map<string, Candle[]>();

export function getCachedLiveCandles(key: string): Candle[] | undefined {
  const candles = cache.get(key);
  if (!candles) return undefined;
  // Refresh LRU order on access.
  cache.delete(key);
  cache.set(key, candles);
  return candles;
}

export function setCachedLiveCandles(key: string, candles: Candle[]): void {
  cache.delete(key);
  cache.set(key, candles.slice(-MAX_CACHED_LIVE_BARS));
  while (cache.size > MAX_CACHED_CHARTS) {
    const oldestKey = cache.keys().next().value;
    if (!oldestKey) break;
    cache.delete(oldestKey);
  }
}

export function clearCachedLiveCandles(): void {
  cache.clear();
}
