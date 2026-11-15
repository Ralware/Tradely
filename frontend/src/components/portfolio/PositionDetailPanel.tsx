import { Link } from 'react-router-dom';
import type { PositionDetailResponse, Transaction } from '../../types/api';
import {
  cn,
  formatDateTime,
  formatNumber,
  formatPercent,
  formatSignedFixed,
  toneForNumber,
} from '../../utils/format';
import { analysisPath } from '../../utils/navigation';
import { Badge } from '../common/Badge';
import { Button } from '../common/Button';
import { EmptyState, ErrorState, LoadingPanel } from '../common/States';
import { PositionChart } from './PositionChart';
import { QuoteBadge } from './QuoteBadge';

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

function Metric({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: string;
}) {
  return (
    <div className="min-w-0 border-l border-terminal-borderSoft pl-2 first:border-l-0 first:pl-0">
      <p className="truncate text-2xs text-terminal-muted">{label}</p>
      <p className={cn('num mt-0.5 truncate text-xs font-semibold', tone ?? 'text-terminal-text')}>
        {value}
      </p>
      {hint ? <p className="mt-0.5 truncate text-2xs text-terminal-muted">{hint}</p> : null}
    </div>
  );
}

function HistoryTable({
  title,
  rows,
  empty,
}: {
  title: string;
  rows: Transaction[];
  empty: string;
}) {
  return (
    <div className="min-w-0">
      <p className="mb-1 text-2xs font-medium tracking-wide text-terminal-muted">{title}</p>
      {rows.length === 0 ? (
        <p className="rounded-sm border border-dashed border-terminal-border px-2 py-3 text-center text-2xs text-terminal-muted">
          {empty}
        </p>
      ) : (
        <div className="max-h-52 overflow-y-auto">
          <table className="w-full min-w-[430px] border-collapse text-2xs">
            <thead>
              <tr className="border-b border-terminal-border text-left text-terminal-muted">
                <th className="py-1 pr-2 font-medium">Time</th>
                <th className="py-1 pr-2 font-medium">Intent</th>
                <th className="py-1 pr-2 text-right font-medium">Amount</th>
                <th className="py-1 pr-2 text-right font-medium">Quantity</th>
                <th className="py-1 pr-2 text-right font-medium">Price</th>
                <th className="py-1 pr-2 text-right font-medium">Fees</th>
                <th className="py-1 text-right font-medium">
                  {title === 'Purchase History' ? 'Unit Cost' : 'Realized P&L'}
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const intent = row.intent ?? row.side;
                return (
                <tr key={row.id} className="border-b border-terminal-borderSoft last:border-0">
                  <td className="num py-1 pr-2 text-terminal-muted">{formatDateTime(row.trade_time)}</td>
                  <td className="py-1 pr-2 text-terminal-muted">
                    {intent === 'SELL_SHORT'
                      ? 'Sell Short'
                      : intent === 'BUY_TO_COVER'
                        ? 'Buy To Cover'
                        : intent === 'SELL'
                          ? 'Sell'
                          : 'Buy'}
                  </td>
                  <td className="num py-1 pr-2 text-right text-terminal-text">
                    {formatNumber(row.amount ?? row.quantity * row.price, 2)}
                  </td>
                  <td className="num py-1 pr-2 text-right text-terminal-text">
                    {formatNumber(row.quantity, 8)}
                  </td>
                  <td className="num py-1 pr-2 text-right text-terminal-text">
                    {formatNumber(row.price, 4)}
                  </td>
                  <td className="num py-1 pr-2 text-right text-terminal-muted">
                    {formatNumber(row.fees, 2)}
                  </td>
                  <td
                    className={cn(
                      'num py-1 text-right font-medium',
                      title === 'Purchase History' ? 'text-terminal-text' : toneClass(row.realised_pnl),
                    )}
                  >
                    {title === 'Purchase History'
                      ? formatNumber(row.unit_cost ?? null, 4)
                      : formatSignedFixed(row.realised_pnl ?? null, 2)}
                  </td>
                </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export function PositionDetailPanel({
  detail,
  loading,
  error,
  onReload,
  onClose,
}: {
  detail: PositionDetailResponse | null;
  loading: boolean;
  error: string | null;
  onReload: () => void;
  onClose: () => void;
}) {
  if (loading && !detail) {
    return <LoadingPanel label="Loading Position Detail" rows={5} />;
  }
  if (error && !detail) {
    return <ErrorState message={error} onRetry={onReload} />;
  }
  if (!detail) {
    return (
      <EmptyState
        title="No Position Selected"
        description="Select a row in Open Positions to inspect its FIFO lots, trade history and price chart."
        icon="portfolio"
      />
    );
  }

  const position = detail.position;
  const totals = detail.totals;
  const isShort = position.position_side === 'SHORT' || position.quantity < 0;
  const shortHistory =
    detail.short_history ??
    detail.transactions.filter(
      (transaction) =>
        transaction.intent === 'SELL_SHORT' || transaction.intent === 'BUY_TO_COVER',
    );
  const chartEntries = isShort
    ? shortHistory.filter((transaction) => transaction.intent === 'SELL_SHORT')
    : detail.purchase_history;
  const chartExits = isShort
    ? shortHistory.filter((transaction) => transaction.intent === 'BUY_TO_COVER')
    : detail.sale_history;
  return (
    <div className="space-y-3">
      <header className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold text-terminal-text">{position.symbol}</h3>
            <Badge tone="accent">{position.exchange}</Badge>
            <Badge>{position.market}</Badge>
            <Badge tone={isShort ? 'negative' : 'positive'}>{isShort ? 'Short' : 'Long'}</Badge>
            <span className="truncate text-2xs text-terminal-muted">{position.name}</span>
          </div>
          <p className="mt-0.5 text-2xs text-terminal-muted">
            {position.provider} · {position.provider_symbol} · {position.currency}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <QuoteBadge quote={position.quote} />
          <Link to={analysisPath(position.symbol, position.market, position.exchange)}>
            <Button size="sm" variant="ghost" icon="external">
              Analysis
            </Button>
          </Link>
          <Button size="sm" icon="refresh" onClick={onReload}>
            Refresh
          </Button>
          <Button size="sm" variant="ghost" onClick={onClose} aria-label="Close Position Detail">
            Close
          </Button>
        </div>
      </header>

      {position.valuation_error ? (
        <p className="text-2xs text-terminal-amber">{position.valuation_error}</p>
      ) : null}

      <div className="grid grid-cols-2 gap-y-2 sm:grid-cols-3 xl:grid-cols-6">
        <Metric
          label="Open Quantity"
          value={formatNumber(position.absolute_quantity ?? Math.abs(position.quantity), 6)}
          hint="Manual Exposure"
        />
        <Metric
          label={isShort ? 'Average Opening Proceeds' : 'Average Cost'}
          value={formatNumber(position.average_cost, 4)}
          hint={isShort ? 'Net Of Opening Fees' : 'Includes Buy Fees'}
        />
        <Metric
          label={isShort ? 'Remaining Proceeds Basis' : 'Remaining Cost Basis'}
          value={formatNumber(position.cost_basis, 2)}
          hint={`${position.lot_count} Open Lots`}
        />
        <Metric
          label="Latest Price"
          value={position.current_price === null ? 'Unavailable' : formatNumber(position.current_price, 4)}
          hint={position.quote ? `${position.quote.market_status}` : undefined}
        />
        <Metric
          label="Market Value"
          value={position.market_value === null ? '—' : formatNumber(position.market_value, 2)}
          hint={position.currency}
        />
        <Metric
          label="Unrealized P&L"
          value={
            position.unrealized_pnl === null
              ? '—'
              : `${formatSignedFixed(position.unrealized_pnl, 2)} (${formatPercent(position.return_pct, 2, true)})`
          }
          tone={toneClass(position.unrealized_pnl)}
          hint="Mark-to-Market"
        />
        <Metric
          label={isShort ? 'Total Covered' : 'Total Bought'}
          value={formatNumber(totals.total_bought, 6)}
          hint={position.currency}
        />
        <Metric
          label={isShort ? 'Total Shorted' : 'Total Sold'}
          value={formatNumber(totals.total_sold, 6)}
          hint={position.currency}
        />
        <Metric
          label="Realized P&L"
          value={formatSignedFixed(totals.realised_pnl, 2)}
          tone={toneClass(totals.realised_pnl)}
          hint="FIFO with Fees"
        />
        <Metric label="Buy Fees" value={formatNumber(totals.buy_fees, 2)} />
        <Metric label="Sell Fees" value={formatNumber(totals.sell_fees, 2)} />
        <Metric label="Total Fees" value={formatNumber(totals.fees_total, 2)} hint="Counted Once" />
      </div>

      <div>
        <div className="mb-1 flex flex-wrap items-center justify-between gap-2">
          <p className="text-2xs font-medium tracking-wide text-terminal-muted">
            Price History and Trade Markers
          </p>
          <p className="text-2xs text-terminal-muted">
            {detail.candle_source ?? 'Provider unavailable'} · Actual Candles Only
          </p>
        </div>
        {detail.candle_error ? (
          <p className="mb-1 text-2xs text-terminal-amber">{detail.candle_error}</p>
        ) : null}
        <PositionChart
          candles={detail.candles}
          purchases={chartEntries}
          sales={chartExits}
          positionSide={isShort ? 'SHORT' : 'LONG'}
          averageCost={position.average_cost}
          currentPrice={position.current_price}
        />
        <div className="mt-1 flex flex-wrap gap-3 text-2xs text-terminal-muted">
          <span className="text-terminal-amber">— {isShort ? 'Average Proceeds' : 'Average Cost'}</span>
          <span className="text-terminal-accent">— Current Price</span>
          <span className="text-terminal-green">▲ {isShort ? 'Cover' : 'Buy'}</span>
          <span className="text-terminal-red">▼ {isShort ? 'Sell Short' : 'Sell'}</span>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
        {isShort ? (
          <HistoryTable title="Short History" rows={shortHistory} empty="No Short Exposure History" />
        ) : (
          <>
            <HistoryTable title="Purchase History" rows={detail.purchase_history} empty="No Purchases Recorded" />
            <HistoryTable title="Sale History" rows={detail.sale_history} empty="No Sales Recorded" />
          </>
        )}
      </div>

      {detail.remaining_lots.length > 0 ? (
        <div>
          <p className="mb-1 text-2xs font-medium tracking-wide text-terminal-muted">
            Remaining FIFO Lots
          </p>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[520px] border-collapse text-2xs">
              <thead>
                <tr className="border-b border-terminal-border text-left text-terminal-muted">
                  <th className="py-1 pr-2 font-medium">Acquired</th>
                  <th className="py-1 pr-2 text-right font-medium">Original Quantity</th>
                  <th className="py-1 pr-2 text-right font-medium">Remaining Quantity</th>
                  <th className="py-1 pr-2 text-right font-medium">
                    {isShort ? 'Unit Proceeds' : 'Unit Cost'}
                  </th>
                  <th className="py-1 text-right font-medium">
                    {isShort ? 'Remaining Proceeds Basis' : 'Remaining Cost Basis'}
                  </th>
                </tr>
              </thead>
              <tbody>
                {detail.remaining_lots.map((lot) => (
                  <tr key={lot.transaction_id} className="border-b border-terminal-borderSoft last:border-0">
                    <td className="num py-1 pr-2 text-terminal-muted">{formatDateTime(lot.acquired_at)}</td>
                    <td className="num py-1 pr-2 text-right text-terminal-text">
                      {formatNumber(lot.original_quantity, 6)}
                    </td>
                    <td className="num py-1 pr-2 text-right text-terminal-text">
                      {formatNumber(lot.remaining_quantity, 6)}
                    </td>
                    <td className="num py-1 pr-2 text-right text-terminal-text">
                      {formatNumber(isShort ? lot.unit_proceeds ?? lot.unit_cost : lot.unit_cost, 4)}
                    </td>
                    <td className="num py-1 text-right text-terminal-text">
                      {formatNumber(lot.remaining_cost_basis, 2)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}
    </div>
  );
}
