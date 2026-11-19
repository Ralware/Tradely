import { useMemo, useState } from 'react';
import type { Quote, SignalState, WatchlistItem } from '../../types/api';
import { cn, formatPercent, toneForNumber } from '../../utils/format';
import { buildWatchlistRows, sortWatchlistRows } from '../../utils/watchlistSort';
import type { WatchlistSort, WatchlistSortColumn } from '../../utils/watchlistSort';
import { EmptyState } from '../common/States';
import { Sparkline } from '../charts/Sparkline';

// ─── Types ───────────────────────────────────────────────────────────────────

export interface WatchlistTableProps {
  items: WatchlistItem[];
  quotes?: Map<string, Quote>;
  signals?: Map<string, { state: SignalState; label?: string }>;
  sparklines?: Map<string, number[]>;
  sort: WatchlistSort | null;
  onSort: (column: WatchlistSortColumn) => void;
  removing?: string | null;
  onRemove: (item: WatchlistItem) => void;
  onRowClick?: (item: WatchlistItem) => void;
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function toneClass(value: number | null | undefined): string {
  const tone = toneForNumber(value);
  if (tone === 'positive') return 'text-terminal-green';
  if (tone === 'negative') return 'text-terminal-red';
  return 'text-terminal-muted';
}

function formatPrice(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—';
  if (value >= 1000) {
    return value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  if (value >= 1) {
    return value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 4 });
  }
  return value.toLocaleString('en-US', { minimumFractionDigits: 4, maximumFractionDigits: 6 });
}

function formatSignedChange(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—';
  const prefix = value > 0 ? '+' : '';
  if (Math.abs(value) >= 1000) {
    return prefix + value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  if (Math.abs(value) >= 1) {
    return prefix + value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  return prefix + value.toFixed(value === 0 ? 2 : Math.abs(value) < 0.01 ? 4 : 2);
}

// ─── Signal badge ─────────────────────────────────────────────────────────────

interface SignalInfo {
  state: SignalState;
  label?: string;
}

const signalStyle: Record<SignalState, string> = {
  BUY: 'border-[#1f4d43] text-terminal-green bg-black',
  SELL: 'border-[#4d2424] text-terminal-red bg-black',
  SELL_SHORT: 'border-[#4d2424] text-terminal-red bg-black',
  BUY_TO_COVER: 'border-[#1f4d43] text-terminal-green bg-black',
  WAIT: 'border-[#4d3d1f] text-terminal-amber bg-black',
  NO_SIGNAL: 'border-terminal-border text-terminal-muted bg-black',
  INSUFFICIENT_DATA: 'border-terminal-border text-terminal-muted bg-black',
  STALE_DATA: 'border-[#4d3d1f] text-terminal-amber bg-black',
  DATA_QUALITY_ERROR: 'border-[#4d2424] text-terminal-red bg-black',
};

const signalLabel: Record<SignalState, string> = {
  BUY: 'Buy',
  SELL: 'Sell · Exit Long',
  SELL_SHORT: 'Sell Short',
  BUY_TO_COVER: 'Buy To Cover',
  WAIT: '→ Wait',
  NO_SIGNAL: 'No Signal',
  INSUFFICIENT_DATA: 'No Data',
  STALE_DATA: 'Stale',
  DATA_QUALITY_ERROR: 'Data Error',
};

function InlineSignalBadge({ signal }: { signal: SignalInfo }) {
  const style = signalStyle[signal.state] ?? signalStyle.NO_SIGNAL;
  const text = signal.label ?? signalLabel[signal.state] ?? signal.state;
  return (
    <span
      className={`inline-flex items-center rounded-sm border px-2 py-0.5 text-2xs font-medium leading-none tracking-wide ${style}`}
    >
      {text}
    </span>
  );
}

// ─── WatchlistTable ───────────────────────────────────────────────────────────

export function WatchlistTable({
  items,
  quotes,
  signals,
  sparklines,
  sort,
  onSort,
  removing,
  onRemove,
  onRowClick,
}: WatchlistTableProps) {
  const [actionMenuOpen, setActionMenuOpen] = useState<string | null>(null);

  const rows = useMemo(() => {
    const built = buildWatchlistRows(items, quotes);
    return sort ? sortWatchlistRows(built, sort.column, sort.direction) : built;
  }, [items, quotes, sort]);

  function renderSortHeader(column: WatchlistSortColumn, label: string) {
    const active = sort?.column === column;
    const direction = active ? sort.direction : null;
    const ariaSort = direction === 'asc' ? 'ascending' : direction === 'desc' ? 'descending' : 'none';

    return (
      <th className="py-2.5 pr-4 text-right" aria-sort={ariaSort}>
        <button
          type="button"
          onClick={() => onSort(column)}
          className={cn(
            'inline-flex cursor-pointer items-center gap-1 transition-colors hover:text-white',
            active ? 'text-white' : 'text-terminal-muted',
          )}
        >
          {label}
          <span aria-hidden="true" className="inline-block w-3 text-center">
            {direction === 'asc' ? '↑' : direction === 'desc' ? '↓' : '⇅'}
          </span>
        </button>
      </th>
    );
  }

  if (items.length === 0) {
    return (
      <EmptyState
        title="Watchlist Empty"
        description="Add an instrument to get started."
        icon="portfolio"
      />
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[780px] border-collapse text-xs">
        <thead>
          <tr className="border-b border-terminal-border text-left text-2xs font-medium text-terminal-muted select-none">
            <th className="w-10 py-2.5 pl-3 pr-2 text-left">#</th>
            <th className="py-2.5 pr-4">Symbol ⇅</th>
            {renderSortHeader('price', 'Last')}
            {renderSortHeader('change', 'Change')}
            {renderSortHeader('changePct', 'Chg%')}
            <th className="py-2.5 pr-4 text-center">Signal</th>
            <th className="w-32 py-2.5 pr-4 text-center">Chart (7D)</th>
            <th className="w-10 py-2.5 pr-3 text-right">···</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-terminal-borderSoft">
          {rows.map(({ item, key, quote }, index) => {
            const signal = signals?.get(key) ?? signals?.get(item.symbol) ?? null;
            const sparkData = sparklines?.get(key) ?? [];
            const isRemoving = removing === key;
            const isMenuOpen = actionMenuOpen === key;

            return (
              <tr
                key={key}
                className="cursor-pointer transition-colors hover:bg-white/[0.03]"
                onClick={() => onRowClick?.(item)}
              >
                {/* # */}
                <td className="num py-3 pl-3 pr-2 text-left font-mono text-2xs text-terminal-muted">
                  {index + 1}
                </td>

                {/* Symbol */}
                <td className="py-3 pr-4">
                  <div className="font-semibold text-white tracking-tight leading-tight">
                    {item.symbol}
                  </div>
                  <p className="max-w-[180px] truncate text-2xs text-terminal-muted leading-tight mt-0.5">
                    {item.name ?? item.display_name}
                  </p>
                </td>

                {/* Last */}
                <td className="num py-3 pr-4 text-right font-mono font-medium text-white">
                  {formatPrice(quote?.price)}
                  {quote?.currency ? (
                    <span className="ml-1 text-2xs font-normal text-terminal-muted">{quote.currency}</span>
                  ) : null}
                </td>

                {/* Change */}
                <td className={`num py-3 pr-4 text-right font-mono font-medium ${toneClass(quote?.day_change)}`}>
                  {formatSignedChange(quote?.day_change)}
                </td>

                {/* Chg% */}
                <td className={`num py-3 pr-4 text-right font-mono font-medium ${toneClass(quote?.day_change_pct)}`}>
                  {formatPercent(quote?.day_change_pct ?? null, 2, true)}
                </td>

                {/* Signal */}
                <td className="py-3 pr-4 text-center">
                  {signal ? (
                    <InlineSignalBadge signal={signal} />
                  ) : (
                    <span className="text-2xs text-terminal-muted">—</span>
                  )}
                </td>

                {/* Chart 7D */}
                <td
                  className="py-3 pr-4"
                  onClick={(e) => e.stopPropagation()}
                >
                  <div className="w-28 h-9 mx-auto">
                    <Sparkline values={sparkData} height={36} className="w-full" />
                  </div>
                </td>

                {/* Actions */}
                <td
                  className="relative py-3 pr-3 text-right"
                  onClick={(e) => e.stopPropagation()}
                >
                  <button
                    type="button"
                    onClick={() => setActionMenuOpen(isMenuOpen ? null : key)}
                    title="Actions"
                    disabled={isRemoving}
                    className="flex h-6 w-6 items-center justify-center rounded text-terminal-muted hover:bg-white/[0.08] hover:text-white transition-colors"
                  >
                    {isRemoving ? (
                      <span className="text-2xs animate-pulse">…</span>
                    ) : (
                      <span className="text-sm font-bold leading-none">···</span>
                    )}
                  </button>

                  {/* Dropdown Action Menu */}
                  {isMenuOpen ? (
                    <>
                      <div
                        className="fixed inset-0 z-30"
                        onClick={() => setActionMenuOpen(null)}
                      />
                      <div className="absolute right-2 top-8 z-40 w-36 rounded-sm border border-terminal-border bg-terminal-panelAlt py-1 shadow-xl">
                        <button
                          type="button"
                          onClick={() => {
                            setActionMenuOpen(null);
                            onRowClick?.(item);
                          }}
                          className="flex w-full items-center px-3 py-1.5 text-left text-xs text-terminal-text hover:bg-white/[0.06]"
                        >
                          View Analysis
                        </button>
                        <button
                          type="button"
                          onClick={() => {
                            setActionMenuOpen(null);
                            onRemove(item);
                          }}
                          className="flex w-full items-center px-3 py-1.5 text-left text-xs text-terminal-red hover:bg-white/[0.06]"
                        >
                          Remove
                        </button>
                      </div>
                    </>
                  ) : null}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
