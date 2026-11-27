import type { Candle } from '../../types/api';

/** Reject impossible prices and obvious feed spikes against the last confirmed close. */
export function isPlausibleLivePrice(value: number, reference: number | null | undefined): boolean {
  if (!Number.isFinite(value) || value <= 0) return false;
  if (typeof reference !== 'number' || !Number.isFinite(reference) || reference <= 0) return true;
  // Allows a 90% fall / 10x rise while screening obvious ticker/feed mix-ups.
  return value >= reference / 10 && value <= reference * 10;
}

export function isPlausibleLiveCandle(
  candle: Candle,
  reference: number | null | undefined,
): boolean {
  const { open, high, low, close } = candle;
  return [open, high, low, close].every((value) => Number.isFinite(value) && value > 0)
    && Number.isFinite(candle.volume)
    && candle.volume >= 0
    && high >= Math.max(open, low, close)
    && low <= Math.min(open, high, close)
    && [open, high, low, close].every((value) => isPlausibleLivePrice(value, reference));
}

/** Replace/upsert one provider candle by its exchange opening timestamp. */
export function replaceFormingCandle(candles: Candle[], authoritative: Candle): Candle[] {
  const existing = candles.find((candle) => candle.timestamp === authoritative.timestamp);
  if (existing
    && existing.open === authoritative.open
    && existing.high === authoritative.high
    && existing.low === authoritative.low
    && existing.close === authoritative.close
    && existing.volume === authoritative.volume) {
    return candles;
  }
  const byTimestamp = new Map<string, Candle>();
  for (const candle of candles) byTimestamp.set(candle.timestamp, candle);
  byTimestamp.set(authoritative.timestamp, authoritative);
  return [...byTimestamp.values()]
    .sort((left, right) => Date.parse(left.timestamp) - Date.parse(right.timestamp))
    .slice(-1_000);
}
