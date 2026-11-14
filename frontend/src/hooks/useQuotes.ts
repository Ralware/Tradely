import { useCallback, useEffect, useRef, useState } from 'react';
import { quoteHub, type QuoteRef } from '../services/quoteHub';
import type { Quote } from '../types/api';

export interface UseQuotesResult {
  quotes: Map<string, Quote>;
  loading: boolean;
  refresh: () => void;
}

/**
 * Retains a set of instruments in the shared quote hub and re-renders when any
 * of their quotes change. The hub batches the REST request and owns the SSE
 * subscription, so mounting another consumer does not duplicate provider calls.
 */
export function useQuotes(instruments: QuoteRef[]): UseQuotesResult {
  const signature = instruments.map((item) => item.instrument_id).sort().join('|');
  const instrumentsRef = useRef(instruments);
  instrumentsRef.current = instruments;

  const [, setVersion] = useState(0);
  const [timedOut, setTimedOut] = useState(false);

  useEffect(
    () =>
      quoteHub.subscribe(() => {
        setVersion((value) => value + 1);
      }),
    [],
  );

  useEffect(() => {
    const release = quoteHub.retain(instrumentsRef.current);
    return release;
  }, [signature]);

  useEffect(() => {
    if (instruments.length === 0) {
      return;
    }
    setTimedOut(false);
    const timer = window.setTimeout(() => setTimedOut(true), 1500);
    return () => window.clearTimeout(timer);
  }, [signature, instruments.length]);

  const quotes = new Map<string, Quote>();
  for (const instrument of instruments) {
    const quote = quoteHub.get(instrument.instrument_id);
    if (quote) {
      quotes.set(instrument.instrument_id, quote);
    }
  }

  const refresh = useCallback(() => {
    setTimedOut(false);
    quoteHub.refresh(true);
  }, []);

  // The version state update above forces a render; the map is rebuilt here so
  // no stale quote object survives a provider refresh.
  return {
    quotes,
    loading: instruments.length > 0 && !timedOut && quotes.size === 0,
    refresh,
  };
}
