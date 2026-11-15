import { Link } from 'react-router-dom';
import type { Position } from '../../types/api';
import {
  cn,
  formatNumber,
  formatPercent,
  formatSignedFixed,
  formatTime,
  toneForNumber,
} from '../../utils/format';
import { analysisPath } from '../../utils/navigation';
import { formatAge } from '../../utils/quotes';
import { Badge } from '../common/Badge';
import { EmptyState } from '../common/States';
import { QuoteBadge } from '../portfolio/QuoteBadge';

function toneClass(value: number | null | undefined): string {
  const tone = toneForNumber(value);
  if (tone === 'positive') {
    return 'text-terminal-green';
  }
  if (tone === 'negative') {
    return 'text-terminal-red';
  }
  return 'text-terminal-muted';
}

export function PositionsTable({
  positions,
  selectedId,
  onSelect,
}: {
  positions: Position[];
  selectedId?: string | null;
  onSelect?: (position: Position) => void;
}) {
  if (positions.length === 0) {
    return (
      <EmptyState
        title="No Open Positions"
        description="Record a BUY or SELL SHORT intent to open a manual exposure. Closed instruments remain in the ledger."
        icon="portfolio"
      />
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[1180px] border-collapse text-xs">
        <thead>
          <tr className="border-b border-terminal-border text-left text-2xs text-terminal-muted">
            <th className="py-1.5 pr-3 font-medium">Symbol</th>
            <th className="py-1.5 pr-3 font-medium">Exchange</th>
            <th className="py-1.5 pr-3 font-medium">Direction</th>
            <th className="py-1.5 pr-3 text-right font-medium">Quantity</th>
            <th className="py-1.5 pr-3 text-right font-medium">Average Cost / Proceeds</th>
            <th className="py-1.5 pr-3 text-right font-medium">Cost / Proceeds Basis</th>
            <th className="py-1.5 pr-3 text-right font-medium">Current Price</th>
            <th className="py-1.5 pr-3 text-right font-medium">Market Value</th>
            <th className="py-1.5 pr-3 text-right font-medium">Day Change</th>
            <th className="py-1.5 pr-3 text-right font-medium">Unrealized P&amp;L</th>
            <th className="py-1.5 pr-3 text-right font-medium">Return %</th>
            <th className="py-1.5 text-right font-medium">Last Updated</th>
          </tr>
        </thead>
        <tbody>
          {positions.map((position) => {
            const selected = selectedId === position.instrument_id;
            const isShort = position.position_side === 'SHORT' || position.quantity < 0;
            return (
              <tr
                key={position.instrument_id}
                onClick={() => onSelect?.(position)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    onSelect?.(position);
                  }
                }}
                tabIndex={0}
                aria-selected={selected}
                className={cn(
                  'cursor-pointer border-b border-terminal-borderSoft last:border-0 focus:outline-none',
                  selected ? 'bg-black' : 'hover:bg-white/[0.03]',
                )}
                title={position.valuation_error ?? position.name}
              >
                <td className="py-1.5 pr-3">
                  <Link
                    to={analysisPath(position.symbol, position.market, position.exchange)}
                    onClick={(event) => event.stopPropagation()}
                    className="font-medium text-terminal-text hover:text-terminal-accent"
                  >
                    {position.symbol}
                  </Link>
                  <p className="truncate text-2xs text-terminal-muted">
                    {position.name} · {position.currency}
                  </p>
                </td>
                <td className="py-1.5 pr-3">
                  <Badge>{position.exchange}</Badge>
                </td>
                <td className="py-1.5 pr-3">
                  <Badge tone={isShort ? 'negative' : 'positive'}>
                    {isShort ? 'Short' : 'Long'}
                  </Badge>
                </td>
                <td className="num py-1.5 pr-3 text-right text-terminal-text">
                  {formatNumber(position.absolute_quantity ?? Math.abs(position.quantity), 6)}
                </td>
                <td className="num py-1.5 pr-3 text-right text-terminal-text">
                  {formatNumber(position.average_cost, 4)}
                </td>
                <td className="num py-1.5 pr-3 text-right text-terminal-text">
                  {formatNumber(position.cost_basis, 2)}
                </td>
                <td className="num py-1.5 pr-3 text-right text-terminal-text">
                  {position.current_price === null ? '—' : formatNumber(position.current_price, 4)}
                </td>
                <td className="num py-1.5 pr-3 text-right text-terminal-text">
                  {position.market_value === null ? '—' : formatNumber(position.market_value, 2)}
                </td>
                <td
                  className={cn(
                    'num py-1.5 pr-3 text-right',
                    toneClass(position.day_change),
                  )}
                >
                  {position.day_change === null
                    ? '—'
                    : `${formatSignedFixed(position.day_change, 2)} (${formatPercent(position.day_change_pct, 2, true)})`}
                </td>
                <td
                  className={cn(
                    'num py-1.5 pr-3 text-right font-medium',
                    toneClass(position.unrealized_pnl),
                  )}
                >
                  {position.unrealized_pnl === null
                    ? '—'
                    : formatSignedFixed(position.unrealized_pnl, 2)}
                </td>
                <td
                  className={cn(
                    'num py-1.5 pr-3 text-right',
                    toneClass(position.return_pct),
                  )}
                >
                  {formatPercent(position.return_pct, 2, true)}
                </td>
                <td className="py-1.5 text-right">
                  <div className="flex flex-col items-end gap-0.5">
                    <QuoteBadge quote={position.quote} />
                    <span className="text-2xs text-terminal-muted">
                      {position.quote
                        ? `${formatAge(position.quote.age_seconds)} · ${formatTime(position.quote.quote_time)}`
                        : position.valuation_error ?? 'No Quote'}
                    </span>
                  </div>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
