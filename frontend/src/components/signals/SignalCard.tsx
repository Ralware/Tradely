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
      title="Strategy State"
      subtitle={`${signal.strategy} · ${signal.strategy_version}`}
      actions={<SignalBadge state={signal.state} />}
    >
      <p className="text-2xs leading-relaxed text-terminal-muted">{signal.explanation}</p>

      {hasLevels ? (
        <dl className="mt-2 divide-y divide-terminal-borderSoft border-y border-terminal-borderSoft">
          <KeyValue label="Entry Reference" value={formatNumber(signal.entry_reference, 2)} />
          <KeyValue label="Stop Reference" value={formatNumber(signal.stop_reference, 2)} />
          <KeyValue
            label="Risk per Unit"
            value={
              signal.risk_per_unit === null
                ? '—'
                : `${formatNumber(signal.risk_per_unit, 2)}${currency ? ` ${currency}` : ''}`
            }
          />
        </dl>
      ) : null}

      <div className="mt-2">
        <p className="mb-1 text-2xs font-medium text-terminal-muted">Rule Checks</p>
        <ConditionList conditions={signal.conditions} />
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-terminal-borderSoft pt-1.5 text-2xs text-terminal-muted">
        <span>As of {formatDateTime(signal.as_of)}</span>
        {signal.data_source ? <span>Source: {signal.data_source}</span> : null}
      </div>
    </Card>
  );
}
