import type { CurrencySummary, PortfolioSummary } from '../../types/api';
import {
  cn,
  formatNumber,
  formatPercent,
  formatSignedFixed,
  toneForNumber,
} from '../../utils/format';
import { formatAge } from '../../utils/quotes';
import { Badge } from '../common/Badge';
import { EmptyState, LoadingPanel } from '../common/States';

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
    <div className="min-w-0">
      <p className="truncate text-2xs text-terminal-muted">{label}</p>
      <p className={cn('num mt-0.5 truncate text-sm font-semibold', tone ?? 'text-terminal-text')}>
        {value}
      </p>
      {hint ? <p className="mt-0.5 truncate text-2xs text-terminal-muted">{hint}</p> : null}
    </div>
  );
}

function CurrencyPanel({ bucket }: { bucket: CurrencySummary }) {
  const currency = bucket.currency;
  return (
    <section className="panel-surface px-3 py-2">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <Badge tone="accent">{currency}</Badge>
          <span className="text-2xs text-terminal-muted">
            {bucket.open_positions} Open · {bucket.closed_positions} Closed
          </span>
          {bucket.unpriced_positions > 0 ? (
            <Badge tone="warning">{bucket.unpriced_positions} Unpriced</Badge>
          ) : null}
        </div>
        <span className="text-2xs text-terminal-muted">
          Quote {bucket.latest_quote_at ? formatAge(
            Math.max(0, (Date.now() - Date.parse(bucket.latest_quote_at)) / 1000),
          ) : '—'}
        </span>
      </header>
      <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-3 xl:grid-cols-5">
        <Metric
          label="Total Invested"
          value={`${currency} ${formatNumber(bucket.total_invested, 2)}`}
          hint={
            bucket.unpriced_invested > 0
              ? `${formatNumber(bucket.unpriced_invested, 2)} Unpriced`
              : 'FIFO Cost Basis'
          }
        />
        <Metric
          label="Current Portfolio Value"
          value={
            bucket.priced_positions > 0
              ? `${currency} ${formatNumber(bucket.market_value, 2)}`
              : 'Unavailable'
          }
          hint={`${bucket.priced_positions} Priced / ${bucket.open_positions} Open`}
        />
        <Metric
          label="Unrealized P&L"
          value={
            bucket.priced_positions > 0
              ? `${formatSignedFixed(bucket.unrealized_pnl, 2)} (${formatPercent(bucket.unrealized_pnl_pct, 2, true)})`
              : 'Unavailable'
          }
          tone={toneClass(bucket.unrealized_pnl)}
          hint="Open Positions Only"
        />
        <Metric
          label="Realized P&L"
          value={formatSignedFixed(bucket.realized_pnl, 2)}
          tone={toneClass(bucket.realized_pnl)}
          hint={`FIFO · Fees ${formatNumber(bucket.transaction_fees, 2)}`}
        />
        <Metric
          label="Total Portfolio P&L"
          value={`${formatSignedFixed(bucket.total_pnl, 2)} (${formatPercent(bucket.total_pnl_pct, 2, true)})`}
          tone={toneClass(bucket.total_pnl)}
          hint="Realized + Unrealized"
        />
      </div>
    </section>
  );
}

export function PortfolioSummaryCards({
  summary,
  loading,
  error,
}: {
  summary: PortfolioSummary | null;
  loading: boolean;
  error: string | null;
}) {
  if (loading && !summary) {
    return <LoadingPanel label="Loading Portfolio Valuation" rows={3} />;
  }
  if (error && !summary) {
    return <EmptyState title="Valuation Unavailable" description={error} icon="alert" />;
  }
  if (!summary || summary.currencies.length === 0) {
    return (
      <EmptyState
        title="No Portfolio Valuation"
        description="Record a BUY transaction to calculate invested value and P&L."
        icon="portfolio"
      />
    );
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-2xs uppercase tracking-wide text-terminal-muted">
          Portfolio Summary by Transaction Currency
        </p>
        <div className="flex items-center gap-2">
          <Badge tone="warning">No Currency Conversion</Badge>
          <span className="text-2xs text-terminal-muted">
            {summary.open_positions} Open · {summary.transactions} Ledger Rows
          </span>
        </div>
      </div>
      {summary.currencies.map((bucket) => (
        <CurrencyPanel key={bucket.currency} bucket={bucket} />
      ))}
      <p className="text-2xs leading-relaxed text-terminal-muted">
        INR, USD and USDT amounts are shown separately. No verified conversion source is configured,
        so totals are never added across currencies.
      </p>
    </div>
  );
}
