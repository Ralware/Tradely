import { beforeEach, describe, expect, it } from 'vitest';
import { snapshotStore, type PreparedSnapshot } from './snapshotStore';

const identity = 'crypto:BINANCE:ALGOUSDT';

function snapshot(candleTime: string, fingerprint: string): PreparedSnapshot {
  return {
    schema_version: 2,
    interval: '1m',
    fingerprint,
    generated_at: candleTime,
    analysis: { as_of: candleTime },
    provenance: { latest_candle_timestamp: candleTime },
  };
}

describe('snapshotStore ordering', () => {
  beforeEach(() => snapshotStore.clear());

  it('accepts a newer snapshot for the same instrument and timeframe', () => {
    snapshotStore.setSnapshot(identity, '1m', snapshot('2026-11-24T12:00:00Z', 'a'));
    snapshotStore.setSnapshot(identity, '1m', snapshot('2026-11-24T12:01:00Z', 'b'));

    expect(snapshotStore.getSnapshot(identity, '1m')?.fingerprint).toBe('b');
  });

  it('ignores an older snapshot that resolves after a newer one', () => {
    snapshotStore.setSnapshot(identity, '1m', snapshot('2026-11-24T12:01:00Z', 'new'));
    snapshotStore.setSnapshot(identity, '1m', snapshot('2026-11-24T12:00:00Z', 'old'));

    expect(snapshotStore.getSnapshot(identity, '1m')?.fingerprint).toBe('new');
  });

  it('isolates snapshots by instrument and timeframe', () => {
    snapshotStore.setSnapshot(identity, '1m', snapshot('2026-11-24T12:00:00Z', 'one-minute'));
    snapshotStore.setSnapshot(identity, '5m', snapshot('2026-11-24T12:00:00Z', 'five-minute'));

    expect(snapshotStore.getSnapshot(identity, '1m')?.fingerprint).toBe('one-minute');
    expect(snapshotStore.getSnapshot(identity, '5m')?.fingerprint).toBe('five-minute');
  });
});
