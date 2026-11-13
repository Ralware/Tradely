import type { StrategySignal } from '../../types/api';
import { formatDateTime, formatNumber } from '../../utils/format';
import { Card } from '../common/Card';
import { KeyValue } from '../common/Stat';
import { SignalBadge } from './SignalBadge';
import { ConditionList } from './ConditionList';

export function SignalCard({
  signal,
  currency,
}: {
  signal: StrategySignal;
  currency?: string | null;
}) {
  const hasLevels =
    signal.entry_reference !== null ||
    signal.stop_reference !== null ||
    signal.risk_per_unit !== null;

  return (
    <Card
      title="Strategy state"
      subtitle={`${signal.strategy} · ${signal.strategy_version}`}
      actions={<SignalBadge state={signal.state} />}
    >
      <p className="text-xs leading-relaxed text-terminal-muted">{signal.explanation}</p>

      {hasLevels ? (
        <dl className="mt-3 divide-y divide-terminal-borderSoft rounded-lg border border-terminal-borderSoft bg-terminal-panelAlt px-3 py-1">
          <KeyValue
            label="Entry reference"
            value={formatNumber(signal.entry_reference, 2)}
          />
          <KeyValue label="Stop reference" value={formatNumber(signal.stop_reference, 2)} />
          <KeyValue
            label="Risk per unit"
            value={
              signal.risk_per_unit === null
                ? '—'
                : `${formatNumber(signal.risk_per_unit, 2)}${currency ? ` ${currency}` : ''}`
            }
          />
        </dl>
      ) : null}

      <div className="mt-3">
        <p className="mb-1 text-[11px] font-medium uppercase tracking-[0.08em] text-terminal-muted">
          Rule checks
        </p>
        <ConditionList conditions={signal.conditions} />
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-terminal-borderSoft pt-2 text-[11px] text-terminal-muted">
        <span>As of {formatDateTime(signal.as_of)}</span>
        {signal.data_source ? <span>Source: {signal.data_source}</span> : null}
      </div>
    </Card>
  );
}
