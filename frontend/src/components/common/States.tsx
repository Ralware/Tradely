import type { ReactNode } from 'react';
import { cn } from '../../utils/format';
import { Button } from './Button';
import { Icon } from './Icon';
import type { IconName } from './Icon';

export function Spinner({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        'inline-block h-4 w-4 animate-spin rounded-full border-2 border-white/25 border-t-terminal-accent',
        className,
      )}
      aria-hidden="true"
    />
  );
}

export function LoadingPanel({
  label = 'Loading…',
  rows = 4,
  className,
}: {
  label?: string;
  rows?: number;
  className?: string;
}) {
  return (
    <div className={cn('space-y-3', className)} role="status" aria-live="polite">
      <div className="flex items-center gap-2 text-xs text-terminal-muted">
        <Spinner />
        <span>{label}</span>
      </div>
      <div className="space-y-2">
        {Array.from({ length: rows }).map((_, index) => (
          <div
            key={index}
            className="skeleton-block h-8 w-full"
            style={{ opacity: 1 - index * 0.12 }}
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
        'flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-terminal-border px-4 py-8 text-center',
        className,
      )}
    >
      <span className="rounded-full border border-terminal-border bg-terminal-panelAlt p-2 text-terminal-muted">
        <Icon name={icon} size={18} />
      </span>
      <p className="text-sm font-medium text-terminal-text">{title}</p>
      {description ? (
        <p className="max-w-md text-xs leading-relaxed text-terminal-muted">{description}</p>
      ) : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}

export function ErrorState({
  message,
  onRetry,
  className,
}: {
  message: string;
  onRetry?: () => void;
  className?: string;
}) {
  return (
    <div
      role="alert"
      className={cn(
        'flex flex-col gap-3 rounded-lg border border-[#4a2a33] bg-[#1d1216] px-4 py-3 text-sm',
        className,
      )}
    >
      <div className="flex items-start gap-2">
        <span className="mt-0.5 text-terminal-red">
          <Icon name="alert" size={16} />
        </span>
        <div className="min-w-0">
          <p className="font-medium text-terminal-red">Request failed</p>
          <p className="mt-0.5 break-words text-xs leading-relaxed text-[#e6b3b3]">{message}</p>
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
    neutral: 'border-terminal-border bg-white/[0.02] text-terminal-muted',
    warning: 'border-[#5c4a24] bg-[#231d0f] text-[#e8c98a]',
    negative: 'border-[#4a2a33] bg-[#1d1216] text-[#e6b3b3]',
    positive: 'border-[#245c46] bg-[#0f2a20] text-[#9fe3c4]',
  } as const;

  return (
    <div className={cn('rounded-lg border px-3 py-2 text-xs leading-relaxed', tones[tone], className)}>
      {children}
    </div>
  );
}
