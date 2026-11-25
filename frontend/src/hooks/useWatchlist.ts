import { useCallback, useEffect, useState } from 'react';
import { useApi } from './useApi';
import { portfolioService } from '../services/portfolioService';

/**
 * Shared watchlist query. Every consumer reads the same application-scoped
 * cache, so the watchlist page and the analytics sidebar do not issue two
 * separate `/api/watchlist` requests when mounted together.
 */
export function useWatchlist() {
  const [cacheVersion, setCacheVersion] = useState(0);
  useEffect(
    () => portfolioService.subscribeWatchlist(() => setCacheVersion((value) => value + 1)),
    [],
  );

  const watchlist = useApi(
    (signal, context) => portfolioService.getWatchlist(signal, { force: context.force }),
    [cacheVersion],
    { getCachedData: () => portfolioService.getCachedWatchlist() },
  );

  const reload = useCallback(() => {
    watchlist.reload();
  }, [watchlist.reload]);

  return { ...watchlist, reload };
}
