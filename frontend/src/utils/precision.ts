import type { Instrument, PriceMetadata } from '../types/api';

type PrecisionSource = PriceMetadata | Instrument | null | undefined;

/**
 * Display precision published by the provider (TradingView `pricescale`).
 * Values are presentation-only; callers must never round stored prices.
 */
export function precisionFromMetadata(source: PrecisionSource): number | null {
  if (!source) return null;
  const direct = source.price_precision;
  if (typeof direct === 'number' && Number.isFinite(direct) && direct >= 0) {
    return Math.min(12, Math.trunc(direct));
  }
  const scale = source.price_scale;
  if (typeof scale === 'number' && Number.isFinite(scale) && scale >= 1) {
    return Math.min(12, Math.max(0, Math.round(Math.log10(scale))));
  }
  return null;
}

export function minMoveFromMetadata(source: PrecisionSource): number | null {
  if (!source) return null;
  const direct = source.min_move;
  if (typeof direct === 'number' && Number.isFinite(direct) && direct > 0) {
    return direct;
  }
  const precision = precisionFromMetadata(source);
  return precision === null ? null : 10 ** -precision;
}

/**
 * Metadata first. The value-based fallback only applies when the provider did
 * not publish a price scale, and is deliberately conservative.
 */
export function pricePrecisionFor(
  value: number | null | undefined,
  source: PrecisionSource,
): number {
  const metadata = precisionFromMetadata(source);
  if (metadata !== null) return metadata;
  if (value === null || value === undefined || !Number.isFinite(value)) return 2;
  const magnitude = Math.abs(value);
  if (magnitude >= 1000) return 2;
  if (magnitude >= 1) return 4;
  if (magnitude >= 0.01) return 6;
  if (magnitude >= 0.0001) return 8;
  return 10;
}
