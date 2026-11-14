import { createContext, useContext, useMemo } from 'react';
import type { ReactNode } from 'react';
import { useLocation, useSearchParams } from 'react-router-dom';
import { useApi } from '../hooks/useApi';
import { marketService } from '../services/marketService';
import type { Market } from '../types/api';
import { defaultDaysFor, exchangeForMarket, normalizeIntervalForMarket } from '../utils/timeframes';

export interface SelectedQuote {
  last: number;
  previous: number | null;
  change: number | null;
  changePct: number | null;
  high: number;
  low: number;
  volume: number;
  source: string;
  asOf: string;
  isStale: boolean;
  isAdjusted: boolean;
  interval: string;
}

interface SelectedInstrumentValue {
  symbol: string;
  market: Market;
  exchange: string;
  interval: string;
  days: number;
  enabled: boolean;
  quote: SelectedQuote | null;
  loading: boolean;
  error: string | null;
  reload: () => void;
}

const SelectedInstrumentContext = createContext<SelectedInstrumentValue | null>(null);

function asMarket(value: string | null, fallback: Market): Market {
  return value === 'india' || value === 'global' || value === 'crypto' ? value : fallback;
}

function asDays(value: string | null, interval: string): number {
  const parsed = Number(value);
  if (Number.isFinite(parsed) && parsed >= 1 && parsed <= 3650) {
    return parsed;
  }
  return defaultDaysFor(interval);
}

/**
 * Resolves the instrument referenced by the URL and exposes a lightweight quote
 * built from backend candles. The quote is presentation only: both closes and
 * the difference come from the provider response.
 */
export function SelectedInstrumentProvider({ children }: { children: ReactNode }) {
  const [params] = useSearchParams();
  const location = useLocation();
  const cryptoRoute = location.pathname.startsWith('/crypto');
  const symbol = (params.get('symbol') ?? '').trim().toUpperCase();
  const rawMarket = asMarket(params.get('market'), cryptoRoute ? 'crypto' : 'india');
  // /stocks analyses equities only, /crypto analyses crypto only.
  const market: Market = cryptoRoute ? 'crypto' : rawMarket === 'crypto' ? 'india' : rawMarket;
  const exchange = params.get('exchange') ?? exchangeForMarket(market);
  const interval = normalizeIntervalForMarket(market, params.get('interval') ?? '1d');
  const days = asDays(params.get('days'), interval);
  const enabled = symbol.length > 0;

  // The quote always uses the latest daily bars so the top bar, the watchlist
  // and the sidebar report the same session change at every chart timeframe.
  const daily = useApi(
    (signal) =>
      marketService.getCandles({ symbol, market, exchange, interval: '1d', days: 7 }, signal),
    [symbol, market, exchange],
    { enabled },
  );

  const quote = useMemo<SelectedQuote | null>(() => {
    const data = daily.data;
    if (!data || data.candles.length === 0) {
      return null;
    }
    const last = data.candles[data.candles.length - 1];
    const previous = data.candles.length > 1 ? data.candles[data.candles.length - 2] : null;
    const change = previous ? last.close - previous.close : null;
    const changePct =
      previous && previous.close !== 0 && change !== null ? (change / previous.close) * 100 : null;
    return {
      last: last.close,
      previous: previous?.close ?? null,
      change,
      changePct,
      high: last.high,
      low: last.low,
      volume: last.volume,
      source: data.source,
      asOf: data.last_candle_at,
      isStale: data.is_stale,
      isAdjusted: data.is_adjusted,
      interval: data.interval,
    };
  }, [daily.data]);

  const value: SelectedInstrumentValue = {
    symbol,
    market,
    exchange,
    interval,
    days,
    enabled,
    quote,
    loading: daily.loading,
    error: daily.error,
    reload: daily.reload,
  };

  return (
    <SelectedInstrumentContext.Provider value={value}>
      {children}
    </SelectedInstrumentContext.Provider>
  );
}

export function useSelectedInstrument(): SelectedInstrumentValue {
  const value = useContext(SelectedInstrumentContext);
  if (!value) {
    throw new Error('useSelectedInstrument must be used inside SelectedInstrumentProvider');
  }
  return value;
}
