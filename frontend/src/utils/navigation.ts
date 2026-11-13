import type { Market } from '../types/api';

export function analysisPath(symbol: string, market: Market, exchange?: string | null): string {
  const params = new URLSearchParams({ symbol: symbol.toUpperCase(), market });
  if (exchange) {
    params.set('exchange', exchange.toUpperCase());
  }
  return `${market === 'crypto' ? '/crypto' : '/stocks'}?${params.toString()}`;
}
