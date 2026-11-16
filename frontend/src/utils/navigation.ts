import type { Instrument, Market } from '../types/api';

export function instrumentPath(
  instrument: Instrument | { instrument_id: string; market: Market },
  options: { interval?: string; days?: number } = {},
): string {
  const params = new URLSearchParams({ instrument: instrument.instrument_id });
  if (options.interval) {
    params.set('interval', options.interval);
  }
  if (options.days) {
    params.set('days', String(options.days));
  }
  return `/analysis?${params.toString()}`;
}

export function instrumentIdFromLegacy(
  symbol: string,
  market: Market,
  exchange?: string | null,
): string {
  const resolvedExchange =
    exchange || (market === 'crypto' ? 'BINANCE' : market === 'global' ? 'NASDAQ' : 'NSE');
  return `${market}:${resolvedExchange.toUpperCase()}:${symbol.trim().toUpperCase()}`;
}
