import { describe, expect, it } from 'vitest';
import { freshnessWindowMs, isTimestampFresh } from './freshness';

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;

describe('client freshness windows', () => {
  it('scales intraday windows with the interval', () => {
    const now = new Date('2026-11-24T12:00:00Z');
    expect(freshnessWindowMs('crypto', '1m', now)).toBe(2 * MINUTE);
    expect(freshnessWindowMs('crypto', '15m', now)).toBe(30 * MINUTE);
  });

  it('accepts a 24-hour-old crypto daily bar but not a 30-hour-old one', () => {
    const now = new Date('2026-11-24T12:00:00Z');
    expect(isTimestampFresh('2026-11-23T12:00:00Z', 'crypto', '1d', now)).toBe(true);
    expect(isTimestampFresh('2026-11-23T06:00:00Z', 'crypto', '1d', now)).toBe(false);
  });

  it('gives equity intraday data a closure grace window', () => {
    // Monday 12:00 UTC = 17:30 IST; the Indian session has closed.
    const closed = new Date('2026-11-23T12:00:00Z');
    expect(freshnessWindowMs('india', '1m', closed)).toBe(4 * 24 * HOUR);
    // Monday 06:00 UTC = 11:30 IST; the session is open.
    const open = new Date('2026-11-23T06:00:00Z');
    expect(freshnessWindowMs('india', '1m', open)).toBe(10 * MINUTE);
  });

  it('treats weekly and monthly periods as their own windows', () => {
    const now = new Date('2026-11-24T12:00:00Z');
    expect(freshnessWindowMs('crypto', '1wk', now)).toBe(14 * 24 * HOUR);
    expect(freshnessWindowMs('crypto', '1mo', now)).toBe(62 * 24 * HOUR);
  });

  it('rejects missing or unparsable timestamps', () => {
    const now = new Date('2026-11-24T12:00:00Z');
    expect(isTimestampFresh(null, 'crypto', '1m', now)).toBe(false);
    expect(isTimestampFresh('not-a-date', 'crypto', '1m', now)).toBe(false);
  });
});
