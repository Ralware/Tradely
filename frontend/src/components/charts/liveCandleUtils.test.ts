import { describe, expect, it } from 'vitest';
import {
  isPlausibleLivePrice,
  parseTimestampToEpochSeconds,
  validateCandle,
} from './liveCandleUtils';

const expectedEpoch = Math.floor(Date.UTC(2026, 10, 27, 18, 0, 0) / 1000);
const base = {
  timestamp: '2026-11-27T18:00:00Z',
  open: 59_800,
  high: 60_100,
  low: 59_700,
  close: 59_950,
  volume: 25,
};

describe('timestamp normalization', () => {
  it('parses all three backend timestamp formats to the same epoch seconds', () => {
    expect(parseTimestampToEpochSeconds('2026-11-27T18:00:00Z')).toBe(expectedEpoch);
    expect(parseTimestampToEpochSeconds('2026-11-27T18:00:00+00:00')).toBe(expectedEpoch);
    expect(parseTimestampToEpochSeconds('2026-11-27 18:00:00+00:00')).toBe(expectedEpoch);
  });

  it('accepts fractional seconds and non-UTC offsets', () => {
    expect(parseTimestampToEpochSeconds('2026-11-27T18:00:00.123Z')).toBe(expectedEpoch);
    expect(parseTimestampToEpochSeconds('2026-11-27T23:30:00+05:30')).toBe(expectedEpoch);
  });

  it('distinguishes seconds from milliseconds', () => {
    expect(parseTimestampToEpochSeconds(expectedEpoch)).toBe(expectedEpoch);
    expect(parseTimestampToEpochSeconds(expectedEpoch * 1000)).toBe(expectedEpoch);
    expect(parseTimestampToEpochSeconds(String(expectedEpoch))).toBe(expectedEpoch);
    expect(parseTimestampToEpochSeconds(String(expectedEpoch * 1000))).toBe(expectedEpoch);
  });

  it('rejects unparseable timestamps', () => {
    expect(parseTimestampToEpochSeconds('not-a-timestamp')).toBeNull();
    expect(parseTimestampToEpochSeconds('2026-02-30 18:00:00+00:00')).toBeNull();
    expect(parseTimestampToEpochSeconds(null)).toBeNull();
  });
});

describe('candle validation', () => {
  it('accepts null volume as unknown, not zero', () => {
    const result = validateCandle({ ...base, volume: null });
    expect(result.malformed).toBe(false);
    expect(result.candle?.volume).toBeNull();
  });

  it('accepts missing volume as unknown', () => {
    const { volume: _volume, ...withoutVolume } = base;
    const result = validateCandle(withoutVolume);
    expect(result.malformed).toBe(false);
    expect(result.candle?.volume).toBeNull();
  });

  it('coerces numeric strings', () => {
    const result = validateCandle({
      ...base,
      open: '59800',
      high: '60100',
      low: '59700',
      close: '59950',
      volume: '25',
    });
    expect(result.candle).toMatchObject({
      open: 59_800, high: 60_100, low: 59_700, close: 59_950, volume: 25,
    });
  });

  it('rejects an unparseable timestamp', () => {
    const result = validateCandle({ ...base, timestamp: 'bad' });
    expect(result.candle).toBeNull();
    expect(result.reasons).toContain('INVALID_TIMESTAMP');
  });

  it('rejects non-positive prices', () => {
    const result = validateCandle({ ...base, open: 0 });
    expect(result.candle).toBeNull();
    expect(result.reasons).toContain('NON_POSITIVE_PRICE');
  });

  it('rejects inconsistent OHLC', () => {
    const result = validateCandle({ ...base, high: 59_000 });
    expect(result.candle).toBeNull();
    expect(result.reasons).toContain('OHLC_INCONSISTENT');
  });

  it('rejects negative volume', () => {
    const result = validateCandle({ ...base, volume: -1 });
    expect(result.candle).toBeNull();
    expect(result.reasons).toContain('NEGATIVE_VOLUME');
  });

  it('accepts and flags reference-price deviation without rejecting the candle', () => {
    const result = validateCandle(
      { ...base, open: 1, high: 1.1, low: 0.9, close: 1 },
      { referencePrice: 60_000 },
    );
    expect(result.malformed).toBe(false);
    expect(result.suspicious).toBe(true);
    expect(result.reasons).toContain('DEVIATION_FROM_REFERENCE');
    expect(result.candle?.close).toBe(1);
  });

  it('flags a stale timestamp but keeps the candle structurally valid', () => {
    const result = validateCandle(base, { referenceTime: expectedEpoch + 60 });
    expect(result.malformed).toBe(false);
    expect(result.reasons).toContain('STALE_TIMESTAMP');
  });

  it('keeps the live-price plausibility guard', () => {
    expect(isPlausibleLivePrice(0.08, 60_000)).toBe(false);
    expect(isPlausibleLivePrice(60_001, 60_000)).toBe(true);
    expect(isPlausibleLivePrice(0, null)).toBe(false);
  });
});
