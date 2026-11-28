import { describe, expect, it } from 'vitest';
import { pollDaysFor, timeframesFor, timeframesForIntervals } from './timeframes';

describe('timeframe ordering', () => {
  it('displays supported intervals from shortest to longest', () => {
    const ascending = ['1m', '5m', '15m', '30m', '1h', '2h', '4h', '1d', '1wk', '1mo'];
    const providerIntervals = [...ascending].reverse();

    expect(timeframesFor('crypto').map((timeframe) => timeframe.id)).toEqual(ascending);
    expect(timeframesForIntervals(providerIntervals).map((timeframe) => timeframe.id)).toEqual(ascending);
  });
});

describe('poll window', () => {
  it('uses the backend tail lookback for long intervals', () => {
    expect(pollDaysFor('1d')).toBe(10);
    expect(pollDaysFor('1wk')).toBe(42);
    expect(pollDaysFor('1mo')).toBe(90);
  });

  it('keeps a five-day floor so a weekend cannot produce an empty range', () => {
    expect(pollDaysFor('1m')).toBe(5);
    expect(pollDaysFor('15m')).toBe(5);
    expect(pollDaysFor('1h')).toBe(5);
    expect(pollDaysFor('unknown')).toBe(10);
  });
});
