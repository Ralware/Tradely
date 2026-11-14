import { useEffect, useState } from 'react';
import { useApi } from './useApi';
import { marketService } from '../services/marketService';
import { portfolioService } from '../services/portfolioService';
import type { WatchlistItem } from '../types/api';
import { WATCHLIST_CHANGED_EVENT } from '../utils/events';

export interface WatchlistQuote {
  key: string;
  item: WatchlistItem;
  last: number | null;
  change: number | null;
  changePct: number | null;
  error: string | null;
}

function quoteKey(item: WatchlistItem): string {
  return `${item.market}:${item.symbol}:${item.exchange}`;
}

/**
 * Watchlist rows plus the latest two daily closes for each row. Both closes are
 * provider values; only their difference is computed for display.
 */
export function useWatchlistQuotes() {
  const watchlist = useApi((signal) => portfolioService.getWatchlist(signal), []);
  const [quotes, setQuotes] = useState<WatchlistQuote[]>([]);
  const [quotesLoading, setQuotesLoading] = useState(false);
  const [quotesError, setQuotesError] = useState<string | null>(null);

  useEffect(() => {
    const handleChange = () => watchlist.reload();
    window.addEventListener(WATCHLIST_CHANGED_EVENT, handleChange);
    return () => window.removeEventListener(WATCHLIST_CHANGED_EVENT, handleChange);
  }, [watchlist.reload]);

  useEffect(() => {
    const items = watchlist.data?.items ?? [];
    if (items.length === 0) {
      setQuotes([]);
      setQuotesLoading(false);
      setQuotesError(null);
      return;
    }

    let active = true;
    const controller = new AbortController();
    setQuotesLoading(true);
    setQuotesError(null);

    Promise.allSettled(
      items.map(async (item): Promise<WatchlistQuote> => {
        const response = await marketService.getCandles(
          {
            symbol: item.symbol,
            market: item.market,
            exchange: item.exchange,
            interval: '1d',
            days: 7,
          },
          controller.signal,
        );
        const candles = response.candles;
        const last = candles.length > 0 ? candles[candles.length - 1].close : null;
        const previous = candles.length > 1 ? candles[candles.length - 2].close : null;
        const change = last !== null && previous !== null ? last - previous : null;
        const changePct =
          change !== null && previous !== null && previous !== 0 ? (change / previous) * 100 : null;
        return { key: quoteKey(item), item, last, change, changePct, error: null };
      }),
    ).then((results) => {
      if (!active) {
        return;
      }
      const next = results.map((result, index): WatchlistQuote => {
        if (result.status === 'fulfilled') {
          return result.value;
        }
        const item = items[index];
        return {
          key: quoteKey(item),
          item,
          last: null,
          change: null,
          changePct: null,
          error: 'Unavailable',
        };
      });
      setQuotes(next);
      setQuotesLoading(false);
    });

    return () => {
      active = false;
      controller.abort();
    };
  }, [watchlist.data]);

  return {
    items: watchlist.data?.items ?? [],
    quotes,
    loading: watchlist.loading || quotesLoading,
    error: watchlist.error ?? quotesError,
    reload: watchlist.reload,
  };
}
