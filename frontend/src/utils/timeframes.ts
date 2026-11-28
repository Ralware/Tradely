import type { Market } from '../types/api';

export interface TimeframeOption {
  id: string;
  label: string;
  days: number;
}

const INTRADAY = new Set(['1m', '5m', '15m', '30m', '1h', '2h', '4h']);

const EQUITY_TIMEFRAMES: TimeframeOption[] = [
  { id: '1m', label: '1 Minute', days: 5 },
  { id: '5m', label: '5 Minutes', days: 30 },
  { id: '15m', label: '15 Minutes', days: 30 },
  { id: '30m', label: '30 Minutes', days: 30 },
  { id: '1h', label: '1 Hour', days: 365 },
  { id: '1d', label: '1 Day', days: 3650 },
  { id: '1wk', label: '1 Week', days: 1825 },
  { id: '1mo', label: '1 Month', days: 3650 },
];

const CRYPTO_TIMEFRAMES: TimeframeOption[] = [
  { id: '1m', label: '1 Minute', days: 5 },
  { id: '5m', label: '5 Minutes', days: 30 },
  { id: '15m', label: '15 Minutes', days: 30 },
  { id: '30m', label: '30 Minutes', days: 30 },
  { id: '1h', label: '1 Hour', days: 365 },
  { id: '2h', label: '2 Hours', days: 365 },
  { id: '4h', label: '4 Hours', days: 365 },
  { id: '1d', label: '1 Day', days: 3650 },
  { id: '1wk', label: '1 Week', days: 1825 },
  { id: '1mo', label: '1 Month', days: 3650 },
];

/**
 * Intervals the TradingView backend actually serves. Weekly and monthly bars
 * use the canonical `1wk`/`1mo` IDs so equity and crypto requests hit the same
 * verified interval mapping.
 */
export function timeframesFor(market: Market): TimeframeOption[] {
  return market === 'crypto' ? CRYPTO_TIMEFRAMES : EQUITY_TIMEFRAMES;
}

const ALL_TIMEFRAMES = CRYPTO_TIMEFRAMES;

/** Timeframes exposed by the verified provider for one resolved instrument. */
export function timeframesForIntervals(intervals: string[] | null | undefined): TimeframeOption[] {
  if (!intervals || intervals.length === 0) {
    return [];
  }
  const supported = new Set(intervals);
  return ALL_TIMEFRAMES.filter((option) => supported.has(option.id));
}

export function normalizeIntervalForIntervals(
  intervals: string[] | null | undefined,
  interval: string,
): string {
  if (!intervals || intervals.length === 0) {
    return interval;
  }
  const supported = new Set(intervals);
  let normalized = interval;
  if (supported.has('1wk') && (interval === '1w' || interval === '1wk')) normalized = '1wk';
  else if (supported.has('1mo') && (interval === '1M' || interval === '1mo')) normalized = '1mo';
  if (supported.has(normalized)) {
    return normalized;
  }
  if (supported.has('1d')) {
    return '1d';
  }
  return intervals[0];
}

export function defaultDaysFor(interval: string): number {
  switch (interval) {
    case '1m':
      return 5;
    case '5m':
    case '15m':
    case '30m':
      return 30;
    case '1h':
    case '2h':
    case '4h':
      return 365;
    case '1d':
      return 3650;
    case '1wk':
    case '1w':
      return 1825;
    case '1mo':
    case '1M':
      return 3650;
    default:
      return 3650;
  }
}

/**
 * Mirrors the backend's `_TAIL_LOOKBACK_DAYS`. The one-second poll only needs
 * the provider tail (latest completed bar + forming bar), not the full chart
 * history, so it asks for a small, interval-aware window.
 */
const POLL_TAIL_LOOKBACK_DAYS: Record<string, number> = {
  '1m': 2,
  '3m': 2,
  '5m': 2,
  '15m': 3,
  '30m': 4,
  '45m': 4,
  '1h': 5,
  '2h': 7,
  '4h': 10,
  '6h': 14,
  '8h': 18,
  '12h': 21,
  '1d': 10,
  '3d': 21,
  '1wk': 42,
  '1w': 42,
  '1mo': 90,
  '1M': 90,
};

/**
 * Poll window in days. The backend requires `days >= 1`. Intraday windows get
 * a five-day floor so a Monday or post-holiday request still reaches the last
 * trading session instead of asking for an empty weekend range (HTTP 502).
 */
export function pollDaysFor(interval: string): number {
  const tail = POLL_TAIL_LOOKBACK_DAYS[interval] ?? 10;
  return Math.max(2, Math.min(3650, Math.max(tail, 5)));
}

export function intervalLabel(interval: string): string {
  const option = [...EQUITY_TIMEFRAMES, ...CRYPTO_TIMEFRAMES].find((item) => item.id === interval);
  return option ? option.label : interval;
}

export function isIntradayInterval(interval: string): boolean {
  return INTRADAY.has(interval);
}

export function exchangeForMarket(market: Market): string {
  if (market === 'crypto') return 'BINANCE';
  if (market === 'global') return 'NASDAQ';
  return 'NSE';
}
