import type { ReactNode } from 'react';
import { cn } from '../../utils/format';

interface CardProps {
  title?: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
  padded?: boolean;
}

export function Card({
  title,
  subtitle,
  actions,
  children,
  className,
  bodyClassName,
  padded = true,
}: CardProps) {
  return (
    <section className={cn('panel-surface enter-reveal flex min-w-0 flex-col overflow-hidden', className)}>
      {title || actions ? (
        <header className="flex min-h-11 flex-wrap items-center justify-between gap-2 border-b border-terminal-border bg-white/[0.012] px-3 py-2.5 sm:px-4">
          <div className="min-w-0">
            {title ? (
              <h2 className="text-xs font-semibold tracking-[0.045em] text-terminal-text">{title}</h2>
            ) : null}
            {subtitle ? <p className="text-2xs text-terminal-muted">{subtitle}</p> : null}
          </div>
          {actions ? <div className="flex flex-wrap items-center gap-1.5">{actions}</div> : null}
        </header>
      ) : null}
      <div className={cn('min-w-0 flex-1', padded && 'p-3 sm:p-4', bodyClassName)}>{children}</div>
    </section>
  );
}
