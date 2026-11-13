import { useEffect, useState } from 'react';
import { useApi } from '../../hooks/useApi';
import { analysisService } from '../../services/analysisService';
import type { FundamentalValue, Market, StatementPayload } from '../../types/api';
import { formatCompact, formatNumber, titleCase } from '../../utils/format';
import { Button } from '../common/Button';
import { Card } from '../common/Card';
import { EmptyState, ErrorState, LoadingPanel, Notice } from '../common/States';

const profileFields = [
  'longName',
  'sector',
  'industry',
  'exchange',
  'currency',
  'marketCap',
  'trailingPE',
  'forwardPE',
  'priceToBook',
  'dividendYield',
  'beta',
  'returnOnEquity',
  'profitMargins',
  'debtToEquity',
  'revenueGrowth',
  'earningsGrowth',
  'fiftyTwoWeekHigh',
  'fiftyTwoWeekLow',
  'fullTimeEmployees',
];

function displayValue(key: string, value: FundamentalValue): string {
  if (value === null) {
    return '—';
  }
  if (typeof value === 'boolean') {
    return value ? 'Yes' : 'No';
  }
  if (typeof value === 'number') {
    if (key === 'marketCap') {
      return formatCompact(value);
    }
    if (key === 'fullTimeEmployees') {
      return formatNumber(value, 0);
    }
    return formatNumber(value, 4);
  }
  return value;
}

function StatementTable({ title, payload }: { title: string; payload: StatementPayload }) {
  if (payload.rows.length === 0) {
    return (
      <div>
        <p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.1em] text-terminal-muted">
          {title}
        </p>
        <p className="text-xs text-terminal-muted">Not supplied by the provider.</p>
      </div>
    );
  }

  return (
    <div>
      <p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.1em] text-terminal-muted">
        {title}
      </p>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[420px] border-collapse text-[11px]">
          <thead>
            <tr className="border-b border-terminal-border text-left text-terminal-muted">
              <th className="py-1.5 pr-2 font-medium">Metric</th>
              {payload.periods.map((period) => (
                <th key={period} className="py-1.5 pr-2 text-right font-medium">
                  {period.slice(0, 10)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {payload.rows.map((row) => (
              <tr key={row.metric} className="border-b border-terminal-borderSoft last:border-0">
                <td className="py-1.5 pr-2 text-terminal-muted">{row.metric}</td>
                {row.values.map((value, index) => (
                  <td key={`${row.metric}-${index}`} className="num py-1.5 pr-2 text-right text-terminal-text">
                    {typeof value === 'number' ? formatCompact(value) : (value ?? '—')}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function FundamentalsPanel({
  symbol,
  market,
  exchange,
}: {
  symbol: string;
  market: Market;
  exchange: string | null;
}) {
  const [requested, setRequested] = useState(false);
  const fundamentals = useApi(
    (signal) => analysisService.getFundamentals({ symbol, market, exchange }, signal),
    [symbol, market, exchange],
    { enabled: requested },
  );

  useEffect(() => {
    setRequested(false);
  }, [symbol, market, exchange]);

  return (
    <Card
      title="Fundamentals"
      subtitle="Best-effort Yahoo Finance profile and quarterly statements. Verify material figures against issuer filings."
      actions={
        <Button size="sm" loading={fundamentals.loading} onClick={() => setRequested(true)}>
          {requested ? 'Reload' : 'Load fundamentals'}
        </Button>
      }
    >
      {!requested ? (
        <EmptyState
          title="Fundamentals not loaded"
          description="This provider call is optional and can be slow. Load it only when you need the company profile."
          icon="info"
        />
      ) : fundamentals.loading ? (
        <LoadingPanel label="Fetching company profile…" rows={5} />
      ) : fundamentals.error ? (
        <ErrorState message={fundamentals.error} onRetry={fundamentals.reload} />
      ) : fundamentals.data ? (
        <div className="space-y-4">
          <div className="grid gap-x-4 gap-y-1 sm:grid-cols-2">
            {profileFields
              .filter((field) => fundamentals.data?.profile[field] !== undefined)
              .map((field) => (
                <div
                  key={field}
                  className="flex items-baseline justify-between gap-3 border-b border-terminal-borderSoft py-1"
                >
                  <span className="text-[11px] text-terminal-muted">{titleCase(field)}</span>
                  <span className="num text-right text-[11px] text-terminal-text">
                    {displayValue(field, fundamentals.data?.profile[field] ?? null)}
                  </span>
                </div>
              ))}
          </div>

          <div className="space-y-4">
            <StatementTable
              title="Quarterly income statement"
              payload={fundamentals.data.quarterly_income_statement}
            />
            <StatementTable
              title="Quarterly balance sheet"
              payload={fundamentals.data.quarterly_balance_sheet}
            />
            <StatementTable
              title="Quarterly cash flow"
              payload={fundamentals.data.quarterly_cash_flow}
            />
          </div>

          <Notice>
            {fundamentals.data.limitations.join(' ')} Source: {fundamentals.data.source}.
          </Notice>
        </div>
      ) : null}
    </Card>
  );
}
