import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../services/api";

export interface ApiState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}

export interface UseApiResult<T> extends ApiState<T> {
  /** True while a request is in flight and previous data is still on screen. */
  refreshing: boolean;
  reload: () => void;
}

export interface UseApiOptions {
  enabled?: boolean;
  keepPreviousData?: boolean;
  keepPreviousDataKey?: unknown;
}

function toMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Request failed";
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

/**
 * Robust typed data-fetching hook with cancellation, reload trigger, and stale-response protection.
 */
export function useApi<T>(
  fetcher: (signal: AbortSignal) => Promise<T>,
  deps: readonly unknown[],
  options: UseApiOptions = {},
): UseApiResult<T> {
  const enabled = options.enabled ?? true;
  const keepPreviousData = options.keepPreviousData ?? false;
  const [state, setState] = useState<ApiState<T>>({
    data: null,
    loading: enabled,
    error: null,
  });
  const [reloadToken, setReloadToken] = useState(0);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const previousDataKeyRef = useRef(options.keepPreviousDataKey);

  useEffect(() => {
    if (!enabled) {
      setState({ data: null, loading: false, error: null });
      return;
    }

    const controller = new AbortController();
    let active = true;

    const sameDataKey = Object.is(
      previousDataKeyRef.current,
      options.keepPreviousDataKey,
    );
    previousDataKeyRef.current = options.keepPreviousDataKey;

    setState((previous) => ({
      data: keepPreviousData && sameDataKey ? previous.data : null,
      loading: true,
      error: null,
    }));

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
        setState((previous) => ({
          data: keepPreviousData && sameDataKey ? previous.data : null,
          loading: false,
          error: toMessage(error),
        }));
      });

    return () => {
      active = false;
      controller.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    ...deps,
    enabled,
    reloadToken,
    keepPreviousData,
    options.keepPreviousDataKey,
  ]);

  const reload = useCallback(() => {
    setReloadToken((token) => token + 1);
  }, []);

  return { ...state, refreshing: state.loading && state.data !== null, reload };
}
