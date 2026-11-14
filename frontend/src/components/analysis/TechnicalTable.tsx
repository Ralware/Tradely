import type { TechnicalRow } from '../../types/api';
import { cn, formatNumber } from '../../utils/format';

const actionTone: Record<TechnicalRow['action'], string> = {
  Buy: 'text-terminal-green',
  Sell: 'text-terminal-red',
  Neutral: 'text-terminal-muted',
};

export function TechnicalTable({
  title,
  rows,
  className,
}: {
  title: string;
  rows: TechnicalRow[];
  className?: string;
}) {
  return (
    <section className={cn('panel-surface min-w-0', className)}>
      <header className="flex items-center justify-between border-b border-terminal-border px-3 py-2">
        <h2 className="text-xs font-semibold text-terminal-text">{title}</h2>
        <span className="text-2xs text-terminal-muted">{rows.length} Indicators</span>
      </header>
      <div className="overflow-x-auto">
        <table className="data-table min-w-[420px]">
          <thead>
            <tr>
              <th className="pl-3">Name</th>
              <th className="text-right">Value</th>
              <th className="w-24 pr-3 text-right">Action</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={`${row.field}-${row.name}`}>
                <td className="pl-3 pr-2 text-terminal-text">{row.name}</td>
                <td className="num px-2 text-right text-terminal-text">
                  {formatNumber(row.value, 4)}
                </td>
                <td className={cn('pr-3 text-right font-medium', actionTone[row.action])}>
                  {row.action}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
