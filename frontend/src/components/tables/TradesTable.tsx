import type { BacktestTrade } from '../../types/api';
import { cn, formatDateTime, formatNumber, toneForNumber } from '../../utils/format';
import { EmptyState } from '../common/States';

export function TradesTable({ trades }: { trades: BacktestTrade[] }) {
  if (trades.length === 0) {
    return (
      <EmptyState
        title="No trades in this simulation"
        description="The strategy did not generate a complete entry and exit within the tested history."
        icon="flask"
      />
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[900px] border-collapse text-xs">
        <thead>
          <tr className="border-b border-terminal-border text-left text-[11px] uppercase tracking-[0.06em] text-terminal-muted">
            <th className="py-2 pr-3 font-medium">Signal</th>
            <th className="py-2 pr-3 font-medium">Entry</th>
            <th className="py-2 pr-3 font-medium">Exit</th>
            <th className="py-2 pr-3 text-right font-medium">Entry px</th>
            <th className="py-2 pr-3 text-right font-medium">Exit px</th>
            <th className="py-2 pr-3 text-right font-medium">Qty</th>
            <th className="py-2 pr-3 text-right font-medium">Costs</th>
            <th className="py-2 pr-3 text-right font-medium">Net P&amp;L</th>
            <th className="py-2 font-medium">Reason</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((trade, index) => {
            const tone = toneForNumber(trade.net_pnl);
            return (
              <tr key={`${trade.entry_time}-${index}`} className="border-b border-terminal-borderSoft last:border-0">
                <td className="num py-2 pr-3 text-terminal-muted">{formatDateTime(trade.signal_time)}</td>
                <td className="num py-2 pr-3 text-terminal-muted">{formatDateTime(trade.entry_time)}</td>
                <td className="num py-2 pr-3 text-terminal-muted">{formatDateTime(trade.exit_time)}</td>
                <td className="num py-2 pr-3 text-right text-terminal-text">
                  {formatNumber(trade.entry_price, 2)}
                </td>
                <td className="num py-2 pr-3 text-right text-terminal-text">
                  {formatNumber(trade.exit_price, 2)}
                </td>
                <td className="num py-2 pr-3 text-right text-terminal-muted">
                  {formatNumber(trade.quantity, 0)}
                </td>
                <td className="num py-2 pr-3 text-right text-terminal-muted">
                  {formatNumber(trade.total_costs, 2)}
                </td>
                <td
                  className={cn(
                    'num py-2 pr-3 text-right font-medium',
                    tone === 'positive'
                      ? 'text-terminal-green'
                      : tone === 'negative'
                        ? 'text-terminal-red'
                        : 'text-terminal-muted',
                  )}
                >
                  {formatNumber(trade.net_pnl, 2)}
                </td>
                <td className="py-2 text-terminal-muted">{trade.exit_reason}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
