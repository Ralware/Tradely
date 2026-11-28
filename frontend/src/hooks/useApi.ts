import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../services/api";

export interface ApiState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}

export interface UseApiResult<T> extends ApiState<T> {
  /** True while a request is in flight and the last coherent snapshot remains visible. */
  refreshing: boolean;
  /** True when the visible snapshot belongs to the same scope but an older request key. */
  isPreviousData: boolean;
  reload: () => void;
  revalidate: () => void;
}

export interface UseApiFetchContext {
  /**
   * True when this run was triggered by `reload()`. Services use it to bypass
   * their persistent cache and request fresh data from the backend.
   */
  force: boolean;
}

export type ApiFetcher<T> = (
  signal: AbortSignal,
  context: UseApiFetchContext,
) => Promise<T>;

export interface UseApiOptions<T> {
  enabled?: boolean;
  keepPreviousData?: boolean;
  /** Full identity of the requested response (e.g. instrument + timeframe + parameters). */
  keepPreviousDataKey?: unknown;
  /** Identity boundary across which old data must never be retained (e.g. instrument ID). */
  keepPreviousDataScopeKey?: unknown;
  /** Return a fresh cache entry synchronously so keyed views do not flash empty. */
  getCachedData?: () => T | null;
}

interface InternalApiState<T> extends ApiState<T> {
  /** Identity of the data currently stored in `data`. */
  dataKey: unknown;
  /** Scope of the data currently stored in `data`. */
  scopeKey: unknown;
  /** Identity of the most recent request. */
  requestKey: unknown;
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
 * Typed data-fetching hook with cancellation, request identity protection,
 * synchronous keyed-cache reads, and optional same-scope stale-while-revalidate.
 * Old data is never carried across a scope boundary such as a symbol change.
 */
export function useApi<T>(
  fetcher: ApiFetcher<T>,
  deps: readonly unknown[],
  options: UseApiOptions<T> = {},
): UseApiResult<T> {
  const enabled = options.enabled ?? true;
  const keepPreviousData = options.keepPreviousData ?? false;
  const requestKey = options.keepPreviousDataKey;
  const scopeKey = options.keepPreviousDataScopeKey ?? requestKey;
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const cachedDataRef = useRef(options.getCachedData);
  cachedDataRef.current = options.getCachedData;
  const forceRef = useRef(false);

  const [state, setState] = useState<InternalApiState<T>>(() => {
    const cached = enabled ? cachedDataRef.current?.() ?? null : null;
    return {
      data: cached,
      loading: enabled && cached === null,
      error: null,
      dataKey: requestKey,
      scopeKey,
      requestKey,
    };
  });
  const [reloadToken, setReloadToken] = useState(0);

  // A valid exact cache hit is returned during render, before the fetch effect
  // runs. If it misses, the previous snapshot may remain visible only inside
  // the same scope (e.g. changing timeframe for the same instrument).
  const cacheData = enabled ? cachedDataRef.current?.() ?? null : null;
  const canShowStoredData = Object.is(state.scopeKey, scopeKey);
  const data = cacheData ?? (canShowStoredData ? state.data : null);
  const dataKey = cacheData !== null ? requestKey : state.dataKey;
  const isPreviousData = data !== null && !Object.is(dataKey, requestKey);
  const requestMatchesKey = Object.is(state.requestKey, requestKey);
  const loading = enabled && cacheData === null
    ? (requestMatchesKey ? state.loading : true)
    : false;
  const error = requestMatchesKey ? state.error : null;

  useEffect(() => {
    if (!enabled) {
      forceRef.current = false;
      setState({
        data: null,
        loading: false,
        error: null,
        dataKey: requestKey,
        scopeKey,
        requestKey,
      });
      return undefined;
    }

    const controller = new AbortController();
    let active = true;
    const cached = cachedDataRef.current?.() ?? null;
    const force = forceRef.current;
    forceRef.current = false;

    setState((previous) => {
      const sameScope = Object.is(previous.scopeKey, scopeKey);
      const retained = cached ?? (keepPreviousData && sameScope ? previous.data : null);
      const retainedKey = cached !== null
        ? requestKey
        : retained !== null
          ? previous.dataKey
          : requestKey;
      return {
        data: retained,
        loading: force || cached === null,
        error: null,
        dataKey: retainedKey,
        scopeKey,
        requestKey,
      };
    });

    fetcherRef
      .current(controller.signal, { force })
      .then((result) => {
        if (!active) return;
        setState({
          data: result,
          loading: false,
          error: null,
          dataKey: requestKey,
          scopeKey,
          requestKey,
        });
      })
      .catch((caught: unknown) => {
        if (!active || isAbort(caught)) return;
        setState((previous) => {
          const sameScope = Object.is(previous.scopeKey, scopeKey);
          const retained = keepPreviousData && sameScope ? previous.data : null;
          return {
            data: retained,
            loading: false,
            error: toMessage(caught),
            dataKey: retained !== null ? previous.dataKey : requestKey,
            scopeKey,
            requestKey,
          };
        });
      });

    return () => {
      active = false;
      controller.abort();
    };
    // The caller supplies stable dependency values; the fetcher and cache getter are read through refs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    ...deps,
    enabled,
    reloadToken,
    keepPreviousData,
    requestKey,
    scopeKey,
  ]);

  const reload = useCallback(() => {
    forceRef.current = true;
    setReloadToken((token) => token + 1);
  }, []);

  const revalidate = useCallback(() => setReloadToken((token) => token + 1), []);
  return { revalidate, data, loading, error, refreshing: loading && data !== null, isPreviousData, reload };
}
