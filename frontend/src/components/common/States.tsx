import type { ReactNode } from 'react';
import { cn } from '../../utils/format';
import { Button } from './Button';
import { Icon } from './Icon';
import type { IconName } from './Icon';

export function Spinner({ className }: { className?: string }) {
  return <Icon name="refresh" size={14} className={cn('animate-spin text-terminal-accent', className)} />;
}

export function LoadingPanel({
  label = 'Loading',
  rows = 4,
  className,
}: {
  label?: string;
  rows?: number;
  className?: string;
}) {
  return (
    <div className={cn('space-y-2', className)} role="status" aria-live="polite">
      <div className="flex items-center gap-2 text-2xs text-terminal-muted">
        <Spinner />
        <span>{label}</span>
      </div>
      <div className="space-y-1.5">
        {Array.from({ length: rows }).map((_, index) => (
          <div
            key={index}
            className="skeleton-block h-4"
            style={{ width: `${88 - ((index * 13) % 40)}%` }}
          />
        ))}
      </div>
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
  icon = 'info',
  className,
}: {
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  icon?: IconName;
  className?: string;
}) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center gap-1.5 rounded-md border border-dashed border-terminal-border px-3 py-6 text-center',
        className,
      )}
    >
      <span className="text-terminal-muted">
        <Icon name={icon} size={16} />
      </span>
      <p className="text-xs font-medium text-terminal-text">{title}</p>
      {description ? (
        <p className="max-w-md text-2xs leading-relaxed text-terminal-muted">{description}</p>
      ) : null}
      {action ? <div className="mt-1">{action}</div> : null}
    </div>
  );
}

export function ErrorState({
  message,
  onRetry,
  className,
  title = 'Request Failed',
}: {
  message: string;
  onRetry?: () => void;
  className?: string;
  title?: string;
}) {
  return (
    <div
      role="alert"
      className={cn(
        'flex flex-col gap-2 rounded-md border border-[#3f2528] bg-[#150f11] px-3 py-2',
        className,
      )}
    >
      <div className="flex items-start gap-2">
        <span className="mt-0.5 text-terminal-red">
          <Icon name="alert" size={14} />
        </span>
        <div className="min-w-0">
          <p className="text-2xs font-medium text-terminal-red">{title}</p>
          <p className="mt-0.5 break-words text-2xs leading-relaxed text-[#d9a9a9]">{message}</p>
        </div>
      </div>
      {onRetry ? (
        <div>
          <Button size="sm" icon="refresh" onClick={onRetry}>
            Retry
          </Button>
        </div>
      ) : null}
    </div>
  );
}

export function Notice({
  tone = 'neutral',
  children,
  className,
}: {
  tone?: 'neutral' | 'warning' | 'negative' | 'positive';
  children: ReactNode;
  className?: string;
}) {
  const tones = {
    neutral: 'border-terminal-border bg-terminal-panel text-terminal-muted',
    warning: 'border-[#4d3d1f] bg-[#14110b] text-[#dcc18d]',
    negative: 'border-[#3f2528] bg-[#150f11] text-[#d9a9a9]',
    positive: 'border-[#1f4d43] bg-[#0c1512] text-[#8fd6c2]',
  } as const;

  return (
    <div className={cn('rounded-md border px-2.5 py-1.5 text-2xs leading-relaxed', tones[tone], className)}>
      {children}
    </div>
  );
}
