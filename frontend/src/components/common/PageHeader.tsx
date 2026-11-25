import type { ReactNode } from 'react';

export function PageHeader({
  title,
  subtitle,
  actions,
  meta,
}: {
  title: string;
  subtitle?: ReactNode;
  actions?: ReactNode;
  meta?: ReactNode;
}) {
  return (
    <div className="mb-3 flex flex-wrap items-end justify-between gap-3 border-b border-terminal-border pb-2">
      <div className="min-w-0">
        <h1 className="text-base font-semibold leading-tight tracking-tight text-terminal-text">{title}</h1>
        {subtitle ? <p className="mt-0.5 text-xs text-terminal-muted">{subtitle}</p> : null}
        {meta ? <div className="mt-1 flex flex-wrap items-center gap-1">{meta}</div> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-1.5">{actions}</div> : null}
    </div>
  );
}
