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
      className={cn('flex flex-nowrap items-center gap-0.5 whitespace-nowrap', className)}
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
              'shrink-0 rounded-md px-2.5 py-1 text-xs transition-colors',
              active
                ? 'bg-white/[0.08] font-medium text-white'
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
