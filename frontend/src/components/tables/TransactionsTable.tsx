import type { Transaction } from '../../types/api';
import { formatDateTime, formatNumber } from '../../utils/format';
import { Badge } from '../common/Badge';
import { EmptyState } from '../common/States';

export function TransactionsTable({ transactions }: { transactions: Transaction[] }) {
  if (transactions.length === 0) {
    return (
      <EmptyState
        title="No transactions recorded"
        description="This ledger records real trades only. Tradely does not simulate or execute orders."
        icon="portfolio"
      />
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[780px] border-collapse text-xs">
        <thead>
          <tr className="border-b border-terminal-border text-left text-[11px] uppercase tracking-[0.06em] text-terminal-muted">
            <th className="py-2 pr-3 font-medium">Time</th>
            <th className="py-2 pr-3 font-medium">Symbol</th>
            <th className="py-2 pr-3 font-medium">Side</th>
            <th className="py-2 pr-3 text-right font-medium">Quantity</th>
            <th className="py-2 pr-3 text-right font-medium">Price</th>
            <th className="py-2 pr-3 text-right font-medium">Fees</th>
            <th className="py-2 pr-3 font-medium">Currency</th>
            <th className="py-2 font-medium">Notes</th>
          </tr>
        </thead>
        <tbody>
          {transactions.map((transaction) => (
            <tr key={transaction.id} className="border-b border-terminal-borderSoft last:border-0">
              <td className="num py-2 pr-3 text-terminal-muted">
                {formatDateTime(transaction.trade_time)}
              </td>
              <td className="py-2 pr-3 font-medium text-terminal-text">{transaction.symbol}</td>
              <td className="py-2 pr-3">
                <Badge tone={transaction.side === 'BUY' ? 'positive' : 'negative'}>
                  {transaction.side}
                </Badge>
              </td>
              <td className="num py-2 pr-3 text-right text-terminal-text">
                {formatNumber(transaction.quantity, 4)}
              </td>
              <td className="num py-2 pr-3 text-right text-terminal-text">
                {formatNumber(transaction.price, 4)}
              </td>
              <td className="num py-2 pr-3 text-right text-terminal-muted">
                {formatNumber(transaction.fees, 2)}
              </td>
              <td className="py-2 pr-3 text-terminal-muted">{transaction.currency}</td>
              <td className="max-w-[220px] truncate py-2 text-terminal-muted">
                {transaction.notes ?? '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
