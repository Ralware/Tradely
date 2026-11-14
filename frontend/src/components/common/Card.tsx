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
    <section className={cn('panel-surface flex min-w-0 flex-col', className)}>
      {title || actions ? (
        <header className="flex flex-wrap items-center justify-between gap-2 border-b border-terminal-border px-3 py-1.5">
          <div className="min-w-0">
            {title ? (
              <h2 className="text-xs font-semibold text-terminal-text">{title}</h2>
            ) : null}
            {subtitle ? <p className="text-2xs text-terminal-muted">{subtitle}</p> : null}
          </div>
          {actions ? <div className="flex flex-wrap items-center gap-1.5">{actions}</div> : null}
        </header>
      ) : null}
      <div className={cn('min-w-0 flex-1', padded && 'p-3', bodyClassName)}>{children}</div>
    </section>
  );
}
