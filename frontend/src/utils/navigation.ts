import type { Market } from '../types/api';

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
  return `${market === 'crypto' ? '/crypto' : '/stocks'}?${params.toString()}`;
}
