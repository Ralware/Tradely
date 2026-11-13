import { Link } from 'react-router-dom';
import type { WatchlistItem } from '../../types/api';
import { analysisPath } from '../../utils/navigation';
import { formatDate } from '../../utils/format';
import { Badge } from '../common/Badge';
import { Button } from '../common/Button';
import { EmptyState } from '../common/States';

export function WatchlistTable({
  items,
  onRemove,
  removing,
}: {
  items: WatchlistItem[];
  onRemove: (item: WatchlistItem) => void;
  removing: string | null;
}) {
  if (items.length === 0) {
    return (
      <EmptyState
        title="Watchlist is empty"
        description="Add an instrument to track it in the daily scanner and open its analysis page."
        icon="portfolio"
      />
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[420px] border-collapse text-xs">
        <thead>
          <tr className="border-b border-terminal-border text-left text-[11px] uppercase tracking-[0.06em] text-terminal-muted">
            <th className="py-2 pr-3 font-medium">Symbol</th>
            <th className="py-2 pr-3 font-medium">Market</th>
            <th className="py-2 pr-3 font-medium">Added</th>
            <th className="py-2 text-right font-medium">Action</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => {
            const key = `${item.market}:${item.symbol}:${item.exchange}`;
            return (
              <tr key={key} className="border-b border-terminal-borderSoft last:border-0">
                <td className="py-2 pr-3">
                  <Link
                    to={analysisPath(item.symbol, item.market, item.exchange)}
                    className="font-medium text-terminal-text hover:text-terminal-accent"
                  >
                    {item.symbol}
                  </Link>
                  {item.exchange ? (
                    <span className="ml-1.5 text-[10px] text-terminal-muted">{item.exchange}</span>
                  ) : null}
                </td>
                <td className="py-2 pr-3">
                  <Badge>{item.market}</Badge>
                </td>
                <td className="num py-2 pr-3 text-terminal-muted">{formatDate(item.created_at)}</td>
                <td className="py-2 text-right">
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
