import { Link } from 'react-router-dom';
import type { Quote, WatchlistItem } from '../../types/api';
import { analysisPath } from '../../utils/navigation';
import { formatDate, formatNumber, formatPercent, toneForNumber } from '../../utils/format';
import { Badge } from '../common/Badge';
import { Button } from '../common/Button';
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

export function WatchlistTable({
  items,
  quotes,
  onRemove,
  removing,
}: {
  items: WatchlistItem[];
  quotes?: Map<string, Quote>;
  onRemove: (item: WatchlistItem) => void;
  removing: string | null;
}) {
  if (items.length === 0) {
    return <EmptyState title="Watchlist Empty" description="Add an instrument to track it." icon="portfolio" />;
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[680px] border-collapse text-xs">
        <thead>
          <tr className="border-b border-terminal-border text-left text-2xs text-terminal-muted">
            <th className="py-1.5 pr-3 font-medium">Symbol</th>
            <th className="py-1.5 pr-3 font-medium">Market</th>
            <th className="py-1.5 pr-3 text-right font-medium">Last</th>
            <th className="py-1.5 pr-3 text-right font-medium">Change %</th>
            <th className="py-1.5 pr-3 font-medium">Quote</th>
            <th className="py-1.5 pr-3 font-medium">Added</th>
            <th className="py-1.5 text-right font-medium">Action</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => {
            const key = item.instrument_id ?? `${item.market}:${item.exchange}:${item.symbol}`;
            const quote = quotes?.get(key) ?? null;
            return (
              <tr key={key} className="border-b border-terminal-borderSoft last:border-0">
                <td className="py-1.5 pr-3">
                  <div className="flex items-center gap-1.5">
                    <Link
                      to={analysisPath(item.symbol, item.market, item.exchange)}
                      className="font-medium text-terminal-text hover:text-terminal-accent"
                    >
                      {item.symbol}
                    </Link>
                    {item.is_held ? <Badge tone="accent">Held</Badge> : null}
                  </div>
                  <p className="truncate text-2xs text-terminal-muted">
                    {item.name ?? item.display_name} · {item.exchange}
                    {item.held_quantity ? ` · ${formatNumber(item.held_quantity, 4)} Held` : ''}
                  </p>
                </td>
                <td className="py-1.5 pr-3">
                  <Badge>{item.market}</Badge>
                </td>
                <td className="num py-1.5 pr-3 text-right text-terminal-text">
                  {formatNumber(quote?.price ?? null, 4)}
                </td>
                <td className={`num py-1.5 pr-3 text-right ${toneClass(quote?.day_change_pct)}`}>
                  {formatPercent(quote?.day_change_pct ?? null, 2, true)}
                </td>
                <td className="py-1.5 pr-3">
                  <QuoteBadge quote={quote} />
                </td>
                <td className="num py-1.5 pr-3 text-terminal-muted">{formatDate(item.created_at)}</td>
                <td className="py-1.5 text-right">
                  <Button
                    size="sm"
                    variant="danger"
                    icon="trash"
                    loading={removing === key}
                    onClick={() => onRemove(item)}
                  >
                    Remove
                  </Button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
