import { cn } from '../../utils/format';
import type { TimeframeOption } from '../../utils/timeframes';

export function TimeframeSelector({
  options,
  value,
  onChange,
  className,
}: {
  options: TimeframeOption[];
  value: string;
  onChange: (id: string) => void;
  className?: string;
}) {
  return (
    <div
      role="tablist"
      aria-label="Timeframe"
      className={cn('flex flex-wrap items-center gap-0.5', className)}
    >
      {options.map((option) => {
        const active = option.id === value;
        return (
          <button
            key={option.id}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(option.id)}
            className={cn(
              'rounded-md px-2.5 py-1 text-xs transition-colors',
              active
                ? 'bg-terminal-panelAlt font-medium text-terminal-text'
                : 'text-terminal-muted hover:bg-white/[0.04] hover:text-terminal-text',
            )}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
