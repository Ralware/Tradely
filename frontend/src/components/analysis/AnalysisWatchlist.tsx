import { useMemo, useState } from 'react';
import { useApi } from '../../hooks/useApi';
import { useQuotes } from '../../hooks/useQuotes';
import { portfolioService } from '../../services/portfolioService';
import type { Instrument, WatchlistItem } from '../../types/api';
import { cn, formatNumber, formatPercent, toneForNumber } from '../../utils/format';
import { quoteRefFromWatchlist } from '../../utils/quotes';
import { Icon } from '../common/Icon';
import { EmptyState, ErrorState, LoadingPanel } from '../common/States';
import { InstrumentSearch } from '../instruments/InstrumentSearch';

function toneClass(value: number | null | undefined): string {
  const tone = toneForNumber(value);
  if (tone === 'positive') return 'text-terminal-green';
  if (tone === 'negative') return 'text-terminal-red';
  return 'text-terminal-muted';
}

function itemKey(item: WatchlistItem): string {
  return item.instrument_id ?? `${item.market}:${item.exchange}:${item.symbol}`;
}

export function AnalysisWatchlist({
  selectedInstrumentId,
  onSelectInstrument,
  onClose,
}: {
  selectedInstrumentId: string;
  onSelectInstrument: (item: WatchlistItem) => void;
  onClose?: () => void;
}) {
  const watchlist = useApi((signal) => portfolioService.getWatchlist(signal), []);
  const [addOpen, setAddOpen] = useState(false);
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const items = useMemo(() => watchlist.data?.items ?? [], [watchlist.data]);
  const refs = useMemo(() => items.map(quoteRefFromWatchlist), [items]);
  const { quotes, refresh } = useQuotes(refs);

  async function handleAdd(instrument: Instrument) {
    setAdding(true);
    setError(null);
    try {
      await portfolioService.addWatchlist({
        symbol: instrument.symbol,
        market: instrument.market,
        exchange: instrument.exchange,
        display_name: instrument.name ?? instrument.display_name ?? instrument.symbol,
        instrument_id: instrument.instrument_id,
      });
      setAddOpen(false);
      watchlist.reload();
      // Also automatically select the added instrument
      onSelectInstrument({
        id: 0,
        symbol: instrument.symbol,
        market: instrument.market,
        exchange: instrument.exchange,
        display_name: instrument.name ?? instrument.symbol,
        created_at: new Date().toISOString(),
        instrument_id: instrument.instrument_id,
      });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not add instrument');
    } finally {
      setAdding(false);
    }
  }

  async function handleRemove(e: React.MouseEvent, item: WatchlistItem) {
    e.stopPropagation();
    try {
      await portfolioService.removeWatchlist({
        instrumentId: item.instrument_id,
        symbol: item.symbol,
        market: item.market,
        exchange: item.exchange,
      });
      watchlist.reload();
    } catch {
      // Ignore
    }
  }

  return (
    <div className="flex h-full flex-col border-l border-terminal-border bg-black text-terminal-text select-none">
      {/* Header */}
      <div className="flex h-11 shrink-0 items-center justify-between border-b border-terminal-border px-3">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-white tracking-wide">Watchlist</span>
          <span className="inline-flex h-4 min-w-[16px] items-center justify-center rounded bg-black px-1 text-2xs font-semibold text-terminal-muted">
            {items.length}
          </span>
        </div>

        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => {
              watchlist.reload();
              refresh();
            }}
            title="Refresh Watchlist"
            className="flex h-6 w-6 items-center justify-center rounded text-terminal-muted hover:bg-white/[0.05] hover:text-white transition-colors"
          >
            <Icon name="refresh" size={12} />
          </button>
          <button
            type="button"
            onClick={() => setAddOpen(!addOpen)}
            title="Add Instrument"
            className={cn(
              'flex h-6 w-6 items-center justify-center rounded text-terminal-muted hover:bg-white/[0.05] hover:text-white transition-colors',
              addOpen && 'bg-black text-white',
            )}
          >
            <Icon name="plus" size={13} />
          </button>
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              title="Close Drawer"
              className="flex h-6 w-6 items-center justify-center rounded text-terminal-muted hover:bg-white/[0.05] hover:text-white transition-colors xl:hidden"
            >
              <Icon name="close" size={13} />
            </button>
          )}
        </div>
      </div>

      {/* Add Instrument Inline Search */}
      {addOpen && (
        <div className="border-b border-terminal-border bg-black p-2">
          <InstrumentSearch
            autoFocus
            clearOnSelect
            placeholder="Add ticker or pair..."
            onSelect={(inst) => void handleAdd(inst)}
            inputClassName="h-7 text-2xs"
            disabled={adding}
          />
          {error && <p className="mt-1 text-2xs text-terminal-red">{error}</p>}
        </div>
      )}

      {/* Watchlist Items */}
      <div className="flex-1 overflow-y-auto divide-y divide-terminal-borderSoft">
        {watchlist.loading && !watchlist.data ? (
          <LoadingPanel label="Loading Watchlist" rows={6} />
        ) : watchlist.error ? (
          <ErrorState message={watchlist.error} onRetry={watchlist.reload} />
        ) : items.length === 0 ? (
          <EmptyState
            title="Watchlist Empty"
            description="Add an instrument using the + button."
            icon="portfolio"
          />
        ) : (
          items.map((item) => {
            const key = itemKey(item);
            const isSelected =
              key === selectedInstrumentId ||
              item.symbol === selectedInstrumentId ||
              (item.instrument_id && item.instrument_id === selectedInstrumentId);
            const quote = quotes.get(key);

            return (
              <div
                key={key}
                onClick={() => onSelectInstrument(item)}
                className={cn(
                  'group flex cursor-pointer items-center justify-between px-3 py-2 transition-colors',
                  isSelected
                    ? 'border-l-2 border-terminal-accent bg-black'
                    : 'border-l-2 border-transparent hover:bg-white/[0.03]',
                )}
              >
                <div className="min-w-0 pr-2">
                  <div className="flex items-center gap-1.5">
                    <span
                      className={cn(
                        'text-xs font-semibold tracking-tight',
                        isSelected ? 'text-terminal-accent' : 'text-white',
                      )}
                    >
                      {item.symbol}
                    </span>
                  </div>
                  <p className="truncate text-2xs text-terminal-muted leading-tight mt-0.5 max-w-[130px]">
                    {item.name ?? item.display_name}
                  </p>
                </div>

                <div className="flex items-center gap-2">
                  <div className="text-right">
                    <p className="num text-xs font-medium font-mono text-white">
                      {quote?.price !== null && quote?.price !== undefined
                        ? formatNumber(quote.price, quote.price >= 1000 ? 2 : quote.price >= 1 ? 4 : 6)
                        : '—'}
                    </p>
                    <p className={cn('num text-2xs font-mono font-medium', toneClass(quote?.day_change_pct))}>
                      {formatPercent(quote?.day_change_pct ?? null, 2, true)}
                    </p>
                  </div>

                  <button
                    type="button"
                    onClick={(e) => void handleRemove(e, item)}
                    title="Remove from Watchlist"
                    className="opacity-0 group-hover:opacity-100 flex h-5 w-5 items-center justify-center rounded text-terminal-muted hover:bg-white/[0.1] hover:text-terminal-red transition-all"
                  >
                    <Icon name="close" size={11} />
                  </button>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
