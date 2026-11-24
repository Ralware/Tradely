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
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3 border-b border-terminal-border pb-3">
      <div className="min-w-0">
        <h1 className="text-xl font-semibold leading-tight tracking-tight text-terminal-text">{title}</h1>
        {subtitle ? <p className="mt-1 text-xs text-terminal-muted">{subtitle}</p> : null}
        {meta ? <div className="mt-1 flex flex-wrap items-center gap-1">{meta}</div> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-1.5">{actions}</div> : null}
    </div>
  );
}
