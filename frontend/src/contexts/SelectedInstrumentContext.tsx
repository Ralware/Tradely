import { createContext, useContext, useEffect, useMemo } from 'react';
import type { ReactNode } from 'react';
import { useLocation, useSearchParams } from 'react-router-dom';
import { useApi } from '../hooks/useApi';
import { useQuotes } from '../hooks/useQuotes';
import { instrumentService } from '../services/instrumentService';
import type {
  Instrument,
  InstrumentCapabilities,
  Market,
} from '../types/api';
import {
  defaultDaysFor,
  exchangeForMarket,
  normalizeIntervalForIntervals,
  timeframesFor,
  timeframesForIntervals,
} from '../utils/timeframes';
import type { TimeframeOption } from '../utils/timeframes';
import { instrumentIdFromLegacy } from '../utils/navigation';

export interface SelectedQuote {
  last: number | null;
  previous: number | null;
  change: number | null;
  changePct: number | null;
  high: number | null;
  low: number | null;
  volume: number | null;
  source: string;
  asOf: string | null;
  isStale: boolean;
  isAdjusted: boolean;
  interval: string;
}

interface SelectedInstrumentValue {
  symbol: string;
  name: string;
  market: Market;
  exchange: string;
  currency: string;
  instrumentId: string;
  instrument: Instrument | null;
  capabilities: InstrumentCapabilities | null;
  timeframes: TimeframeOption[];
  interval: string;
  days: number;
  enabled: boolean;
  loading: boolean;
  quote: SelectedQuote | null;
  quoteLoading: boolean;
  error: string | null;
  reload: () => void;
}

const SelectedInstrumentContext = createContext<SelectedInstrumentValue | null>(null);

function asMarket(value: string | null): Market | null {
  return value === 'india' || value === 'global' || value === 'crypto' ? value : null;
}

function asDays(value: string | null, interval: string): number {
  const parsed = Number(value);
  if (Number.isFinite(parsed) && parsed >= 1 && parsed <= 3650) {
    return parsed;
  }
  return defaultDaysFor(interval);
}

interface IdentityParts {
  instrumentId: string;
  market: Market;
  exchange: string;
  symbol: string;
}

function identityFromId(instrumentId: string): IdentityParts | null {
  const parts = instrumentId.split(':');
  if (parts.length !== 3) {
    return null;
  }
  const market = asMarket(parts[0]);
  if (!market) {
    return null;
  }
  return {
    instrumentId,
    market,
    exchange: parts[1].toUpperCase(),
    symbol: parts[2].toUpperCase(),
  };
}

/**
 * Resolves the instrument referenced by the URL and reads its quote from the
 * app-wide quote hub.
 *
 * The canonical URL parameter is `instrument=<instrument_id>`. Legacy
 * `symbol`/`market`/`exchange` links are accepted and normalised once the
 * backend confirms the identity, so old bookmarks keep working.
 */
export function SelectedInstrumentProvider({ children }: { children: ReactNode }) {
  const [params, setParams] = useSearchParams();
  const location = useLocation();
  const cryptoRoute = location.pathname.startsWith('/crypto');

  const instrumentParam = (params.get('instrument') ?? '').trim();
  const legacySymbol = (params.get('symbol') ?? '').trim().toUpperCase();
  const legacyMarket =
    asMarket(params.get('market')) ?? (cryptoRoute ? 'crypto' : 'india');
  const legacyExchange = params.get('exchange') ?? exchangeForMarket(legacyMarket);

  const identity = useMemo<IdentityParts | null>(() => {
    if (instrumentParam) {
      const parsed = identityFromId(instrumentParam);
      if (parsed) {
        return parsed;
      }
      return {
        instrumentId: instrumentParam,
        market: legacyMarket,
        exchange: legacyExchange.toUpperCase(),
        symbol: legacySymbol,
      };
    }
    if (legacySymbol) {
      return {
        instrumentId: instrumentIdFromLegacy(legacySymbol, legacyMarket, legacyExchange),
        market: legacyMarket,
        exchange: legacyExchange.toUpperCase(),
        symbol: legacySymbol,
      };
    }
    return null;
  }, [instrumentParam, legacySymbol, legacyMarket, legacyExchange]);

  const enabled = identity !== null;
  const instrumentId = identity?.instrumentId ?? '';
  const metadata = useApi(
    (signal) => instrumentService.get(instrumentId, signal),
    [instrumentId],
    { enabled },
  );

  const instrument = metadata.data;
  const capabilities = instrument?.capabilities ?? null;
  const market = instrument?.market ?? identity?.market ?? legacyMarket;
  const symbol = instrument?.symbol ?? identity?.symbol ?? '';
  const exchange = instrument?.exchange ?? identity?.exchange ?? legacyExchange;
  const name = instrument?.name ?? symbol;
  const currency = instrument?.currency ?? '';

  const timeframes = useMemo<TimeframeOption[]>(() => {
    if (capabilities?.supported_intervals?.length) {
      return timeframesForIntervals(capabilities.supported_intervals);
    }
    return timeframesFor(market);
  }, [capabilities, market]);

  const requestedInterval = params.get('interval') ?? '1d';
  const interval = normalizeIntervalForIntervals(
    timeframes.map((option) => option.id),
    requestedInterval,
  );
  const days = asDays(params.get('days'), interval);

  // Migrate legacy links to the canonical parameter without a full navigation.
  useEffect(() => {
    if (instrumentParam || !metadata.data) {
      return;
    }
    const next = new URLSearchParams(params);
    next.delete('symbol');
    next.delete('market');
    next.delete('exchange');
    next.set('instrument', metadata.data.instrument_id);
    setParams(next, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [instrumentParam, metadata.data]);

  const refs = useMemo(
    () =>
      enabled
        ? [
            {
              instrument_id: instrumentId,
              symbol,
              market,
              exchange,
              currency: currency || undefined,
            },
          ]
        : [],
    [enabled, instrumentId, symbol, market, exchange, currency],
  );
  const { quotes, loading: quoteLoading, refresh } = useQuotes(refs);
  const live = quotes.get(instrumentId) ?? null;

  const quote = useMemo<SelectedQuote | null>(() => {
    if (!live) {
      return null;
    }
    return {
      last: live.price,
      previous: live.previous_close,
      change: live.day_change,
      changePct: live.day_change_pct,
      high: live.day_high,
      low: live.day_low,
      volume: live.volume,
      source: live.provider,
      asOf: live.quote_time ?? live.retrieved_at,
      isStale: live.is_stale,
      isAdjusted: Boolean(live.is_adjusted),
      interval,
    };
  }, [live, interval]);

  const value: SelectedInstrumentValue = {
    symbol,
    name,
    market,
    exchange,
    currency,
    instrumentId,
    instrument,
    capabilities,
    timeframes,
    interval,
    days,
    enabled,
    loading: metadata.loading,
    quote,
    quoteLoading,
    error: metadata.error ?? live?.error ?? null,
    reload: () => {
      metadata.reload();
      refresh();
    },
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
