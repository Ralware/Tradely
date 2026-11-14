import type { Instrument, Market } from '../types/api';

function pathFor(market: Market): string {
  return market === 'crypto' ? '/crypto' : '/stocks';
}

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
  return `${pathFor(instrument.market)}?${params.toString()}`;
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

/**
 * Legacy URL builder kept for scanner/signal rows that predate canonical ids.
 * New navigation uses instrumentPath with the resolved instrument.
 */
export function analysisPath(
  symbol: string,
  market: Market,
  exchange?: string | null,
  options: { interval?: string; days?: number } = {},
): string {
  const params = new URLSearchParams({ symbol: symbol.toUpperCase(), market });
  if (exchange) {
    params.set('exchange', exchange.toUpperCase());
  }
  if (options.interval) {
    params.set('interval', options.interval);
  }
  if (options.days) {
    params.set('days', String(options.days));
  }
  return `${pathFor(market)}?${params.toString()}`;
}
