import { describe, expect, it } from 'vitest';
import { timeframesFor, timeframesForIntervals } from './timeframes';

describe('timeframe ordering', () => {
  it('displays supported intervals from shortest to longest', () => {
    const ascending = ['1m', '5m', '15m', '30m', '1h', '2h', '4h', '1d', '1wk', '1mo'];
    const providerIntervals = [...ascending].reverse();

    expect(timeframesFor('crypto').map((timeframe) => timeframe.id)).toEqual(ascending);
    expect(timeframesForIntervals(providerIntervals).map((timeframe) => timeframe.id)).toEqual(ascending);
  });
});
