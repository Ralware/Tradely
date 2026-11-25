import { useMemo, useState } from 'react';
import { useQuotes } from '../../hooks/useQuotes';
import { useWatchlist } from '../../hooks/useWatchlist';
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
  const watchlist = useWatchlist();
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
      setError(null);
      watchlist.reload();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not remove instrument');
    }
  }

  return (
    <div className="flex h-full flex-col bg-terminal-panel text-terminal-text select-none">
      {/* Header */}
      <div className="flex h-11 shrink-0 items-center justify-between border-b border-terminal-border px-3">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold tracking-wide text-terminal-text">Watchlist</span>
          <span className="inline-flex h-5 min-w-[20px] items-center justify-center rounded border border-terminal-border bg-terminal-panelAlt px-1 text-2xs font-semibold text-terminal-muted">
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
            className="flex h-6 w-6 items-center justify-center rounded text-terminal-muted transition-colors hover:bg-white/[0.05] hover:text-terminal-text"
          >
            <Icon name="refresh" size={12} />
          </button>
          <button
            type="button"
            onClick={() => setAddOpen(!addOpen)}
            title="Add Instrument"
            className={cn(
              'flex h-6 w-6 items-center justify-center rounded text-terminal-muted transition-colors hover:bg-white/[0.05] hover:text-terminal-text',
              addOpen && 'bg-terminal-accentSoft text-terminal-accent',
            )}
          >
            <Icon name="plus" size={13} />
          </button>
          {onClose ? (
            <button
              type="button"
              onClick={onClose}
              title="Close Drawer"
              className="flex h-6 w-6 items-center justify-center rounded text-terminal-muted transition-colors hover:bg-white/[0.05] hover:text-terminal-text"
            >
              <Icon name="close" size={13} />
            </button>
          ) : null}
        </div>
      </div>

      {/* Add Instrument Inline Search */}
      {addOpen ? (
        <div className="border-b border-terminal-border bg-terminal-panel p-2">
          <InstrumentSearch
            autoFocus
            clearOnSelect
            placeholder="Add ticker or pair..."
            onSelect={(instrument) => void handleAdd(instrument)}
            inputClassName="h-7 text-2xs"
            disabled={adding}
          />
          {error ? <p className="mt-1 text-2xs text-terminal-red">{error}</p> : null}
        </div>
      ) : null}

      {error && !addOpen ? (
        <p className="border-b border-terminal-borderSoft px-2.5 py-1 text-2xs text-terminal-red">{error}</p>
      ) : null}

      {/* Watchlist Items */}
      <div className="flex-1 overflow-y-auto divide-y divide-terminal-borderSoft">
        {watchlist.loading && !watchlist.data ? (
          <LoadingPanel className="p-3" label="Loading Watchlist" rows={6} />
        ) : watchlist.error ? (
          <ErrorState className="m-2" message={watchlist.error} onRetry={watchlist.reload} />
        ) : items.length === 0 ? (
          <EmptyState
            className="m-2"
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
                role="button"
                tabIndex={0}
                aria-label={`Open analysis for ${item.symbol}`}
                aria-current={isSelected ? 'true' : undefined}
                onClick={() => onSelectInstrument(item)}
                onKeyDown={(event) => {
                  if (event.target !== event.currentTarget) return;
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    onSelectInstrument(item);
                  }
                }}
                className={cn(
                  'group flex cursor-pointer items-center justify-between py-2 pl-2.5 pr-3 transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-terminal-accent',
                  isSelected
                    ? 'border-l-2 border-terminal-accent bg-terminal-accentSoft'
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
                    aria-label={`Remove ${item.symbol} from watchlist`}
                    className="flex h-5 w-5 items-center justify-center rounded text-terminal-muted opacity-0 transition-all hover:bg-white/[0.1] hover:text-terminal-red group-hover:opacity-100 group-focus-within:opacity-100 focus-visible:opacity-100 max-sm:opacity-100"
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
