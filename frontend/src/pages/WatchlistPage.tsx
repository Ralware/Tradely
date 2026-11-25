import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuotes } from '../hooks/useQuotes';
import { useWatchlist } from '../hooks/useWatchlist';
import { portfolioService } from '../services/portfolioService';
import { sparklineService } from '../services/sparklineService';
import type { Instrument, WatchlistItem } from '../types/api';
import { instrumentPath } from '../utils/navigation';
import { quoteRefFromWatchlist } from '../utils/quotes';
import { nextWatchlistSort, watchlistItemKey } from '../utils/watchlistSort';
import type { WatchlistSort } from '../utils/watchlistSort';
import { Button } from '../components/common/Button';
import { Icon } from '../components/common/Icon';
import { PageHeader } from '../components/common/PageHeader';
import { ErrorState, LoadingPanel, Notice } from '../components/common/States';
import { WatchlistTable } from '../components/tables/WatchlistTable';
import { InstrumentSearch } from '../components/instruments/InstrumentSearch';

export function WatchlistPage() {
  const navigate = useNavigate();
  const watchlist = useWatchlist();

  const [sparklines, setSparklines] = useState<Map<string, number[]>>(new Map());
  const [removing, setRemoving] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [addModalOpen, setAddModalOpen] = useState(false);
  const [addingError, setAddingError] = useState<string | null>(null);
  const [watchlistSort, setWatchlistSort] = useState<WatchlistSort | null>(null);

  useEffect(() => {
    if (!addModalOpen) return undefined;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') setAddModalOpen(false);
    }
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [addModalOpen]);

  const watchlistItems = useMemo(() => watchlist.data?.items ?? [], [watchlist.data]);
  const watchlistRefs = useMemo(
    () => watchlistItems.map(quoteRefFromWatchlist),
    [watchlistItems],
  );
  const { quotes: watchlistQuotes, refresh: refreshQuotes } = useQuotes(watchlistRefs);

  // 24-hour hourly sparklines are cached outside React, so revisiting the page
  // reuses the series instead of re-requesting candles for every instrument.
  useEffect(() => {
    sparklineService.prune(watchlistItems);
    if (watchlistItems.length === 0) {
      setSparklines(new Map());
      return undefined;
    }
    let cancelled = false;
    const cached = sparklineService.getSnapshot(watchlistItems);
    if (cached.size > 0) {
      setSparklines(cached);
    }
    void sparklineService.loadMany(watchlistItems).then((snapshot) => {
      if (!cancelled) setSparklines(snapshot);
    });
    return () => {
      cancelled = true;
    };
  }, [watchlistItems]);

  async function handleRemove(item: WatchlistItem) {
    setActionError(null);
    const key = watchlistItemKey(item);
    setRemoving(key);
    try {
      await portfolioService.removeWatchlist({
        instrumentId: item.instrument_id,
        symbol: item.symbol,
        market: item.market,
        exchange: item.exchange,
      });
      watchlist.reload();
    } catch (caught) {
      setActionError(caught instanceof Error ? caught.message : 'Could not remove instrument');
    } finally {
      setRemoving(null);
    }
  }

  async function handleAdd(instrument: Instrument) {
    setAddingError(null);
    try {
      await portfolioService.addWatchlist({
        symbol: instrument.symbol,
        market: instrument.market,
        exchange: instrument.exchange,
        display_name: instrument.name ?? instrument.display_name ?? instrument.symbol,
        instrument_id: instrument.instrument_id,
      });
      setAddModalOpen(false);
      watchlist.reload();
    } catch (caught) {
      setAddingError(caught instanceof Error ? caught.message : 'Could not add instrument');
    }
  }

  function handleRowClick(item: WatchlistItem) {
    if (item.instrument_id) {
      navigate(instrumentPath({ instrument_id: item.instrument_id, market: item.market }));
    } else {
      navigate(instrumentPath({ instrument_id: `${item.market}:${item.exchange}:${item.symbol}`, market: item.market }));
    }
  }

  function handleRefreshAll() {
    watchlist.reload();
    refreshQuotes();
    sparklineService.invalidate();
    void sparklineService
      .loadMany(watchlistItems, { force: true })
      .then((snapshot) => setSparklines(snapshot));
  }

  return (
    <div className="app-page">
      <PageHeader
        title="Watchlist"
        subtitle="Live quotes and a 24-hour trend for every tracked instrument."
        meta={
          <span className="inline-flex h-5 min-w-[20px] items-center justify-center rounded border border-terminal-border bg-terminal-panelAlt px-1.5 text-2xs font-semibold text-terminal-muted">
            {watchlistItems.length} {watchlistItems.length === 1 ? 'instrument' : 'instruments'}
          </span>
        }
        actions={
          <>
            <button
              type="button"
              onClick={handleRefreshAll}
              aria-label="Refresh watchlist data"
              title="Refresh watchlist data"
              className="flex h-7 w-7 items-center justify-center rounded-md border border-terminal-border bg-terminal-panel text-terminal-muted transition-colors hover:bg-terminal-hover hover:text-terminal-text"
            >
              <Icon name="refresh" size={14} />
            </button>

            <Button
              size="sm"
              variant="secondary"
              icon="plus"
              onClick={() => {
                setAddingError(null);
                setAddModalOpen(true);
              }}
            >
              Add Instrument
            </Button>
          </>
        }
      />

      {actionError ? (
        <Notice tone="negative" className="mb-3">
          {actionError}
        </Notice>
      ) : null}

      {/* Full-width unified Watchlist table */}
      <div className="panel-surface w-full overflow-hidden">
        {watchlist.loading && !watchlist.data ? (
          <LoadingPanel className="p-3" label="Loading Watchlist" rows={8} />
        ) : watchlist.error ? (
          <ErrorState className="m-3" message={watchlist.error} onRetry={watchlist.reload} />
        ) : (
          <WatchlistTable
            items={watchlistItems}
            quotes={watchlistQuotes}
            sparklines={sparklines}
            sort={watchlistSort}
            onSort={(column) => setWatchlistSort((current) => nextWatchlistSort(current, column))}
            removing={removing}
            onRemove={(item) => void handleRemove(item)}
            onRowClick={handleRowClick}
          />
        )}
      </div>

      {/* Add Instrument Modal */}
      {addModalOpen ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-terminal-bg/90 p-4"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setAddModalOpen(false);
          }}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="watchlist-dialog-title"
            className="w-full max-w-md rounded border border-terminal-border bg-terminal-panel p-4"
          >
            <div className="mb-3 flex items-start justify-between gap-3 border-b border-terminal-border pb-2.5">
              <div>
                <h3 id="watchlist-dialog-title" className="text-sm font-semibold text-terminal-text">
                  Add to Watchlist
                </h3>
                <p className="mt-0.5 text-2xs text-terminal-muted">
                  Search across Indian stocks, US equities, and crypto pairs
                </p>
              </div>
              <button
                type="button"
                onClick={() => setAddModalOpen(false)}
                className="-mr-1 -mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-terminal-muted transition-colors hover:bg-terminal-hover hover:text-terminal-text"
                aria-label="Close"
              >
                <Icon name="close" size={14} />
              </button>
            </div>

            {addingError ? (
              <Notice tone="negative" className="mb-3">
                {addingError}
              </Notice>
            ) : null}

            <div className="mt-2">
              <InstrumentSearch
                autoFocus
                placeholder="Enter ticker (e.g. AAPL, RELIANCE, BTCUSDT) or company"
                onSelect={(instrument) => void handleAdd(instrument)}
              />
            </div>

            <div className="mt-4 flex justify-end">
              <Button size="sm" variant="ghost" onClick={() => setAddModalOpen(false)}>
                Cancel
              </Button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
