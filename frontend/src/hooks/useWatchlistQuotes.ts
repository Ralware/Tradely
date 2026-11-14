import { useEffect, useMemo } from 'react';
import { useApi } from './useApi';
import { useQuotes } from './useQuotes';
import { portfolioService } from '../services/portfolioService';
import type { Quote, WatchlistItem } from '../types/api';
import { WATCHLIST_CHANGED_EVENT } from '../utils/events';
import { quoteRefFromWatchlist } from '../utils/quotes';

export interface WatchlistQuote {
  key: string;
  item: WatchlistItem;
  last: number | null;
  change: number | null;
  changePct: number | null;
  error: string | null;
  quote: Quote | null;
}

function quoteKey(item: WatchlistItem): string {
  return item.instrument_id ?? `${item.market}:${item.exchange}:${item.symbol}`;
}

/**
 * Watchlist rows plus the latest centralised quote for each row. Prices and
 * timestamps come from the same quote service used by the portfolio and
 * analysis views, so a watchlist row and a held position never disagree.
 */
export function useWatchlistQuotes() {
  const watchlist = useApi((signal) => portfolioService.getWatchlist(signal), []);
  const items = watchlist.data?.items ?? [];
  const refs = useMemo(() => items.map(quoteRefFromWatchlist), [items]);
  const { quotes, loading: quotesLoading, refresh } = useQuotes(refs);

  useEffect(() => {
    const handleChange = () => watchlist.reload();
    window.addEventListener(WATCHLIST_CHANGED_EVENT, handleChange);
    return () => window.removeEventListener(WATCHLIST_CHANGED_EVENT, handleChange);
  }, [watchlist.reload]);

  const rows = useMemo(
    () =>
      items.map((item): WatchlistQuote => {
        const quote = quotes.get(quoteKey(item)) ?? null;
        return {
          key: quoteKey(item),
          item,
          last: quote?.price ?? null,
          change: quote?.day_change ?? null,
          changePct: quote?.day_change_pct ?? null,
          error: quote?.price === null ? quote?.error ?? 'Unavailable' : null,
          quote,
        };
      }),
    [items, quotes],
  );

  return {
    items,
    quotes: rows,
    loading: watchlist.loading || quotesLoading,
    error: watchlist.error,
    reload: () => {
      watchlist.reload();
      refresh();
    },
  };
}
