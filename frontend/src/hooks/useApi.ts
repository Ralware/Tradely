import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from '../services/api';

export interface ApiState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}

export interface UseApiResult<T> extends ApiState<T> {
  reload: () => void;
}

function toMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return 'Request failed';
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError';
}

/**
 * Small typed data-fetching hook with cancellation and a manual reload trigger.
 * Keeps the previous data visible while a reload is in flight so the UI does not
 * flash between loading states.
 */
export function useApi<T>(
  fetcher: (signal: AbortSignal) => Promise<T>,
  deps: readonly unknown[],
  options: { enabled?: boolean } = {},
): UseApiResult<T> {
  const enabled = options.enabled ?? true;
  const [state, setState] = useState<ApiState<T>>({
    data: null,
    loading: enabled,
    error: null,
  });
  const [reloadToken, setReloadToken] = useState(0);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  useEffect(() => {
    if (!enabled) {
      setState({ data: null, loading: false, error: null });
      return;
    }

    const controller = new AbortController();
    let active = true;

    setState((previous) => ({ data: previous.data, loading: true, error: null }));

    fetcherRef
      .current(controller.signal)
      .then((data) => {
        if (!active) {
          return;
        }
        setState({ data, loading: false, error: null });
      })
      .catch((error: unknown) => {
        if (!active || isAbort(error)) {
          return;
        }
        setState({ data: null, loading: false, error: toMessage(error) });
      });

    return () => {
      active = false;
      controller.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, enabled, reloadToken]);

  const reload = useCallback(() => {
    setReloadToken((token) => token + 1);
  }, []);

  return { ...state, reload };
}
