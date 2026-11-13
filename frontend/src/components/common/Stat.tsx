import type { ReactNode } from 'react';
import { cn } from '../../utils/format';

export function Stat({
  label,
  value,
  hint,
  tone = 'neutral',
  className,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: 'neutral' | 'positive' | 'negative' | 'warning' | 'accent';
  className?: string;
}) {
  const tones = {
    neutral: 'text-terminal-text',
    positive: 'text-terminal-green',
    negative: 'text-terminal-red',
    warning: 'text-terminal-amber',
    accent: 'text-terminal-accent',
  } as const;

  return (
    <div className={cn('panel-surface px-4 py-3', className)}>
      <p className="text-[11px] font-medium uppercase tracking-[0.08em] text-terminal-muted">
        {label}
      </p>
      <p className={cn('num mt-1 text-xl font-semibold tracking-tight', tones[tone])}>{value}</p>
      {hint ? <p className="mt-0.5 text-xs text-terminal-muted">{hint}</p> : null}
    </div>
  );
}

export function KeyValue({
  label,
  value,
  className,
}: {
  label: string;
  value: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn('flex items-baseline justify-between gap-3 py-1.5', className)}>
      <dt className="text-xs text-terminal-muted">{label}</dt>
      <dd className="num text-right text-xs font-medium text-terminal-text">{value}</dd>
    </div>
  );
}
