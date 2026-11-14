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
      className={cn('flex flex-wrap items-center gap-0.5 border-b border-terminal-border', className)}
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
              '-mb-px border-b-2 px-2.5 py-1.5 text-xs transition-colors',
              selected
                ? 'border-terminal-accent font-medium text-terminal-text'
                : 'border-transparent text-terminal-muted hover:text-terminal-text',
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
