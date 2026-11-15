import type { StrategySignal } from '../../types/api';
import { Card } from '../common/Card';
import { Badge } from '../common/Badge';
import { SignalBadge } from './SignalBadge';
import { ConditionList } from './ConditionList';

export function SignalCard({ signal }: { signal: StrategySignal }) {
  return (
    <Card
      title={signal.strategy}
      actions={
        <div className="flex items-center gap-1">
          {signal.direction ? <Badge>{signal.direction}</Badge> : null}
          <SignalBadge state={signal.state} />
        </div>
      }
    >
      <div>
        <p className="mb-1 text-2xs text-terminal-muted">
          {signal.direction_mode === 'short_only'
            ? 'Short Only'
            : signal.direction_mode === 'long_short'
              ? 'Long + Short'
              : 'Long Only'}
          {' · Manual Research Signal · No Order Execution'}
        </p>
        <ConditionList conditions={signal.conditions} />
      </div>
    </Card>
  );
}
