import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { ReactNode } from "react";
import { useLocation, useSearchParams } from "react-router-dom";
import { useQuotes } from "../hooks/useQuotes";
import { instrumentService } from "../services/instrumentService";
import { portfolioService } from "../services/portfolioService";
import type { Instrument, InstrumentCapabilities, Market } from "../types/api";
import {
  defaultDaysFor,
  exchangeForMarket,
  normalizeIntervalForIntervals,
  timeframesFor,
  timeframesForIntervals,
} from "../utils/timeframes";
import type { TimeframeOption } from "../utils/timeframes";
import { instrumentIdFromLegacy } from "../utils/navigation";

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
  isAdjusted: boolean | null;
  interval: string;
}

type ResolutionStatus =
  | "resolved"
  | "ambiguous"
  | "unsupported"
  | "not_found"
  | "loading"
  | "error";

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
  resolutionStatus: ResolutionStatus;
  reload: () => void;
}

const SelectedInstrumentContext = createContext<SelectedInstrumentValue | null>(
  null,
);

function asMarket(value: string | null): Market | null {
  return value === "india" || value === "global" || value === "crypto"
    ? value
    : null;
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
  const parts = instrumentId.split(":");
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

function messageForStatus(
  status: ResolutionStatus,
  fallback: string | null,
): string | null {
  if (status === "ambiguous")
    return "Multiple supported instruments match this search. Select the correct listing.";
  if (status === "unsupported")
    return (
      fallback ??
      "Instrument was recognized, but no supported market-data source is available."
    );
  if (status === "not_found")
    return fallback ?? "No supported instrument matches the current selection.";
  if (status === "error")
    return fallback ?? "Unable to resolve the selected instrument.";
  return fallback;
}

export function SelectedInstrumentProvider({
  children,
}: {
  children: ReactNode;
}) {
  const [params, setParams] = useSearchParams();
  const location = useLocation();

  const rawInstrument = (params.get("instrument") ?? "").trim();
  const rawSymbol = (params.get("symbol") ?? "").trim().toUpperCase();
  const rawMarket = asMarket(params.get("market"));
  const rawExchange = params.get("exchange")?.trim().toUpperCase() ?? null;
  const hasLegacyParams =
    params.has("symbol") || params.has("market") || params.has("exchange");

  const canonicalParts = useMemo(() => {
    if (!rawInstrument) return null;
    return identityFromId(rawInstrument);
  }, [rawInstrument]);

  const requestedInstrumentId = useMemo(() => {
    if (canonicalParts) {
      return canonicalParts.instrumentId;
    }
    if (rawInstrument && rawInstrument.includes(":")) {
      return rawInstrument;
    }
    return "";
  }, [canonicalParts, rawInstrument]);

  const legacyQuery =
    rawInstrument && !rawInstrument.includes(":") ? rawInstrument : rawSymbol;

  const [selection, setSelection] = useState<{
    instrument: Instrument | null;
    status: ResolutionStatus;
    message: string | null;
    loading: boolean;
    error: string | null;
  }>({
    instrument: null,
    status: "loading",
    message: null,
    loading: false,
    error: null,
  });
  const selectionRequestRef = useRef(0);

  useEffect(() => {
    const requestId = ++selectionRequestRef.current;
    const controller = new AbortController();
    const isCanonical =
      Boolean(canonicalParts) ||
      Boolean(rawInstrument && rawInstrument.includes(":"));

    if (!rawInstrument && !rawSymbol && location.pathname === "/analysis") {
      setSelection({
        instrument: null,
        status: "loading",
        message: null,
        loading: true,
        error: null,
      });
      let active = true;
      portfolioService
        .getWatchlist()
        .then((res) => {
          if (!active || requestId !== selectionRequestRef.current) return;
          const first = res.items?.[0];
          if (!first) {
            setSelection({
              instrument: null,
              status: "loading",
              message: null,
              loading: false,
              error: null,
            });
            return;
          }
          const targetId =
            first.instrument_id ??
            instrumentIdFromLegacy(first.symbol, first.market, first.exchange);
          setParams(
            (current) => {
              const next = new URLSearchParams(current);
              next.set("instrument", targetId);
              return next;
            },
            { replace: true },
          );
        })
        .catch(() => {
          if (active && requestId === selectionRequestRef.current) {
            setSelection({
              instrument: null,
              status: "error",
              message: "Unable to load your watchlist.",
              loading: false,
              error: "Unable to load your watchlist.",
            });
          }
        });
      return () => {
        active = false;
      };
    }

    if (!requestedInstrumentId && !legacyQuery) {
      setSelection({
        instrument: null,
        status: "loading",
        message: null,
        loading: false,
        error: null,
      });
      return undefined;
    }

    if (!requestedInstrumentId && legacyQuery) {
      const query = legacyQuery;
      setSelection((current) => ({
        ...current,
        loading: true,
        error: null,
        status: "loading",
      }));

      void instrumentService
        .resolve(query, controller.signal)
        .then((res) => {
          if (
            controller.signal.aborted ||
            requestId !== selectionRequestRef.current
          )
            return;
          if (res.status === "resolved" && res.instrument) {
            const canonicalId = res.instrument.instrument_id;
            if (rawInstrument !== canonicalId || hasLegacyParams) {
              setParams(
                (current) => {
                  const next = new URLSearchParams(current);
                  next.delete("symbol");
                  next.delete("market");
                  next.delete("exchange");
                  next.set("instrument", canonicalId);
                  return next;
                },
                { replace: true },
              );
            }
            setSelection({
              instrument: res.instrument,
              status: "resolved",
              message: null,
              loading: false,
              error: null,
            });
            return;
          }
          if (res.status === "ambiguous") {
            setSelection({
              instrument: null,
              status: "ambiguous",
              message:
                res.message ??
                "Multiple supported instruments matched your search.",
              loading: false,
              error: null,
            });
            return;
          }
          if (res.status === "unsupported") {
            setSelection({
              instrument: null,
              status: "unsupported",
              message:
                res.message ??
                "This instrument was recognized, but market data is unavailable.",
              loading: false,
              error: null,
            });
            return;
          }
          if (res.status === "not_found") {
            setSelection({
              instrument: null,
              status: "not_found",
              message: res.message ?? "No supported instrument was found.",
              loading: false,
              error: null,
            });
            return;
          }
          setSelection({
            instrument: null,
            status: "error",
            message: "Unable to resolve the selected instrument.",
            loading: false,
            error: "Unable to resolve the selected instrument.",
          });
        })
        .catch((caught: unknown) => {
          if (requestId !== selectionRequestRef.current) return;
          const errorMessage =
            caught instanceof Error
              ? caught.message
              : "Unable to resolve the selected instrument.";
          setSelection({
            instrument: null,
            status: "error",
            message: errorMessage,
            loading: false,
            error: errorMessage,
          });
        });

      return () => {
        controller.abort();
      };
    }

    if (
      requestedInstrumentId &&
      !isCanonical &&
      rawInstrument &&
      rawInstrument.includes(":")
    ) {
      setSelection({
        instrument: null,
        status: "error",
        message: "Invalid instrument identifier in the URL.",
        loading: false,
        error: "Invalid instrument identifier in the URL.",
      });
      return () => controller.abort();
    }

    if (!requestedInstrumentId) {
      setSelection({
        instrument: null,
        status: "error",
        message: "No instrument selected.",
        loading: false,
        error: "No instrument selected.",
      });
      return () => controller.abort();
    }

    if (selection.instrument?.instrument_id === requestedInstrumentId) {
      return undefined;
    }

    setSelection((current) => ({
      ...current,
      loading: true,
      error: null,
      status: "loading",
    }));

    void instrumentService
      .get(requestedInstrumentId, controller.signal)
      .then((instrument) => {
        if (requestId !== selectionRequestRef.current) return;
        const canonicalId = instrument.instrument_id;
        if (rawInstrument !== canonicalId || hasLegacyParams) {
          setParams(
            (current) => {
              const next = new URLSearchParams(current);
              next.delete("symbol");
              next.delete("market");
              next.delete("exchange");
              next.set("instrument", canonicalId);
              return next;
            },
            { replace: true },
          );
        }
        setSelection({
          instrument,
          status: "resolved",
          message: null,
          loading: false,
          error: null,
        });
      })
      .catch((caught: unknown) => {
        if (requestId !== selectionRequestRef.current) return;
        const message =
          caught instanceof Error
            ? caught.message
            : "Unable to load instrument details.";
        setSelection({
          instrument: null,
          status: "error",
          message,
          loading: false,
          error: message,
        });
      });

    return () => {
      controller.abort();
    };
  }, [
    canonicalParts,
    hasLegacyParams,
    legacyQuery,
    location.pathname,
    rawInstrument,
    rawMarket,
    rawExchange,
    rawSymbol,
    requestedInstrumentId,
    selection.instrument?.instrument_id,
    setParams,
  ]);

  const instrument = selection.instrument;
  const capabilities = instrument?.capabilities ?? null;
  const resolvedIdentity = useMemo<IdentityParts | null>(() => {
    if (instrument) {
      return {
        instrumentId: instrument.instrument_id,
        market: instrument.market,
        exchange: instrument.exchange,
        symbol: instrument.symbol,
      };
    }
    if (canonicalParts) {
      return canonicalParts;
    }
    if (rawSymbol) {
      const market: Market = rawMarket ?? "india";
      const exchange = rawExchange ?? exchangeForMarket(market);
      return {
        instrumentId: instrumentIdFromLegacy(rawSymbol, market, exchange),
        market,
        exchange,
        symbol: rawSymbol,
      };
    }
    if (rawInstrument && rawInstrument.includes(":")) {
      return identityFromId(rawInstrument);
    }
    return null;
  }, [
    canonicalParts,
    instrument,
    rawExchange,
    rawInstrument,
    rawMarket,
    rawSymbol,
  ]);

  const market = instrument?.market ?? resolvedIdentity?.market ?? "crypto";
  const symbol = instrument?.symbol ?? resolvedIdentity?.symbol ?? "";
  const exchange = instrument?.exchange ?? resolvedIdentity?.exchange ?? "";
  const name = instrument?.name ?? symbol;
  const currency = instrument?.currency ?? "";
  const enabled = Boolean(instrument || resolvedIdentity);
  const instrumentId =
    instrument?.instrument_id ?? resolvedIdentity?.instrumentId ?? "";

  const timeframes = useMemo<TimeframeOption[]>(() => {
    if (capabilities?.supported_intervals?.length) {
      return timeframesForIntervals(capabilities.supported_intervals);
    }
    return timeframesFor(market);
  }, [capabilities, market]);

  const requestedInterval = params.get("interval") ?? "1d";
  const interval = normalizeIntervalForIntervals(
    timeframes.map((option) => option.id),
    requestedInterval,
  );
  const days = asDays(params.get("days"), interval);

  const refs = useMemo(
    () =>
      enabled && instrumentId
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
    [currency, enabled, exchange, instrumentId, market, symbol],
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
      isAdjusted: live.is_adjusted ?? null,
      interval,
    };
  }, [interval, live]);

  const errorMessage = messageForStatus(
    selection.status,
    selection.error ?? selection.message ?? null,
  );

  const value = useMemo<SelectedInstrumentValue>(
    () => ({
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
      loading: selection.loading,
      quote,
      quoteLoading,
      error: errorMessage,
      resolutionStatus: selection.status,
      reload: () => {
        if (selection.instrument?.instrument_id) {
          selectionRequestRef.current += 1;
        }
        refresh();
      },
    }),
    [
      capabilities,
      currency,
      days,
      enabled,
      errorMessage,
      exchange,
      instrument,
      instrumentId,
      interval,
      market,
      name,
      quote,
      quoteLoading,
      refresh,
      selection.loading,
      selection.status,
      symbol,
      timeframes,
    ],
  );

  return (
    <SelectedInstrumentContext.Provider value={value}>
      {children}
    </SelectedInstrumentContext.Provider>
  );
}

export function useSelectedInstrument(): SelectedInstrumentValue {
  const context = useContext(SelectedInstrumentContext);
  if (!context) {
    throw new Error(
      "useSelectedInstrument must be used inside <SelectedInstrumentProvider>",
    );
  }
  return context;
}
