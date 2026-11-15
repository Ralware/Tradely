import { Badge } from '../common/Badge';
import type { BadgeTone } from '../common/Badge';
import type { SignalState } from '../../types/api';

const meta: Record<SignalState, { label: string; tone: BadgeTone }> = {
  BUY: { label: 'Buy', tone: 'positive' },
  SELL: { label: 'Sell · Exit Long', tone: 'negative' },
  SELL_SHORT: { label: 'Sell Short', tone: 'negative' },
  BUY_TO_COVER: { label: 'Buy To Cover', tone: 'positive' },
  WAIT: { label: 'Wait', tone: 'warning' },
  NO_SIGNAL: { label: 'No Signal', tone: 'neutral' },
  INSUFFICIENT_DATA: { label: 'Insufficient Data', tone: 'neutral' },
  STALE_DATA: { label: 'Stale Data', tone: 'warning' },
  DATA_QUALITY_ERROR: { label: 'Data Quality Error', tone: 'negative' },
};

export function SignalBadge({ state, dot = true }: { state: SignalState; dot?: boolean }) {
  const entry = meta[state] ?? { label: state, tone: 'neutral' as BadgeTone };
  return (
    <Badge tone={entry.tone} dot={dot}>
      {entry.label}
    </Badge>
  );
}
