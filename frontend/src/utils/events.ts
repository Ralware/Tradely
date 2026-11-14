export const WATCHLIST_CHANGED_EVENT = 'tradely:watchlist-changed';

/** Tells every mounted watchlist view to refetch after a mutation. */
export function notifyWatchlistChanged(): void {
  window.dispatchEvent(new Event(WATCHLIST_CHANGED_EVENT));
}
