import { describe, expect, it } from 'vitest';
import {
  minMoveFromMetadata,
  precisionFromMetadata,
  pricePrecisionFor,
} from './precision';

describe('provider price precision', () => {
  it('reads pricescale-derived precision from metadata', () => {
    expect(precisionFromMetadata({ price_precision: 4 })).toBe(4);
    expect(precisionFromMetadata({ price_scale: 10_000 })).toBe(4);
    expect(precisionFromMetadata({ price_scale: 100 })).toBe(2);
  });

  it('returns null when the provider published no scale', () => {
    expect(precisionFromMetadata(null)).toBeNull();
    expect(precisionFromMetadata({})).toBeNull();
    expect(precisionFromMetadata({ price_scale: 0 })).toBeNull();
  });

  it('preserves small-instrument precision instead of two decimals', () => {
    // ALGOUSDT trades near 0.7482 and must render all four decimals.
    expect(pricePrecisionFor(0.7482, { price_precision: 4 })).toBe(4);
    expect(pricePrecisionFor(0.7482, { price_scale: 10_000 })).toBe(4);
  });

  it('derives a conservative fallback only without metadata', () => {
    expect(pricePrecisionFor(0.7482, null)).toBe(6);
    expect(pricePrecisionFor(125.5, null)).toBe(4);
    expect(pricePrecisionFor(2500, null)).toBe(2);
    expect(pricePrecisionFor(null, null)).toBe(2);
  });

  it('derives the tick size from metadata first', () => {
    expect(minMoveFromMetadata({ min_move: 0.0005 })).toBe(0.0005);
    expect(minMoveFromMetadata({ price_precision: 4 })).toBe(0.0001);
    expect(minMoveFromMetadata(null)).toBeNull();
  });
});
