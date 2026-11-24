import { useState } from 'react';
import type { TechnicalCounts, TechnicalRow } from '../../types/api';
import { cn, formatNumber } from '../../utils/format';
import { Icon } from '../common/Icon';

function actionTone(row: TechnicalRow): string {
  if (row.action === 'Buy') return 'tv-technical-action-buy';
  if (row.action === 'Sell') return 'tv-technical-action-sell';
  if (row.action === 'Neutral') return 'tv-technical-action-neutral';
  return 'tv-technical-action-unavailable';
}

function indicatorName(row: TechnicalRow): string {
  const values = Object.values(row.parameters);
  return values.length > 0 ? `${row.name} (${values.join(', ')})` : row.name;
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

  return (
    <section
      className={cn('tv-technical-table', className)}
      aria-label={`${title}; ${summary.available} of ${summary.total} indicators available`}
    >
      <h2 className="tv-technical-table-title">{title}</h2>
      <table>
        <thead>
          <tr>
            <th scope="col">Name</th>
            <th scope="col">Value</th>
            <th scope="col">Action</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const isOpen = Boolean(expanded[row.key]);
            const entries = Object.entries(row.details);
            const hasDetails = entries.length > 0;
            const name = indicatorName(row);
            const rating = row.rating === null ? 'unavailable' : row.rating > 0 ? '+1' : String(row.rating);

            return (
              <FragmentRow
                key={row.key}
                row={row}
                name={name}
                rating={rating}
                actionClass={actionTone(row)}
                isOpen={isOpen}
                hasDetails={hasDetails}
                entries={entries}
                onToggle={() => setExpanded((current) => ({ ...current, [row.key]: !current[row.key] }))}
              />
            );
          })}
          {rows.length === 0 ? (
            <tr>
              <td colSpan={3} className="tv-technical-empty">No indicator values are available for this group.</td>
            </tr>
          ) : null}
        </tbody>
      </table>
    </section>
  );
}

function FragmentRow({
  row,
  name,
  rating,
  actionClass,
  isOpen,
  hasDetails,
  entries,
  onToggle,
}: {
  row: TechnicalRow;
  name: string;
  rating: string;
  actionClass: string;
  isOpen: boolean;
  hasDetails: boolean;
  entries: Array<[string, number | null]>;
  onToggle: () => void;
}) {
  return (
    <>
      <tr className="tv-technical-row">
        <td>
          <div className="tv-technical-name-cell">
            {hasDetails ? (
              <button
                type="button"
                className="tv-technical-expand"
                aria-expanded={isOpen}
                aria-label={`${isOpen ? 'Hide' : 'Show'} ${row.name} component values`}
                onClick={onToggle}
              >
                <span aria-hidden="true">
                  <Icon name={isOpen ? 'minus' : 'plus'} size={13} />
                </span>
              </button>
            ) : null}
            <span title={name}>{name}</span>
          </div>
        </td>
        <td className="num tv-technical-value">{formatNumber(row.value, row.precision)}</td>
        <td className={cn('tv-technical-action', actionClass)} title={`Rating ${rating}`}>
          {row.action === 'Unavailable' ? '—' : row.action}
        </td>
      </tr>
      {isOpen && hasDetails ? (
        <tr className="tv-technical-details-row">
          <td colSpan={3}>
            <dl>
              {entries.map(([key, value]) => (
                <div key={key}>
                  <dt>{key.replace(/_/g, ' ')}</dt>
                  <dd className="num">{formatNumber(value, 6)}</dd>
                </div>
              ))}
            </dl>
          </td>
        </tr>
      ) : null}
    </>
  );
}
