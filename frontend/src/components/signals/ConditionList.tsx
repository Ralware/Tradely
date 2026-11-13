import type { SignalCondition } from '../../types/api';
import { cn, formatNumber } from '../../utils/format';
import { Icon } from '../common/Icon';

export function ConditionList({ conditions }: { conditions: SignalCondition[] }) {
  if (conditions.length === 0) {
    return <p className="text-xs text-terminal-muted">No conditions evaluated.</p>;
  }

  return (
    <ul className="divide-y divide-terminal-borderSoft">
      {conditions.map((condition) => (
        <li key={condition.name} className="flex items-start gap-2.5 py-2.5">
          <span
            className={cn(
              'mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full border',
              condition.passed
                ? 'border-[#245c46] bg-[#0f2a20] text-terminal-green'
                : 'border-terminal-border bg-terminal-panelAlt text-terminal-muted',
            )}
            aria-label={condition.passed ? 'Passed' : 'Not passed'}
          >
            {condition.passed ? <Icon name="check" size={11} /> : <Icon name="close" size={10} />}
          </span>
          <div className="min-w-0">
            <p
              className={cn(
                'text-xs font-medium',
                condition.passed ? 'text-terminal-text' : 'text-terminal-muted',
              )}
            >
              {condition.name}
            </p>
            <p className="mt-0.5 text-[11px] leading-relaxed text-terminal-muted">
              {condition.explanation}
            </p>
            <p className="num mt-0.5 text-[11px] text-terminal-muted">
              observed {typeof condition.observed === 'number' ? formatNumber(condition.observed, 4) : (condition.observed ?? '—')}
              {' · '}
              threshold{' '}
              {typeof condition.threshold === 'number'
                ? formatNumber(condition.threshold, 4)
                : (condition.threshold ?? '—')}
            </p>
          </div>
        </li>
      ))}
    </ul>
  );
}
