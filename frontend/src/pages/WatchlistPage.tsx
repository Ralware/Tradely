import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useApi } from '../hooks/useApi';
import { useQuotes } from '../hooks/useQuotes';
import { marketService } from '../services/marketService';
import { portfolioService } from '../services/portfolioService';
import type { Instrument, SignalState, WatchlistItem } from '../types/api';
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
  const watchlist = useApi((signal) => portfolioService.getWatchlist(signal), []);
  const scanner = useApi((signal) => marketService.getScanner(signal), []);

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

  // Map scanner signals by key and symbol
  const signalsMap = useMemo(() => {
    const map = new Map<string, { state: SignalState; label?: string }>();
    if (!scanner.data?.items) return map;
    for (const item of scanner.data.items) {
      const state = item.strategy.state;
      let label: string | undefined;
      if (state === 'SELL') {
        label = 'Sell · Exit Long';
      } else if (state === 'WAIT') {
        label = '→ Wait';
      } else if (state === 'BUY') {
        label = 'Buy';
      }
      if (item.instrument_id) {
        map.set(item.instrument_id, { state, label });
      }
      map.set(`${item.market}:${item.symbol}`, { state, label });
      map.set(item.symbol, { state, label });
    }
    return map;
  }, [scanner.data]);

  // Fetch 7-day daily sparklines for each instrument
  const sparklineCache = useRef<Map<string, number[]>>(new Map());
  useEffect(() => {
    if (watchlistItems.length === 0) return;
    let cancelled = false;

    async function loadSparklines() {
      const nextMap = new Map(sparklineCache.current);
      const missing = watchlistItems.filter((item) => !nextMap.has(watchlistItemKey(item)));

      if (missing.length > 0) {
        await Promise.all(
          missing.map(async (item) => {
            const key = watchlistItemKey(item);
            try {
              const res = await marketService.getCandles({
                instrumentId: item.instrument_id,
                symbol: item.symbol,
                market: item.market,
                exchange: item.exchange,
                interval: '1d',
                days: 7,
              });
              if (res.candles && res.candles.length > 0) {
                const closes = res.candles.map((c) => c.close);
                nextMap.set(key, closes);
                sparklineCache.current.set(key, closes);
              }
            } catch {
              // Ignore individual failure; Sparkline handles missing data
            }
          }),
        );
      }

      if (!cancelled) {
        setSparklines(new Map(nextMap));
      }
    }

    void loadSparklines();
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
      scanner.reload();
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
      scanner.reload();
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
    scanner.reload();
    refreshQuotes();
    sparklineCache.current.clear();
  }

  return (
    <div className="w-full px-4 py-4 lg:px-6">
      <PageHeader
        title="Watchlist"
        subtitle="Live quotes, rule-based signals and a 7-day trend for every tracked instrument."
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
              className="flex h-7 w-7 items-center justify-center rounded-md border border-terminal-border bg-terminal-panel text-terminal-muted transition-colors hover:bg-white/[0.05] hover:text-terminal-text"
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
            signals={signalsMap}
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
          className="fixed inset-0 z-50 flex items-center justify-center bg-terminal-bg/80 p-4 backdrop-blur-sm"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) setAddModalOpen(false);
          }}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="watchlist-dialog-title"
            className="w-full max-w-md rounded-xl border border-terminal-border bg-terminal-panel p-4 shadow-2xl"
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
                className="-mr-1 -mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-terminal-muted transition-colors hover:bg-white/[0.06] hover:text-terminal-text"
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
