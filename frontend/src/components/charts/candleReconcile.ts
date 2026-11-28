import type { Candle, Market } from '../../types/api';
import {
  parseTimestampToEpochSeconds,
  validateCandle,
  type NormalizedCandle,
  type ValidationReason,
} from './liveCandleUtils';

export type CandleStatus = 'final' | 'forming';
export type CandleSource = 'snapshot' | 'polled' | 'cached' | 'forming';

export interface LiveCandleEntry {
  time: number;
  candle: Candle;
  status: CandleStatus;
  interval: string;
  /** Monotonic fetch sequence. Higher wins on a timestamp collision. */
  sequence: number;
  updatedAt: number;
}

export interface ReconciledCandle extends Candle {
  time: number;
  status: CandleStatus;
}

export interface ReconcileCandlesInput {
  snapshotCandles?: Candle[];
  polledCandles?: Candle[];
  formingCandle?: Candle | null;
  cachedLive?: LiveCandleEntry[];
  interval: string;
  market?: Market;
  /** Epoch seconds. Defaults to `Date.now()`. */
  now?: number;
  snapshotSequence?: number;
  pollSequence?: number;
  referencePrice?: number | null;
  maxCandles?: number;
}

export interface ReconcileRejection {
  time: number | null;
  reason: ValidationReason;
  source: CandleSource;
}

export interface ReconcileDiagnostics {
  snapshotCount: number;
  polledCount: number;
  cachedCount: number;
  latestFinalizedTime: number | null;
  formingTime: number | null;
  acceptedFinal: number;
  acceptedForming: number;
  rejected: ReconcileRejection[];
  replaced: number;
  discarded: number;
  retained: number;
  mismatches: string[];
}

export interface ReconcileResult {
  candles: ReconciledCandle[];
  diagnostics: ReconcileDiagnostics;
  latestFinalized: ReconciledCandle | null;
  forming: ReconciledCandle | null;
}

const INTERVAL_SECONDS: Record<string, number> = {
  '1m': 60,
  '3m': 180,
  '5m': 300,
  '15m': 900,
  '30m': 1_800,
  '45m': 2_700,
  '1h': 3_600,
  '2h': 7_200,
  '4h': 14_400,
  '6h': 21_600,
  '8h': 28_800,
  '12h': 43_200,
  '1d': 86_400,
  '3d': 259_200,
  '1wk': 604_800,
  '1w': 604_800,
};

export function intervalSecondsFor(interval: string): number | null {
  return INTERVAL_SECONDS[interval] ?? null;
}

interface ZonedParts {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
  weekday: number;
}

const formatterCache = new Map<string, Intl.DateTimeFormat>();
const WEEKDAYS: Record<string, number> = {
  Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6,
};

function zonedParts(epochSeconds: number, timeZone: string): ZonedParts {
  let formatter = formatterCache.get(timeZone);
  if (!formatter) {
    formatter = new Intl.DateTimeFormat('en-US', {
      timeZone,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      weekday: 'short',
      hourCycle: 'h23',
    });
    formatterCache.set(timeZone, formatter);
  }
  const values: Record<string, string> = {};
  for (const part of formatter.formatToParts(new Date(epochSeconds * 1000))) {
    if (part.type !== 'literal') values[part.type] = part.value;
  }
  return {
    year: Number(values.year),
    month: Number(values.month),
    day: Number(values.day),
    hour: Number(values.hour),
    minute: Number(values.minute),
    weekday: WEEKDAYS[values.weekday] ?? 0,
  };
}

function sessionFor(market: Market | undefined): {
  timeZone: string;
  closeHour: number;
  closeMinute: number;
  crypto: boolean;
} {
  if (market === 'crypto') {
    return { timeZone: 'UTC', closeHour: 0, closeMinute: 0, crypto: true };
  }
  if (market === 'india') {
    return { timeZone: 'Asia/Kolkata', closeHour: 15, closeMinute: 45, crypto: false };
  }
  return { timeZone: 'America/New_York', closeHour: 16, closeMinute: 5, crypto: false };
}

function sameLocalDate(left: ZonedParts, right: ZonedParts): boolean {
  return left.year === right.year && left.month === right.month && left.day === right.day;
}

function localWeekKey(parts: ZonedParts): number {
  const dayNumber = Math.floor(Date.UTC(parts.year, parts.month - 1, parts.day) / 86_400_000);
  const mondayOffset = (parts.weekday + 6) % 7;
  return dayNumber - mondayOffset;
}

function daysInMonth(year: number, month: number): number {
  return new Date(Date.UTC(year, month, 0)).getUTCDate();
}

/**
 * Whether `time` is the bar-open time of the interval that contains `now`.
 *
 * Daily/weekly/monthly equity bars follow the backend's session convention
 * (Asia/Kolkata for India, America/New_York for global, UTC for crypto).
 * The exact daily bar-open timestamp emitted by the provider is not
 * independently verified, so this deliberately validates the containing
 * session rather than assuming browser-local midnight.
 */
export function isActiveInterval(
  time: number,
  interval: string,
  market: Market | undefined,
  now: number,
): boolean {
  const seconds = intervalSecondsFor(interval);
  if (seconds !== null && interval !== '1d' && interval !== '1wk' && interval !== '1w') {
    return time <= now && now < time + seconds;
  }

  const session = sessionFor(market);
  if (interval === '1d') {
    if (session.crypto) return time <= now && now < time + 86_400;
    const bar = zonedParts(time, session.timeZone);
    const current = zonedParts(now, session.timeZone);
    if (!sameLocalDate(bar, current)) return false;
    return (current.hour < session.closeHour)
      || (current.hour === session.closeHour && current.minute < session.closeMinute);
  }
  if (interval === '3d') {
    return time <= now && now < time + 3 * 86_400;
  }
  if (interval === '1wk' || interval === '1w') {
    if (session.crypto) return time <= now && now < time + 7 * 86_400;
    const bar = zonedParts(time, session.timeZone);
    const current = zonedParts(now, session.timeZone);
    if (localWeekKey(bar) !== localWeekKey(current)) return false;
    const weekComplete = current.weekday > 4
      || (current.weekday === 4
        && ((current.hour > session.closeHour)
          || (current.hour === session.closeHour && current.minute >= session.closeMinute)));
    return !weekComplete;
  }
  if (interval === '1mo' || interval === '1M') {
    const bar = zonedParts(time, session.timeZone);
    const current = zonedParts(now, session.timeZone);
    if (session.crypto) {
      return (bar.year < current.year)
        || (bar.year === current.year && bar.month < current.month)
        ? false
        : time <= now;
    }
    if (bar.year !== current.year || bar.month !== current.month) return false;
    const monthEnd = daysInMonth(current.year, current.month);
    const monthComplete = current.day === monthEnd
      && ((current.hour > session.closeHour)
        || (current.hour === session.closeHour && current.minute >= session.closeMinute));
    return !monthComplete;
  }

  // Unknown interval: use a conservative one-day window.
  return time <= now && now < time + 86_400;
}

/**
 * Whether the bar-open time is aligned to the interval. Intraday and crypto
 * bars are UTC-aligned; equity bars can be anchored to the exchange session
 * open, so a multiple of the interval from the latest finalized bar is also
 * accepted.
 */
export function isAlignedToInterval(
  time: number,
  interval: string,
  market: Market | undefined,
  referenceTime: number | null,
): boolean {
  const seconds = intervalSecondsFor(interval);
  if (seconds !== null) {
    if (time % seconds === 0) return true;
    if (referenceTime !== null && Math.abs(time - referenceTime) % seconds === 0) return true;
    return false;
  }
  if (interval === '1mo' || interval === '1M') {
    const session = sessionFor(market);
    if (referenceTime === null) return true;
    const bar = zonedParts(time, session.timeZone);
    const reference = zonedParts(referenceTime, session.timeZone);
    return bar.day === reference.day
      || (bar.day === 1 && bar.hour === 0);
  }
  return true;
}

function sourceRank(source: CandleSource): number {
  if (source === 'polled') return 3;
  if (source === 'forming') return 2;
  if (source === 'snapshot') return 1;
  return 0;
}

function shouldReplace(
  incomingSequence: number,
  incomingSource: CandleSource,
  existingSequence: number,
  existingSource: CandleSource,
): boolean {
  if (incomingSequence !== existingSequence) return incomingSequence > existingSequence;
  return sourceRank(incomingSource) > sourceRank(existingSource);
}

interface FinalizedEntry {
  candle: NormalizedCandle;
  source: CandleSource;
  sequence: number;
}

function reject(
  diagnostics: ReconcileDiagnostics,
  source: CandleSource,
  time: number | null,
  reason: ValidationReason,
): void {
  diagnostics.rejected.push({ source, time, reason });
}

function formingRejectionReason(
  time: number,
  latestFinalizedTime: number | null,
  interval: string,
  market: Market | undefined,
  now: number,
): ValidationReason | null {
  if (latestFinalizedTime !== null && time <= latestFinalizedTime) {
    return time === latestFinalizedTime ? 'ALREADY_FINALIZED' : 'STALE_TIMESTAMP';
  }
  if (!isAlignedToInterval(time, interval, market, latestFinalizedTime)) {
    return 'MISALIGNED_TIMESTAMP';
  }
  if (!isActiveInterval(time, interval, market, now)) {
    return 'INACTIVE_INTERVAL';
  }
  return null;
}

/**
 * Pure reconciliation of snapshot history, polled confirmed candles, the
 * provider's current forming candle and the per-chart live cache.
 */
export function reconcileCandles(input: ReconcileCandlesInput): ReconcileResult {
  const now = input.now ?? Math.floor(Date.now() / 1000);
  const snapshotSequence = input.snapshotSequence ?? 0;
  const pollSequence = input.pollSequence ?? snapshotSequence + 1;
  const diagnostics: ReconcileDiagnostics = {
    snapshotCount: input.snapshotCandles?.length ?? 0,
    polledCount: input.polledCandles?.length ?? 0,
    cachedCount: input.cachedLive?.length ?? 0,
    latestFinalizedTime: null,
    formingTime: null,
    acceptedFinal: 0,
    acceptedForming: 0,
    rejected: [],
    replaced: 0,
    discarded: 0,
    retained: 0,
    mismatches: [],
  };

  const finalized = new Map<number, FinalizedEntry>();

  const addFinalized = (raw: Candle, source: CandleSource, sequence: number): void => {
    const validation = validateCandle(raw, { referencePrice: input.referencePrice });
    if (!validation.candle) {
      reject(diagnostics, source, validation.time, validation.reasons[0] ?? 'MISSING_FIELD');
      return;
    }
    const time = validation.candle.time;
    const existing = finalized.get(time);
    if (!existing) {
      finalized.set(time, { candle: validation.candle, source, sequence });
      diagnostics.acceptedFinal += 1;
      return;
    }
    if (shouldReplace(sequence, source, existing.sequence, existing.source)) {
      finalized.set(time, { candle: validation.candle, source, sequence });
      diagnostics.replaced += 1;
      return;
    }
    diagnostics.retained += 1;
  };

  for (const candle of input.snapshotCandles ?? []) {
    addFinalized(candle, 'snapshot', snapshotSequence);
  }
  for (const candle of input.polledCandles ?? []) {
    addFinalized(candle, 'polled', pollSequence);
  }

  const finalizedTimes = [...finalized.keys()].sort((left, right) => left - right);
  const latestFinalizedTime = finalizedTimes.length ? finalizedTimes[finalizedTimes.length - 1] : null;
  diagnostics.latestFinalizedTime = latestFinalizedTime;
  const latestFinalizedClose = latestFinalizedTime === null
    ? null
    : finalized.get(latestFinalizedTime)?.candle.close ?? null;

  let activeForming: NormalizedCandle | null = null;
  const referencePrice = latestFinalizedClose ?? input.referencePrice ?? null;

  const evaluateForming = (
    raw: Candle,
    source: CandleSource,
  ): NormalizedCandle | null => {
    const validation = validateCandle(raw, {
      referencePrice,
      referenceTime: latestFinalizedTime,
    });
    if (!validation.candle) {
      reject(diagnostics, source, validation.time, validation.reasons[0] ?? 'MISSING_FIELD');
      return null;
    }
    const reason = formingRejectionReason(
      validation.candle.time,
      latestFinalizedTime,
      input.interval,
      input.market,
      now,
    );
    if (reason) {
      reject(diagnostics, source, validation.candle.time, reason);
      return null;
    }
    return validation.candle;
  };

  if (input.formingCandle) {
    activeForming = evaluateForming(input.formingCandle, 'forming');
    // A present-but-invalid provider forming candle is not replaced by stale
    // cache: that would hide a backend problem.
  } else {
    // A null forming candle is normal when the interval has just completed.
    // Retain the last cached forming bar only while its interval is still the
    // active one, which keeps the chart alive through a temporary poll failure.
    const cachedForming = (input.cachedLive ?? [])
      .filter((entry) => entry.status === 'forming')
      .sort((left, right) => right.time - left.time || right.sequence - left.sequence);
    for (const entry of cachedForming) {
      if (finalized.has(entry.time)) {
        reject(diagnostics, 'cached', entry.time, 'ALREADY_FINALIZED');
        diagnostics.discarded += 1;
        continue;
      }
      const candidate = evaluateForming(entry.candle, 'cached');
      if (candidate && !activeForming) {
        activeForming = candidate;
      } else if (!candidate) {
        diagnostics.discarded += 1;
      }
    }
  }

  if (input.formingCandle) {
    for (const entry of input.cachedLive ?? []) {
      if (entry.status !== 'forming') {
        if (finalized.has(entry.time)) diagnostics.retained += 1;
        else diagnostics.discarded += 1;
        continue;
      }
      if (finalized.has(entry.time)) {
        reject(diagnostics, 'cached', entry.time, 'ALREADY_FINALIZED');
        diagnostics.discarded += 1;
      } else if (activeForming && entry.time === activeForming.time) {
        diagnostics.retained += 1;
      } else if (!activeForming) {
        // The provider explicitly returned no valid forming bar.
        diagnostics.discarded += 1;
      } else {
        diagnostics.discarded += 1;
      }
    }
  }

  if (activeForming) {
    diagnostics.acceptedForming = 1;
    diagnostics.formingTime = activeForming.time;
  }

  const candles: ReconciledCandle[] = finalizedTimes
    .map((time) => {
      const entry = finalized.get(time)!;
      return { ...entry.candle, status: 'final' as const };
    });
  if (activeForming) {
    candles.push({ ...activeForming, status: 'forming' });
  }
  candles.sort((left, right) => left.time - right.time);
  const limited = typeof input.maxCandles === 'number' && input.maxCandles > 0
    ? candles.slice(-input.maxCandles)
    : candles;

  const latestFinalized = limited.filter((candle) => candle.status === 'final').at(-1) ?? null;
  const forming = limited.find((candle) => candle.status === 'forming') ?? null;

  return {
    candles: limited,
    diagnostics,
    latestFinalized,
    forming,
  };
}

/**
 * The prior completed close used for the day-change calculation.
 *
 * While a forming candle is active the latest finalized candle is the prior
 * close. Without a forming candle the change is measured against the bar
 * before the latest completed one.
 */
export function resolvePreviousClose(
  input: Pick<
    ReconcileCandlesInput,
    'snapshotCandles' | 'polledCandles' | 'formingCandle' | 'interval' | 'market' | 'now'
  >,
): number | null {
  const now = input.now ?? Math.floor(Date.now() / 1000);
  const snapshotSequence = 0;
  const pollSequence = 1;
  const finalized = new Map<number, { close: number; sequence: number; source: CandleSource }>();

  const add = (raw: Candle, source: CandleSource, sequence: number): void => {
    const validation = validateCandle(raw);
    if (!validation.candle) return;
    const time = validation.candle.time;
    const existing = finalized.get(time);
    if (!existing || shouldReplace(sequence, source, existing.sequence, existing.source)) {
      finalized.set(time, { close: validation.candle.close, sequence, source });
    }
  };
  for (const candle of input.snapshotCandles ?? []) add(candle, 'snapshot', snapshotSequence);
  for (const candle of input.polledCandles ?? []) add(candle, 'polled', pollSequence);

  const times = [...finalized.keys()].sort((left, right) => left - right);
  if (times.length === 0) return null;
  const latestTime = times[times.length - 1];

  const formingValidation = input.formingCandle
    ? validateCandle(input.formingCandle)
    : null;
  const hasActiveForming = Boolean(
    formingValidation?.candle
    && formingRejectionReason(
      formingValidation.candle.time,
      latestTime,
      input.interval,
      input.market,
      now,
    ) === null,
  );

  if (hasActiveForming) {
    return finalized.get(latestTime)?.close ?? null;
  }
  return times.length >= 2 ? finalized.get(times[times.length - 2])?.close ?? null : null;
}

/** Exposed for store/diagnostics without duplicating the parser. */
export function candleTime(candle: Candle): number | null {
  return parseTimestampToEpochSeconds(candle.timestamp);
}
