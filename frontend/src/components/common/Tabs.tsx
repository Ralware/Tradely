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
      className={cn('flex flex-wrap gap-1 rounded-lg border border-terminal-border bg-terminal-panelAlt p-1', className)}
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
              'rounded-md px-3 py-1.5 text-xs font-medium transition-colors',
              selected
                ? 'bg-[#22304a] text-terminal-text'
                : 'text-terminal-muted hover:text-terminal-text',
            )}
          >
            {item.label}
            {typeof item.count === 'number' ? (
              <span className="ml-1.5 text-[10px] text-terminal-muted">{item.count}</span>
            ) : null}
          </button>
        );
      })}
    </div>
  );
}
