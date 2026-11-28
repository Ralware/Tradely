import { describe, expect, it } from 'vitest';
import type { Candle } from '../../types/api';
import {
  reconcileCandles,
  resolvePreviousClose,
  type LiveCandleEntry,
} from './candleReconcile';

const BASE = Math.floor(Date.UTC(2026, 10, 27, 18, 30, 0) / 1000);

function candle(time: number, overrides: Partial<Candle> = {}): Candle {
  const close = overrides.close ?? 102;
  return {
    timestamp: new Date(time * 1000).toISOString(),
    open: close - 2,
    high: close + 3,
    low: close - 3,
    close,
    volume: 10,
    ...overrides,
  };
}

function entry(
  time: number,
  status: 'forming' | 'final',
  sequence = 1,
  overrides: Partial<Candle> = {},
): LiveCandleEntry {
  return {
    time,
    candle: candle(time, overrides),
    status,
    interval: '1m',
    sequence,
    updatedAt: sequence,
  };
}

describe('candle reconciliation', () => {
  it('returns a forming candle when history is empty', () => {
    const result = reconcileCandles({
      snapshotCandles: [],
      polledCandles: [],
      formingCandle: candle(BASE),
      interval: '1m',
      market: 'crypto',
      now: BASE + 30,
    });
    expect(result.candles).toHaveLength(1);
    expect(result.candles[0]).toMatchObject({ time: BASE, status: 'forming' });
  });

  it('fills a snapshot that is missing the latest completed bar from polled candles', () => {
    const result = reconcileCandles({
      snapshotCandles: [candle(BASE - 180), candle(BASE - 120)],
      polledCandles: [candle(BASE - 60)],
      formingCandle: candle(BASE),
      interval: '1m',
      market: 'crypto',
      now: BASE + 30,
    });
    expect(result.candles.map((item) => item.time)).toEqual([
      BASE - 180, BASE - 120, BASE - 60, BASE,
    ]);
    expect(result.candles.map((item) => item.status)).toEqual([
      'final', 'final', 'final', 'forming',
    ]);
    expect(result.latestFinalized?.time).toBe(BASE - 60);
  });

  it('accepts a newer forming candle and discards one equal to the latest final', () => {
    const newer = reconcileCandles({
      snapshotCandles: [candle(BASE - 60)],
      formingCandle: candle(BASE),
      interval: '1m',
      market: 'crypto',
      now: BASE + 30,
    });
    expect(newer.forming?.time).toBe(BASE);

    const stale = reconcileCandles({
      snapshotCandles: [candle(BASE - 60)],
      formingCandle: candle(BASE - 60, { close: 999 }),
      interval: '1m',
      market: 'crypto',
      now: BASE + 30,
    });
    expect(stale.forming).toBeNull();
    expect(stale.candles).toHaveLength(1);
    expect(stale.diagnostics.rejected.some((item) => item.reason === 'ALREADY_FINALIZED')).toBe(true);
  });

  it('updates the same forming timestamp in place', () => {
    const first = reconcileCandles({
      snapshotCandles: [candle(BASE - 60)],
      formingCandle: candle(BASE, { close: 101 }),
      interval: '1m',
      market: 'crypto',
      now: BASE + 30,
    });
    const second = reconcileCandles({
      snapshotCandles: [candle(BASE - 60)],
      formingCandle: candle(BASE, { close: 104 }),
      interval: '1m',
      market: 'crypto',
      now: BASE + 30,
    });
    expect(first.candles).toHaveLength(2);
    expect(second.candles).toHaveLength(2);
    expect(second.forming?.time).toBe(BASE);
    expect(second.forming?.close).toBe(104);
  });

  it('is a no-op for an unchanged forming candle', () => {
    const input = {
      snapshotCandles: [candle(BASE - 60)],
      formingCandle: candle(BASE, { close: 101 }),
      interval: '1m',
      market: 'crypto' as const,
      now: BASE + 30,
    };
    const first = reconcileCandles(input);
    const second = reconcileCandles(input);
    expect(second.candles).toEqual(first.candles);
    expect(second.diagnostics.formingTime).toBe(first.diagnostics.formingTime);
  });

  it('does not display a stale cached forming bar after the bar becomes final', () => {
    const result = reconcileCandles({
      snapshotCandles: [candle(BASE - 60), candle(BASE)],
      formingCandle: null,
      cachedLive: [entry(BASE, 'forming')],
      interval: '1m',
      market: 'crypto',
      now: BASE + 30,
    });
    expect(result.forming).toBeNull();
    expect(result.candles.map((item) => item.time)).toEqual([BASE - 60, BASE]);
    expect(result.diagnostics.rejected.some((item) => item.reason === 'ALREADY_FINALIZED')).toBe(true);
  });

  it('moves forming to final and activates the next forming bar', () => {
    const before = reconcileCandles({
      snapshotCandles: [candle(BASE - 60)],
      formingCandle: candle(BASE, { close: 103 }),
      interval: '1m',
      market: 'crypto',
      now: BASE + 30,
    });
    expect(before.forming?.time).toBe(BASE);

    const after = reconcileCandles({
      snapshotCandles: [candle(BASE - 60), candle(BASE, { close: 103 })],
      formingCandle: candle(BASE + 60, { close: 104 }),
      interval: '1m',
      market: 'crypto',
      now: BASE + 90,
    });
    expect(after.latestFinalized?.time).toBe(BASE);
    expect(after.latestFinalized?.close).toBe(103);
    expect(after.forming?.time).toBe(BASE + 60);
  });

  it('retains the last cached forming bar while a poll is failing', () => {
    const result = reconcileCandles({
      snapshotCandles: [candle(BASE - 60)],
      formingCandle: null,
      cachedLive: [entry(BASE, 'forming', 4)],
      interval: '1m',
      market: 'crypto',
      now: BASE + 30,
    });
    expect(result.forming?.time).toBe(BASE);
  });

  it('expires a cached forming bar once its interval has ended', () => {
    const result = reconcileCandles({
      snapshotCandles: [candle(BASE - 60)],
      formingCandle: null,
      cachedLive: [entry(BASE, 'forming', 4)],
      interval: '1m',
      market: 'crypto',
      now: BASE + 120,
    });
    expect(result.forming).toBeNull();
    expect(result.diagnostics.rejected.some((item) => item.reason === 'INACTIVE_INTERVAL')).toBe(true);
  });

  it('prefers the newer fetch sequence on a finalized collision', () => {
    const result = reconcileCandles({
      snapshotCandles: [candle(BASE - 60, { close: 100 })],
      polledCandles: [candle(BASE - 60, { close: 105 })],
      formingCandle: null,
      interval: '1m',
      market: 'crypto',
      now: BASE + 30,
      snapshotSequence: 1,
      pollSequence: 2,
    });
    expect(result.latestFinalized?.close).toBe(105);

    const older = reconcileCandles({
      snapshotCandles: [candle(BASE - 60, { close: 100 })],
      polledCandles: [candle(BASE - 60, { close: 105 })],
      formingCandle: null,
      interval: '1m',
      market: 'crypto',
      now: BASE + 30,
      snapshotSequence: 5,
      pollSequence: 2,
    });
    expect(older.latestFinalized?.close).toBe(100);
  });

  it('does not fill closed-market gaps', () => {
    const result = reconcileCandles({
      snapshotCandles: [candle(BASE - 300), candle(BASE - 60)],
      formingCandle: null,
      interval: '1m',
      market: 'crypto',
      now: BASE + 30,
    });
    expect(result.candles.map((item) => item.time)).toEqual([BASE - 300, BASE - 60]);
  });

  it('rejects a forming bar that is not aligned to the interval', () => {
    const result = reconcileCandles({
      snapshotCandles: [candle(BASE - 60)],
      formingCandle: candle(BASE + 30),
      interval: '1m',
      market: 'crypto',
      now: BASE + 45,
    });
    expect(result.forming).toBeNull();
    expect(result.diagnostics.rejected.some((item) => item.reason === 'MISALIGNED_TIMESTAMP')).toBe(true);
  });

  it('uses the India session for daily active intervals', () => {
    const previousDay = Math.floor(Date.UTC(2026, 10, 26, 0, 0, 0) / 1000);
    const sessionDay = Math.floor(Date.UTC(2026, 10, 27, 0, 0, 0) / 1000);
    const duringSession = Math.floor(Date.UTC(2026, 10, 27, 9, 0, 0) / 1000);
    const afterClose = Math.floor(Date.UTC(2026, 10, 27, 11, 0, 0) / 1000);

    const active = reconcileCandles({
      snapshotCandles: [candle(previousDay)],
      formingCandle: candle(sessionDay),
      interval: '1d',
      market: 'india',
      now: duringSession,
    });
    expect(active.forming?.time).toBe(sessionDay);

    const closed = reconcileCandles({
      snapshotCandles: [candle(previousDay)],
      formingCandle: candle(sessionDay),
      interval: '1d',
      market: 'india',
      now: afterClose,
    });
    expect(closed.forming).toBeNull();
    expect(closed.diagnostics.rejected.some((item) => item.reason === 'INACTIVE_INTERVAL')).toBe(true);
  });
});

describe('previous close', () => {
  const snapshot = [candle(BASE - 120, { close: 100 }), candle(BASE - 60, { close: 110 })];

  it('uses the latest completed close while a forming candle is active', () => {
    expect(resolvePreviousClose({
      snapshotCandles: snapshot,
      formingCandle: candle(BASE, { close: 120 }),
      interval: '1m',
      market: 'crypto',
      now: BASE + 30,
    })).toBe(110);
  });

  it('uses the bar before the latest completed close without a forming candle', () => {
    expect(resolvePreviousClose({
      snapshotCandles: snapshot,
      formingCandle: null,
      interval: '1m',
      market: 'crypto',
      now: BASE + 30,
    })).toBe(100);
  });

  it('includes a newer polled completed bar', () => {
    expect(resolvePreviousClose({
      snapshotCandles: snapshot,
      polledCandles: [candle(BASE, { close: 120 })],
      formingCandle: null,
      interval: '1m',
      market: 'crypto',
      now: BASE + 30,
    })).toBe(110);
  });
});
