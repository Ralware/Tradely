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
    <div className={cn('panel-surface px-3 py-2', className)}>
      <p className="text-2xs text-terminal-muted">{label}</p>
      <p className={cn('num mt-0.5 text-base font-semibold', tones[tone])}>{value}</p>
      {hint ? <p className="mt-0.5 text-2xs text-terminal-muted">{hint}</p> : null}
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
    <div className={cn('flex items-baseline justify-between gap-3 py-1', className)}>
      <dt className="text-2xs text-terminal-muted">{label}</dt>
      <dd className="num text-right text-2xs font-medium text-terminal-text">{value}</dd>
    </div>
  );
}
