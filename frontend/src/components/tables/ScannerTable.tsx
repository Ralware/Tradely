import { Link } from 'react-router-dom';
import type { ScannerItem } from '../../types/api';
import { analysisPath } from '../../utils/navigation';
import { formatNumber } from '../../utils/format';
import { Badge } from '../common/Badge';
import { EmptyState } from '../common/States';
import { SignalBadge } from '../signals/SignalBadge';

export function ScannerTable({ items }: { items: ScannerItem[] }) {
  if (items.length === 0) {
    return (
      <EmptyState
        title="Nothing to scan yet"
        description="The scanner evaluates the configured daily strategy for each watchlist instrument."
        icon="markets"
      />
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[620px] border-collapse text-xs">
        <thead>
          <tr className="border-b border-terminal-border text-left text-[11px] uppercase tracking-[0.06em] text-terminal-muted">
            <th className="py-2 pr-3 font-medium">Symbol</th>
            <th className="py-2 pr-3 font-medium">Market</th>
            <th className="py-2 pr-3 text-right font-medium">Last close</th>
            <th className="py-2 pr-3 font-medium">Signal</th>
            <th className="py-2 pr-3 font-medium">Data</th>
            <th className="py-2 font-medium">Source</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={`${item.market}:${item.symbol}`} className="border-b border-terminal-borderSoft last:border-0">
              <td className="py-2 pr-3">
                <Link
                  to={analysisPath(item.symbol, item.market)}
                  className="font-medium text-terminal-text hover:text-terminal-accent"
                >
                  {item.symbol}
                </Link>
              </td>
              <td className="py-2 pr-3">
                <Badge>{item.market}</Badge>
              </td>
              <td className="num py-2 pr-3 text-right text-terminal-text">
                {item.last_close === undefined ? '—' : formatNumber(item.last_close, 2)}
              </td>
              <td className="py-2 pr-3">
                <SignalBadge state={item.strategy.state} />
              </td>
              <td className="py-2 pr-3">
                <div className="flex flex-wrap gap-1">
                  {item.is_adjusted === false ? <Badge tone="warning">unadjusted</Badge> : null}
                  {item.is_stale ? <Badge tone="warning">stale</Badge> : null}
                  {item.is_adjusted === true && !item.is_stale ? (
                    <Badge tone="positive">ok</Badge>
                  ) : null}
                </div>
              </td>
              <td className="py-2 text-terminal-muted">
                {item.error ? <span className="text-terminal-red">{item.error}</span> : (item.source ?? '—')}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
