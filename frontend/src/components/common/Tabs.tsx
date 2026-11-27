import { cn } from '../../utils/format';

export interface TabItem {
  id: string;
  label: string;
  count?: number;
}

export function Tabs({
  items,
  active,
  onChange,
  className,
}: {
  items: TabItem[];
  active: string;
  onChange: (id: string) => void;
  className?: string;
}) {
  return (
    <div
      role="tablist"
      aria-label="Section"
      className={cn('flex flex-wrap items-center gap-1 border-b border-terminal-border pb-1', className)}
    >
      {items.map((item) => {
        const selected = item.id === active;
        return (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={selected}
            onClick={() => onChange(item.id)}
            className={cn(
              'rounded-md px-2.5 py-1.5 text-xs transition-all duration-200',
              selected
                ? 'bg-terminal-accentSoft font-medium text-terminal-accent shadow-[inset_0_0_0_1px_rgba(22,133,255,0.18)]'
                : 'border-transparent text-terminal-muted hover:bg-white/[0.035] hover:text-terminal-text',
            )}
          >
            {item.label}
            {typeof item.count === 'number' ? (
              <span className="num ml-1.5 text-2xs text-terminal-muted">{item.count}</span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}
