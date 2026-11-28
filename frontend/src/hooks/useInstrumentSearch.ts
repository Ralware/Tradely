import { useEffect, useState } from 'react';
import { instrumentService } from '../services/instrumentService';
import type { InstrumentSearchResponse } from '../types/api';

interface SearchOutcome {
  query: string;
  result?: InstrumentSearchResponse;
  error?: string;
}

export function useInstrumentSearch(query: string, enabled: boolean) {
  const [outcome, setOutcome] = useState<SearchOutcome | null>(null);
  const term = enabled ? query.trim() : '';

  useEffect(() => {
    setOutcome(null);
    if (!term) return;
    const controller = new AbortController();
    const timer = window.setTimeout(async () => {
      try {
        const result = await instrumentService.search(term, controller.signal);
        if (!controller.signal.aborted) setOutcome({ query: term, result });
      } catch (error) {
        if (!controller.signal.aborted) {
          setOutcome({ query: term, error: error instanceof Error ? error.message : 'Instrument search failed' });
        }
      }
    }, 220);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [term]);

  // Input and the last completed response change on different renders.
  const current = term && outcome?.query === term ? outcome : null;
  return {
    result: current?.result,
    loading: Boolean(term && !current),
    error: current?.error,
  };
}
