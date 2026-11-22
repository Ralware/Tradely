import { useState } from 'react';
import type { TechnicalCounts, TechnicalRow } from '../../types/api';
import { cn, formatNumber, titleCase } from '../../utils/format';

const actionTone: Record<TechnicalRow['action'], string> = {
  Buy: 'text-terminal-green',
  Sell: 'text-terminal-red',
  Neutral: 'text-terminal-muted',
  Unavailable: 'text-terminal-amber',
};

function parameterText(parameters: TechnicalRow['parameters']): string {
  return Object.entries(parameters)
    .map(([key, value]) => `${key} ${value}`)
    .join(' · ');
}

function DetailValue({ name, value }: { name: string; value: number | null }) {
  return (
    <div className="flex min-w-0 items-center justify-between gap-3 border-b border-terminal-borderSoft py-1 last:border-0">
      <span className="truncate text-2xs text-terminal-muted">{titleCase(name)}</span>
      <span className="num shrink-0 text-2xs text-terminal-text">{formatNumber(value, 6)}</span>
    </div>
  );
}

export function TechnicalTable({
  title,
  rows,
  summary,
  className,
}: {
  title: string;
  rows: TechnicalRow[];
  summary: TechnicalCounts;
  className?: string;
}) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const hasAnyDetails = rows.some((row) => Object.keys(row.details).length > 0);

  return (
    <section className={cn('panel-surface min-w-0', className)}>
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-terminal-border px-3 py-2">
        <div>
          <h2 className="text-xs font-semibold text-terminal-text">{title}</h2>
          <p className="mt-0.5 text-2xs text-terminal-muted">
            Aggregate {summary.score === null ? '—' : summary.score.toFixed(3)} · {summary.action}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-2xs">
          <span className="text-terminal-green">Buy {summary.buy}</span>
          <span className="text-terminal-muted">Neutral {summary.neutral}</span>
          <span className="text-terminal-red">Sell {summary.sell}</span>
          {summary.unavailable > 0 ? <span className="text-terminal-amber">Unavailable {summary.unavailable}</span> : null}
          <span className="text-terminal-muted">{rows.length} indicators</span>
        </div>
      </header>
      <div className="overflow-x-auto">
        <table className="data-table min-w-[640px]">
          <thead>
            <tr>
              <th className="pl-3">Indicator</th>
              <th>Parameters</th>
              <th className="text-right">Value</th>
              <th className="w-24 pr-2 text-right">Signal</th>
              <th className="w-16 pr-3 text-right">Rating</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const isOpen = Boolean(expanded[row.key]);
              const detailEntries = Object.entries(row.details);
              const hasDetails = detailEntries.length > 0;
              return (
                <tr key={row.key} className="group">
                  <td colSpan={5} className="!p-0">
                    <div className="grid grid-cols-[minmax(150px,1.4fr)_minmax(160px,1.2fr)_minmax(90px,0.8fr)_90px_58px] items-center border-b border-terminal-borderSoft px-3 py-2 text-xs">
                      <div className="flex min-w-0 items-center gap-1.5">
                        {hasDetails ? (
                          <button
                            type="button"
                            aria-expanded={isOpen}
                            aria-label={`${isOpen ? 'Hide' : 'Show'} ${row.name} components`}
                            onClick={() => setExpanded((current) => ({ ...current, [row.key]: !current[row.key] }))}
                            className="shrink-0 text-terminal-muted hover:text-terminal-text"
                          >
                            <span aria-hidden="true">{isOpen ? '−' : '+'}</span>
                          </button>
                        ) : <span className="w-2 shrink-0" />}
                        <span className="truncate text-terminal-text" title={row.name}>{row.name}</span>
                      </div>
                      <span className="truncate pr-2 text-2xs text-terminal-muted" title={parameterText(row.parameters)}>
                        {parameterText(row.parameters) || '—'}
                      </span>
                      <span className="num text-right text-terminal-text">
                        {formatNumber(row.value, row.precision)}
                      </span>
                      <span className={cn('text-right text-xs font-medium', actionTone[row.action])}>
                        {row.action}
                      </span>
                      <span className={cn('num pr-1 text-right font-semibold', row.rating === 1 ? 'text-terminal-green' : row.rating === -1 ? 'text-terminal-red' : row.rating === 0 ? 'text-terminal-text' : 'text-terminal-amber')}>
                        {row.rating === null ? '—' : row.rating > 0 ? '+1' : String(row.rating)}
                      </span>
                    </div>
                    {isOpen && hasDetails ? (
                      <div className="grid grid-cols-1 gap-x-8 bg-white/[0.015] px-8 py-2 sm:grid-cols-2">
                        {detailEntries.map(([key, value]) => (
                          <DetailValue key={key} name={key} value={value} />
                        ))}
                      </div>
                    ) : null}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {!hasAnyDetails ? <p className="px-3 py-2 text-2xs text-terminal-muted">No additional component values are exposed for this group.</p> : null}
    </section>
  );
}
