import { Badge } from '../common/Badge';
import type { BadgeTone } from '../common/Badge';
import type { SignalState } from '../../types/api';

const meta: Record<SignalState, { label: string; tone: BadgeTone }> = {
  BUY: { label: 'BUY', tone: 'positive' },
  SELL: { label: 'SELL · exit long', tone: 'negative' },
  WAIT: { label: 'WAIT', tone: 'warning' },
  NO_SIGNAL: { label: 'NO SIGNAL', tone: 'neutral' },
  INSUFFICIENT_DATA: { label: 'INSUFFICIENT DATA', tone: 'neutral' },
  STALE_DATA: { label: 'STALE DATA', tone: 'warning' },
  DATA_QUALITY_ERROR: { label: 'DATA QUALITY ERROR', tone: 'negative' },
};

export function SignalBadge({ state, dot = true }: { state: SignalState; dot?: boolean }) {
  const entry = meta[state] ?? { label: state, tone: 'neutral' as BadgeTone };
  return (
    <Badge tone={entry.tone} dot={dot}>
      {entry.label}
    </Badge>
  );
}
