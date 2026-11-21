import type { TechnicalCounts } from '../../types/api';
import { cn } from '../../utils/format';

function DistributionRow({ label, summary, emphasize = false }: {
  label: string;
  summary: TechnicalCounts;
  emphasize?: boolean;
}) {
  const available = Math.max(1, summary.available);
  return (
    <div className={cn('grid grid-cols-[minmax(110px,1fr)_repeat(4,minmax(54px,auto))] items-center gap-3 py-2', emphasize && 'border-t border-terminal-border pt-3')}>
      <div className="min-w-0">
        <p className={cn('truncate text-xs', emphasize ? 'font-semibold text-terminal-text' : 'text-terminal-muted')}>{label}</p>
        <p className="text-2xs text-terminal-muted">{summary.available}/{summary.total} available</p>
      </div>
      <div className="text-right">
        <p className="num text-xs font-medium text-terminal-green">{summary.buy}</p>
        <p className="text-2xs text-terminal-muted">Buy</p>
      </div>
      <div className="text-right">
        <p className="num text-xs font-medium text-terminal-text">{summary.neutral}</p>
        <p className="text-2xs text-terminal-muted">Neutral</p>
      </div>
      <div className="text-right">
        <p className="num text-xs font-medium text-terminal-red">{summary.sell}</p>
        <p className="text-2xs text-terminal-muted">Sell</p>
      </div>
      <div className="text-right">
        <p className="num text-xs font-medium text-terminal-amber">{summary.unavailable}</p>
        <p className="text-2xs text-terminal-muted">N/A</p>
      </div>
      <div className="col-span-full h-1 overflow-hidden rounded-full bg-white/[0.06]">
        <div className="flex h-full w-full">
          <span className="h-full bg-terminal-green" style={{ width: `${(summary.buy / available) * 100}%` }} />
          <span className="h-full bg-terminal-muted/70" style={{ width: `${(summary.neutral / available) * 100}%` }} />
          <span className="h-full bg-terminal-red" style={{ width: `${(summary.sell / available) * 100}%` }} />
        </div>
      </div>
    </div>
  );
}

export function TechnicalDistribution({ summary }: {
  summary: {
    oscillators: TechnicalCounts;
    moving_averages: TechnicalCounts;
    overall: TechnicalCounts;
  };
}) {
  return (
    <section className="panel-surface min-w-0">
      <header className="border-b border-terminal-border px-3 py-2">
        <h2 className="text-xs font-semibold text-terminal-text">Signal Distribution</h2>
        <p className="mt-0.5 text-2xs text-terminal-muted">Constituent ratings only; unavailable indicators are excluded from signal counts.</p>
      </header>
      <div className="px-3 py-1">
        <div className="grid grid-cols-[minmax(110px,1fr)_repeat(4,minmax(54px,auto))] gap-3 border-b border-terminal-borderSoft py-1 text-2xs text-terminal-muted">
          <span>Group</span><span className="text-right">Buy</span><span className="text-right">Neutral</span><span className="text-right">Sell</span><span className="text-right">N/A</span>
        </div>
        <DistributionRow label="Moving Averages" summary={summary.moving_averages} />
        <DistributionRow label="Oscillators" summary={summary.oscillators} />
        <DistributionRow label="Overall" summary={summary.overall} emphasize />
      </div>
    </section>
  );
}
