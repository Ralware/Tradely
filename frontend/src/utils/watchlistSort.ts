import type { Quote, WatchlistItem } from '../types/api';

export type WatchlistSortColumn = 'price' | 'change' | 'changePct';
export type WatchlistSortDirection = 'asc' | 'desc';

export interface WatchlistSort {
  column: WatchlistSortColumn;
  direction: WatchlistSortDirection;
}

export interface WatchlistRow {
  item: WatchlistItem;
  key: string;
  quote: Quote | null;
  originalIndex: number;
}

export function watchlistItemKey(item: WatchlistItem): string {
  return item.instrument_id ?? `${item.market}:${item.exchange}:${item.symbol}`;
}

function numeric(value: number | null | undefined): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

const sortAccessors: Record<WatchlistSortColumn, (quote: Quote | null) => number | null> = {
  price: (quote) => numeric(quote?.price),
  change: (quote) => numeric(quote?.day_change),
  changePct: (quote) => numeric(quote?.day_change_pct),
};

/** Pairs each watchlist item with its quote without changing the saved order. */
export function buildWatchlistRows(
  items: WatchlistItem[],
  quotes?: Map<string, Quote>,
): WatchlistRow[] {
  return items.map((item, originalIndex) => {
    const key = watchlistItemKey(item);
    return {
      item,
      key,
      originalIndex,
      quote: quotes?.get(key) ?? quotes?.get(item.symbol) ?? null,
    };
  });
}

/**
 * Returns a sorted copy of the rows. Rows without a usable value stay at the
 * bottom in both directions, and ties keep the saved watchlist order.
 */
export function sortWatchlistRows(
  rows: WatchlistRow[],
  column: WatchlistSortColumn,
  direction: WatchlistSortDirection,
): WatchlistRow[] {
  const read = sortAccessors[column];
  return [...rows].sort((left, right) => {
    const a = read(left.quote);
    const b = read(right.quote);
    if (a === null || b === null) {
      if (a === b) return left.originalIndex - right.originalIndex;
      return a === null ? 1 : -1;
    }
    const delta = direction === 'asc' ? a - b : b - a;
    return delta === 0 ? left.originalIndex - right.originalIndex : delta;
  });
}

/** First click on a column sorts ascending; later clicks toggle the direction. */
export function nextWatchlistSort(
  current: WatchlistSort | null,
  column: WatchlistSortColumn,
): WatchlistSort {
  if (current?.column === column) {
    return { column, direction: current.direction === 'asc' ? 'desc' : 'asc' };
  }
  return { column, direction: 'asc' };
}
