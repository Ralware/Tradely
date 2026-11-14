import type { Position } from '../../types/api';
import { cn, formatNumber, toneForNumber } from '../../utils/format';
import { Badge } from '../common/Badge';
import { EmptyState } from '../common/States';

export function PositionsTable({ positions }: { positions: Position[] }) {
  if (positions.length === 0) {
    return <EmptyState title="No Open Positions" description="Record a BUY transaction." icon="portfolio" />;
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[720px] border-collapse text-xs">
        <thead>
          <tr className="border-b border-terminal-border text-left text-2xs text-terminal-muted">
            <th className="py-1.5 pr-3 font-medium">Symbol</th>
            <th className="py-1.5 pr-3 font-medium">Market</th>
            <th className="py-1.5 pr-3 text-right font-medium">Quantity</th>
            <th className="py-1.5 pr-3 text-right font-medium">Average Cost</th>
            <th className="py-1.5 pr-3 text-right font-medium">Cost Basis</th>
            <th className="py-1.5 pr-3 text-right font-medium">Realised P&amp;L</th>
            <th className="py-1.5 text-right font-medium">Currency</th>
          </tr>
        </thead>
        <tbody>
          {positions.map((position) => {
            const tone = toneForNumber(position.realised_pnl);
            return (
              <tr
                key={`${position.market}:${position.symbol}:${position.currency}`}
                className="border-b border-terminal-borderSoft last:border-0"
              >
                <td className="py-1.5 pr-3 font-medium text-terminal-text">{position.symbol}</td>
                <td className="py-1.5 pr-3">
                  <Badge>{position.market}</Badge>
                </td>
                <td className="num py-1.5 pr-3 text-right text-terminal-text">
                  {formatNumber(position.quantity, 4)}
                </td>
                <td className="num py-1.5 pr-3 text-right text-terminal-text">
                  {formatNumber(position.average_cost, 4)}
                </td>
                <td className="num py-1.5 pr-3 text-right text-terminal-muted">
                  {formatNumber(position.cost_basis, 2)}
                </td>
                <td
                  className={cn(
                    'num py-1.5 pr-3 text-right font-medium',
                    tone === 'positive'
                      ? 'text-terminal-green'
                      : tone === 'negative'
                        ? 'text-terminal-red'
                        : 'text-terminal-muted',
                  )}
                >
                  {formatNumber(position.realised_pnl, 2)}
                </td>
                <td className="py-1.5 text-right text-terminal-muted">{position.currency}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
