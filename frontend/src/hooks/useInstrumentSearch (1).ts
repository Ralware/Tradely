import { useCallback, useEffect, useState } from "react";
import { instrumentService } from "../services/instrumentService";
import type {
  Instrument,
  InstrumentCandidate,
  InstrumentRecognitionStatus,
  RecognizedAsset,
} from "../types/api";

const DEBOUNCE_MS = 220;

export interface InstrumentSearchState {
  query: string;
  setQuery: (value: string) => void;
  reset: () => void;
  loading: boolean;
  error: string | null;
  status: InstrumentRecognitionStatus | null;
  message: string | null;
  instrument: Instrument | null;
  candidates: InstrumentCandidate[];
  recognized: RecognizedAsset | null;
  run: (value: string) => Promise<void>;
}

function toMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Instrument search failed";
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

/**
 * Debounced recognition against the single backend instrument catalogue. The
 * UI never guesses a market, exchange or provider from the typed text.
 */
export function useInstrumentSearch(initialQuery = ""): InstrumentSearchState {
  const [query, setQuery] = useState(initialQuery);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<InstrumentRecognitionStatus | null>(
    null,
  );
  const [message, setMessage] = useState<string | null>(null);
  const [instrument, setInstrument] = useState<Instrument | null>(null);
  const [candidates, setCandidates] = useState<InstrumentCandidate[]>([]);
  const [recognized, setRecognized] = useState<RecognizedAsset | null>(null);

  const run = useCallback(async (value: string) => {
    const clean = value.trim();
    if (!clean) {
      return;
    }
    const result = await instrumentService.search(clean);
    setStatus(result.status);
    setMessage(result.message);
    setInstrument(result.status === "resolved" ? result.instrument : null);
    setCandidates(result.candidates ?? []);
    setRecognized(result.recognized ?? null);
  }, []);

  useEffect(() => {
    const clean = query.trim();
    if (!clean) {
      setLoading(false);
      setError(null);
      setStatus(null);
      setMessage(null);
      setInstrument(null);
      setCandidates([]);
      setRecognized(null);
      return;
    }

    const controller = new AbortController();
    let active = true;
    setLoading(true);
    setError(null);
    const timer = window.setTimeout(() => {
      instrumentService
        .search(clean, controller.signal)
        .then((result) => {
          if (!active) {
            return;
          }
          setStatus(result.status);
          setMessage(result.message);
          setInstrument(
            result.status === "resolved" ? result.instrument : null,
          );
          setCandidates(result.candidates ?? []);
          setRecognized(result.recognized ?? null);
        })
        .catch((caught: unknown) => {
          if (!active || isAbort(caught)) {
            return;
          }
          setError(toMessage(caught));
          setStatus(null);
          setMessage(null);
          setInstrument(null);
          setCandidates([]);
          setRecognized(null);
        })
        .finally(() => {
          if (active) {
            setLoading(false);
          }
        });
    }, DEBOUNCE_MS);

    return () => {
      active = false;
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [query]);

  const reset = useCallback(() => {
    setQuery("");
    setStatus(null);
    setMessage(null);
    setInstrument(null);
    setCandidates([]);
    setRecognized(null);
    setError(null);
    setLoading(false);
  }, []);

  return {
    query,
    setQuery,
    reset,
    loading,
    error,
    status,
    message,
    instrument,
    candidates,
    recognized,
    run,
  };
}
