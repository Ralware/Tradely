import type { Instrument } from '../../types/api';
import { Badge } from '../common/Badge';

export function InstrumentBadge({
  instrument,
  showName = true,
}: {
  instrument: Pick<Instrument, 'symbol' | 'name' | 'market' | 'exchange' | 'currency' | 'asset_type'>;
  showName?: boolean;
}) {
  const market = instrument.asset_type === 'crypto'
    ? 'Crypto'
    : instrument.market === 'india'
      ? 'India'
      : 'Global';
  return (
    <span className="inline-flex min-w-0 flex-wrap items-center gap-1.5">
      <span className="text-xs font-semibold text-terminal-text">{instrument.symbol}</span>
      {showName ? (
        <span className="truncate text-2xs text-terminal-muted">{instrument.name}</span>
      ) : null}
      <Badge tone="accent">{instrument.exchange}</Badge>
      <Badge>{market}</Badge>
      <Badge>{instrument.currency}</Badge>
    </span>
  );
}
