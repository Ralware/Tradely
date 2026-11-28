import type { Candle } from '../../types/api';

/**
 * Every candle timestamp in the product is a UTC bar-open time. The backend
 * currently emits three different string shapes:
 *
 *  - `/api/market/candles` candles: `YYYY-MM-DDTHH:MM:SSZ`
 *  - `forming_candle.timestamp`:     ISO-8601 with `+00:00`
 *  - snapshot `analysis.candles`:    `YYYY-MM-DD HH:MM:SS+00:00`
 *
 * `Date.parse` is not reliable for the space-separated form, so all three are
 * parsed by one explicit function and reduced to epoch seconds.
 */
const TIMESTAMP_PATTERN =
  /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d{1,9}))?(Z|[+-]\d{2}:?\d{2})?$/i;

function parseEpochNumber(value: number): number | null {
  if (!Number.isFinite(value)) return null;
  // Values around 1e12 are milliseconds; values around 1e9 are seconds.
  const seconds = Math.abs(value) >= 1e12 ? value / 1000 : value;
  if (!Number.isFinite(seconds) || Math.abs(seconds) < 1e8) return null;
  return Math.floor(seconds);
}

/** Parse any supported candle timestamp into integer epoch seconds. */
export function parseTimestampToEpochSeconds(value: unknown): number | null {
  if (typeof value === 'number') {
    return parseEpochNumber(value);
  }
  if (typeof value !== 'string') {
    return null;
  }
  const text = value.trim();
  if (!text) return null;

  if (/^\d+(?:\.\d+)?$/.test(text)) {
    return parseEpochNumber(Number(text));
  }

  const match = TIMESTAMP_PATTERN.exec(text);
  if (!match) return null;
  const [, yearText, monthText, dayText, hourText, minuteText, secondText, fractionText, zone] = match;
  const year = Number(yearText);
  const month = Number(monthText);
  const day = Number(dayText);
  const hour = Number(hourText);
  const minute = Number(minuteText);
  const second = Number(secondText ?? '0');
  if (
    month < 1 || month > 12
    || day < 1 || day > 31
    || hour > 23
    || minute > 59
    || second > 59
  ) {
    return null;
  }
  const milliseconds = fractionText ? Number(fractionText.padEnd(3, '0').slice(0, 3)) : 0;
  const utcMillis = Date.UTC(year, month - 1, day, hour, minute, second, milliseconds);
  const check = new Date(utcMillis);
  if (
    check.getUTCFullYear() !== year
    || check.getUTCMonth() !== month - 1
    || check.getUTCDate() !== day
    || check.getUTCHours() !== hour
    || check.getUTCMinutes() !== minute
    || check.getUTCSeconds() !== second
  ) {
    return null;
  }

  let offsetSeconds = 0;
  if (zone && zone.toUpperCase() !== 'Z') {
    const sign = zone.startsWith('-') ? -1 : 1;
    const digits = zone.slice(1).replace(':', '');
    const offsetHours = Number(digits.slice(0, 2));
    const offsetMinutes = Number(digits.slice(2, 4));
    if (offsetHours > 23 || offsetMinutes > 59) return null;
    offsetSeconds = sign * (offsetHours * 60 + offsetMinutes) * 60;
  }
  return Math.floor(utcMillis / 1000) - offsetSeconds;
}

export type ValidationReason =
  | 'INVALID_TIMESTAMP'
  | 'NON_POSITIVE_PRICE'
  | 'OHLC_INCONSISTENT'
  | 'NEGATIVE_VOLUME'
  | 'DEVIATION_FROM_REFERENCE'
  | 'STALE_TIMESTAMP'
  | 'INACTIVE_INTERVAL'
  | 'ALREADY_FINALIZED'
  | 'MISALIGNED_TIMESTAMP'
  | 'MISSING_FIELD';

export interface NormalizedCandle {
  timestamp: string;
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  /** `null` means the provider did not report volume; it is unknown, not zero. */
  volume: number | null;
}

export interface CandleValidationResult {
  candle: NormalizedCandle | null;
  time: number | null;
  /** Structural problems: the candle must not be used at all. */
  malformed: boolean;
  /** Accepted, but worth surfacing in diagnostics. */
  suspicious: boolean;
  reasons: ValidationReason[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

/** Coerce numbers and numeric strings; reject everything else. */
export function toFiniteNumber(value: unknown): number | null {
  if (typeof value === 'number') {
    return Number.isFinite(value) ? value : null;
  }
  if (typeof value === 'string' && value.trim() !== '') {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function toOptionalVolume(value: unknown): { value: number | null; malformed: boolean } {
  if (value === null || value === undefined || value === '') {
    return { value: null, malformed: false };
  }
  const parsed = toFiniteNumber(value);
  if (parsed === null) {
    // A non-numeric volume is unknown rather than a fabricated zero.
    return { value: null, malformed: false };
  }
  return { value: parsed, malformed: parsed < 0 };
}

/**
 * Normalize and validate a provider candle.
 *
 * Malformed candles are rejected. Reference-price deviation is deliberately
 * only flagged: adjusted and unadjusted sources can legitimately disagree.
 */
export function validateCandle(
  raw: unknown,
  options: { referencePrice?: number | null; referenceTime?: number | null } = {},
): CandleValidationResult {
  if (!isRecord(raw)) {
    return {
      candle: null,
      time: null,
      malformed: true,
      suspicious: false,
      reasons: ['MISSING_FIELD'],
    };
  }

  const reasons: ValidationReason[] = [];
  const time = parseTimestampToEpochSeconds(raw.timestamp);
  if (time === null) {
    reasons.push('INVALID_TIMESTAMP');
  }

  const open = toFiniteNumber(raw.open);
  const high = toFiniteNumber(raw.high);
  const low = toFiniteNumber(raw.low);
  const close = toFiniteNumber(raw.close);
  if (
    open === null || high === null || low === null || close === null
    || open <= 0 || high <= 0 || low <= 0 || close <= 0
  ) {
    reasons.push('NON_POSITIVE_PRICE');
  }

  let volume: number | null = null;
  const volumeResult = toOptionalVolume(raw.volume);
  volume = volumeResult.value;
  if (volumeResult.malformed) {
    reasons.push('NEGATIVE_VOLUME');
  }

  if (
    open !== null && high !== null && low !== null && close !== null
    && (high < low
      || high < Math.max(open, low, close)
      || low > Math.min(open, high, close))
  ) {
    reasons.push('OHLC_INCONSISTENT');
  }

  const reference = toFiniteNumber(options.referencePrice);
  if (
    reference !== null && reference > 0
    && open !== null && high !== null && low !== null && close !== null
    && [open, high, low, close].some(
      (value) => value < reference / 10 || value > reference * 10,
    )
  ) {
    reasons.push('DEVIATION_FROM_REFERENCE');
  }

  if (time !== null && options.referenceTime !== null && options.referenceTime !== undefined
    && Number.isFinite(options.referenceTime) && time < options.referenceTime) {
    reasons.push('STALE_TIMESTAMP');
  }

  const malformed = reasons.some(
    (reason) => reason !== 'DEVIATION_FROM_REFERENCE' && reason !== 'STALE_TIMESTAMP',
  );
  if (malformed || time === null || open === null || high === null || low === null || close === null) {
    return {
      candle: null,
      time,
      malformed: true,
      suspicious: reasons.includes('DEVIATION_FROM_REFERENCE'),
      reasons,
    };
  }

  return {
    candle: {
      timestamp: typeof raw.timestamp === 'string'
        ? raw.timestamp
        : new Date(time * 1000).toISOString(),
      time,
      open,
      high,
      low,
      close,
      volume,
    },
    time,
    malformed: false,
    suspicious: reasons.includes('DEVIATION_FROM_REFERENCE'),
    reasons,
  };
}

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
  return validateCandle(candle, { referencePrice: reference }).candle !== null;
}
