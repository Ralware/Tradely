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
        <header className="flex flex-wrap items-start justify-between gap-3 border-b border-terminal-borderSoft px-4 py-3">
          <div className="min-w-0">
            {title ? (
              <h2 className="text-sm font-semibold tracking-tight text-terminal-text">{title}</h2>
            ) : null}
            {subtitle ? <p className="mt-0.5 text-xs text-terminal-muted">{subtitle}</p> : null}
          </div>
          {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
        </header>
      ) : null}
      <div className={cn('min-w-0 flex-1', padded && 'p-4', bodyClassName)}>{children}</div>
    </section>
  );
}
