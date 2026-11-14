import type { Transaction } from '../../types/api';
import {
  cn,
  formatDateTime,
  formatNumber,
  formatSignedFixed,
  toneForNumber,
} from '../../utils/format';
import { quoteTypeLabel, quoteTypeTone } from '../../utils/quotes';
import { Badge } from '../common/Badge';
import { Button } from '../common/Button';
import { EmptyState } from '../common/States';

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

function amountOf(transaction: Transaction): number | null {
  if (transaction.amount !== undefined && transaction.amount !== null) {
    return transaction.amount;
  }
  if (transaction.quantity && transaction.price) {
    return transaction.quantity * transaction.price;
  }
  return null;
}

export function TransactionsTable({
  transactions,
  onDelete,
  deleting,
}: {
  transactions: Transaction[];
  onDelete?: (transaction: Transaction) => void;
  deleting?: number | null;
}) {
  if (transactions.length === 0) {
    return (
      <EmptyState
        title="No Transactions Recorded"
        description="Record a real BUY or SELL amount to build the FIFO ledger."
        icon="portfolio"
      />
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[1120px] border-collapse text-xs">
        <thead>
          <tr className="border-b border-terminal-border text-left text-2xs text-terminal-muted">
            <th className="py-1.5 pr-3 font-medium">Time</th>
            <th className="py-1.5 pr-3 font-medium">Symbol</th>
            <th className="py-1.5 pr-3 font-medium">Exchange</th>
            <th className="py-1.5 pr-3 font-medium">Side</th>
            <th className="py-1.5 pr-3 text-right font-medium">Amount</th>
            <th className="py-1.5 pr-3 text-right font-medium">Quantity</th>
            <th className="py-1.5 pr-3 text-right font-medium">Price</th>
            <th className="py-1.5 pr-3 text-right font-medium">Fees</th>
            <th className="py-1.5 pr-3 text-right font-medium">Realized P&amp;L</th>
            <th className="py-1.5 pr-3 font-medium">Currency</th>
            <th className="py-1.5 pr-3 font-medium">Quote</th>
            <th className="py-1.5 pr-3 font-medium">Notes</th>
            {onDelete ? <th className="py-1.5 text-right font-medium">Action</th> : null}
          </tr>
        </thead>
        <tbody>
          {transactions.map((transaction) => {
            const amount = amountOf(transaction);
            const quoteTitle = [
              transaction.quote_provider || transaction.provider,
              transaction.quote_time ? `Quote ${transaction.quote_time}` : null,
            ]
              .filter(Boolean)
              .join(' · ');
            return (
              <tr key={transaction.id} className="border-b border-terminal-borderSoft last:border-0">
                <td className="num py-1.5 pr-3 text-terminal-muted">
                  {formatDateTime(transaction.trade_time)}
                </td>
                <td className="py-1.5 pr-3">
                  <span className="font-medium text-terminal-text">{transaction.symbol}</span>
                  {transaction.instrument_name || transaction.name ? (
                    <p className="truncate text-2xs text-terminal-muted">
                      {transaction.instrument_name ?? transaction.name}
                    </p>
                  ) : null}
                </td>
                <td className="py-1.5 pr-3 text-terminal-muted">{transaction.exchange ?? '—'}</td>
                <td className="py-1.5 pr-3">
                  <Badge tone={transaction.side === 'BUY' ? 'positive' : 'negative'}>
                    {transaction.side}
                  </Badge>
                </td>
                <td className="num py-1.5 pr-3 text-right text-terminal-text">
                  {formatNumber(amount, 2)}
                </td>
                <td className="num py-1.5 pr-3 text-right text-terminal-text">
                  {formatNumber(transaction.quantity, 8)}
                </td>
                <td className="num py-1.5 pr-3 text-right text-terminal-text">
                  {formatNumber(transaction.price, 4)}
                </td>
                <td className="num py-1.5 pr-3 text-right text-terminal-muted">
                  {formatNumber(transaction.fees, 2)}
                </td>
                <td
                  className={cn(
                    'num py-1.5 pr-3 text-right',
                    transaction.side === 'SELL'
                      ? toneClass(transaction.realised_pnl)
                      : 'text-terminal-muted',
                  )}
                >
                  {transaction.side === 'SELL'
                    ? formatSignedFixed(transaction.realised_pnl ?? null, 2)
                    : '—'}
                </td>
                <td className="py-1.5 pr-3 text-terminal-muted">{transaction.currency}</td>
                <td className="py-1.5 pr-3">
                  <Badge
                    tone={quoteTypeTone(transaction.quote_type, transaction.quote_status)}
                    title={quoteTitle || undefined}
                  >
                    {quoteTypeLabel(transaction.quote_type)}
                  </Badge>
                </td>
                <td className="max-w-[200px] truncate py-1.5 pr-3 text-terminal-muted">
                  {transaction.notes ?? '—'}
                </td>
                {onDelete ? (
                  <td className="py-1.5 text-right">
                    <Button
                      size="sm"
                      variant="danger"
                      icon="trash"
                      loading={deleting === transaction.id}
                      onClick={() => onDelete(transaction)}
                      aria-label={`Delete ${transaction.side} ${transaction.symbol}`}
                    >
                      Delete
                    </Button>
                  </td>
                ) : null}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
