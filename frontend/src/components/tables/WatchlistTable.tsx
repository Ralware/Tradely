import { useEffect, useMemo, useState } from 'react';
import type { MouseEvent } from 'react';
import type { Quote, WatchlistItem } from '../../types/api';
import { cn, formatPercent, toneForNumber } from '../../utils/format';
import {
  buildWatchlistRows,
  sortWatchlistRows,
} from '../../utils/watchlistSort';
import type {
  WatchlistSort,
  WatchlistSortColumn,
} from '../../utils/watchlistSort';
import { Icon } from '../common/Icon';
import { EmptyState } from '../common/States';
import { Sparkline } from '../charts/Sparkline';

// ─── Types ───────────────────────────────────────────────────────────────────

export interface WatchlistTableProps {
  items: WatchlistItem[];
  quotes?: Map<string, Quote>;
  sparklines?: Map<string, number[]>;
  sort: WatchlistSort | null;
  onSort: (column: WatchlistSortColumn) => void;
  removing?: string | null;
  onRemove: (item: WatchlistItem) => void;
  onRowClick?: (item: WatchlistItem) => void;
}

interface ActionMenuState {
  key: string;
  top: number;
  left: number;
}

const MENU_WIDTH = 168;
const MENU_HEIGHT = 76;

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
    return value.toLocaleString('en-US', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  }
  if (value >= 1) {
    return value.toLocaleString('en-US', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 4,
    });
  }
  return value.toLocaleString('en-US', {
    minimumFractionDigits: 4,
    maximumFractionDigits: 6,
  });
}

function formatSignedChange(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—';
  const prefix = value > 0 ? '+' : '';
  if (Math.abs(value) >= 1) {
    return (
      prefix +
      value.toLocaleString('en-US', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      })
    );
  }
  return (
    prefix + value.toFixed(value === 0 ? 2 : Math.abs(value) < 0.01 ? 4 : 2)
  );
}

// ─── WatchlistTable ───────────────────────────────────────────────────────────

export function WatchlistTable({
  items,
  quotes,
  sparklines,
  sort,
  onSort,
  removing,
  onRemove,
  onRowClick,
}: WatchlistTableProps) {
  const [menu, setMenu] = useState<ActionMenuState | null>(null);

  const rows = useMemo(() => {
    const built = buildWatchlistRows(items, quotes);
    return sort ? sortWatchlistRows(built, sort.column, sort.direction) : built;
  }, [items, quotes, sort]);

  const menuRow = menu ? rows.find((row) => row.key === menu.key) ?? null : null;

  useEffect(() => {
    if (!menu) return undefined;
    const dismiss = () => setMenu(null);
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') dismiss();
    }
    window.addEventListener('keydown', onKey);
    window.addEventListener('resize', dismiss);
    return () => {
      window.removeEventListener('keydown', onKey);
      window.removeEventListener('resize', dismiss);
    };
  }, [menu]);

  function toggleMenu(event: MouseEvent<HTMLButtonElement>, key: string) {
    event.stopPropagation();
    if (menu?.key === key) {
      setMenu(null);
      return;
    }
    const rect = event.currentTarget.getBoundingClientRect();
    const left = Math.max(
      8,
      Math.min(rect.right - MENU_WIDTH, window.innerWidth - MENU_WIDTH - 8),
    );
    const below = rect.bottom + 4;
    const top =
      below + MENU_HEIGHT > window.innerHeight - 8
        ? Math.max(8, rect.top - MENU_HEIGHT - 4)
        : below;
    setMenu({ key, top, left });
  }

  function renderSortHeader(column: WatchlistSortColumn, label: string) {
    const active = sort?.column === column;
    const direction = active ? sort.direction : null;
    const ariaSort =
      direction === 'asc'
        ? 'ascending'
        : direction === 'desc'
          ? 'descending'
          : 'none';

    return (
      <th className="py-2.5 pr-4 text-right" aria-sort={ariaSort}>
        <button
          type="button"
          onClick={() => {
            setMenu(null);
            onSort(column);
          }}
          className={cn(
            'inline-flex items-center gap-1 rounded px-1 py-0.5 transition-colors hover:text-white focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-terminal-accent',
            active ? 'text-terminal-text' : 'text-terminal-muted',
          )}
        >
          {label}
          <Icon
            name={direction === 'asc' ? 'chevronUp' : direction === 'desc' ? 'chevronDown' : 'sort'}
            size={11}
            className={active ? 'text-terminal-accent' : 'text-terminal-muted/60'}
          />
        </button>
      </th>
    );
  }

  if (items.length === 0) {
    return (
      <EmptyState
        className="m-3"
        title="Watchlist Empty"
        description="Add an instrument to get started."
        icon="portfolio"
      />
    );
  }

  return (
    <>
      <div
        className="overflow-x-auto"
        onScrollCapture={() => setMenu(null)}
      >
        <table className="w-full min-w-[780px] table-fixed border-collapse text-xs">
          <colgroup>
            <col className="w-10" />
            <col className="w-[32%]" />
            <col className="w-[16%]" />
            <col className="w-[14%]" />
            <col className="w-[14%]" />
            <col className="w-36" />
            <col className="w-10" />
          </colgroup>
          <thead>
            <tr className="select-none border-b border-terminal-border text-left text-2xs font-medium text-terminal-muted">
              <th className="w-10 py-2.5 pl-3 pr-2 text-left">#</th>
              <th className="py-2.5 pr-4">Symbol</th>
              {renderSortHeader('price', 'Last')}
              {renderSortHeader('change', '24Hr Change')}
              {renderSortHeader('changePct', '24Hr %')}
              <th className="w-32 py-2.5 pr-4 text-center">Chart (24Hr)</th>
              <th className="w-10 py-2.5 pr-3 text-right">
                <span className="sr-only">Actions</span>
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-terminal-borderSoft">
            {rows.map(({ item, key, quote }, index) => {
              const sparkData = sparklines?.get(key) ?? [];
              const isRemoving = removing === key;

              return (
                <tr
                  key={key}
                  tabIndex={0}
                  aria-label={`Open analysis for ${item.symbol}`}
                  onKeyDown={(event) => {
                    if (event.target !== event.currentTarget) return;
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault();
                      onRowClick?.(item);
                    }
                  }}
                  className="cursor-pointer transition-colors hover:bg-white/[0.035] focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-terminal-accent"
                  onClick={() => onRowClick?.(item)}
                >
                  <td className="num py-3 pl-3 pr-2 text-left font-mono text-2xs text-terminal-muted">
                    {index + 1}
                  </td>

                  <td className="py-3 pr-4">
                    <div className="font-semibold leading-tight tracking-tight text-terminal-text">
                      {item.symbol}
                    </div>
                    <p className="mt-0.5 max-w-[180px] truncate text-2xs leading-tight text-terminal-muted">
                      {item.name ?? item.display_name}
                    </p>
                  </td>

                  <td className="num py-3 pr-4 text-right font-mono font-medium text-terminal-text">
                    {formatPrice(quote?.price)}
                    {quote?.currency ? (
                      <span className="ml-1 text-2xs font-normal text-terminal-muted">
                        {quote.currency}
                      </span>
                    ) : null}
                  </td>

                  <td
                    className={`num py-3 pr-4 text-right font-mono font-medium ${toneClass(quote?.day_change)}`}
                  >
                    {formatSignedChange(quote?.day_change)}
                  </td>

                  <td
                    className={`num py-3 pr-4 text-right font-mono font-medium ${toneClass(quote?.day_change_pct)}`}
                  >
                    {formatPercent(quote?.day_change_pct ?? null, 2, true)}
                  </td>

                  <td className="py-3 pr-4" onClick={(event) => event.stopPropagation()}>
                    <div className="mx-auto h-9 w-28">
                      <Sparkline
                        values={sparkData}
                        height={36}
                        className="w-full"
                      />
                    </div>
                  </td>

                  <td
                    className="py-3 pr-3 text-right"
                    onClick={(event) => event.stopPropagation()}
                  >
                    <button
                      type="button"
                      onClick={(event) => toggleMenu(event, key)}
                      aria-label={`Actions for ${item.symbol}`}
                      aria-haspopup="menu"
                      aria-expanded={menu?.key === key}
                      disabled={isRemoving}
                      className="inline-flex h-6 w-6 items-center justify-center rounded text-terminal-muted transition-colors hover:bg-white/[0.08] hover:text-terminal-text"
                    >
                      {isRemoving ? (
                        <span className="animate-pulse text-2xs">…</span>
                      ) : (
                        <Icon name="more" size={16} />
                      )}
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {menu && menuRow ? (
        <>
          <div
            className="fixed inset-0 z-40"
            onClick={() => setMenu(null)}
            aria-hidden="true"
          />
          <div
            role="menu"
            style={{ position: 'fixed', top: menu.top, left: menu.left, width: MENU_WIDTH }}
            className="z-50 overflow-hidden rounded-md border border-terminal-border bg-terminal-panelAlt py-1 shadow-xl"
          >
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setMenu(null);
                onRowClick?.(menuRow.item);
              }}
              className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-xs text-terminal-text transition-colors hover:bg-white/[0.06]"
            >
              <Icon name="chart" size={12} />
              View Analysis
            </button>
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setMenu(null);
                onRemove(menuRow.item);
              }}
              className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left text-xs text-terminal-red transition-colors hover:bg-white/[0.06]"
            >
              <Icon name="trash" size={12} />
              Remove
            </button>
          </div>
        </>
      ) : null}
    </>
  );
}
