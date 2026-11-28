import { describe, expect, it, vi } from 'vitest';
import type { Candle } from '../types/api';
import {
  createCandlePollController,
  type CandlePollResponse,
  type PolledCandleState,
} from './candlePolling';

const BASE = Math.floor(Date.UTC(2026, 10, 27, 18, 0, 0) / 1000);

function candle(time: number, close = 100): Candle {
  return {
    timestamp: new Date(time * 1000).toISOString(),
    open: close - 1,
    high: close + 1,
    low: close - 2,
    close,
    volume: 10,
  };
}

const flush = () => new Promise<void>((resolve) => setTimeout(resolve, 0));

describe('candle poll controller', () => {
  it('tags responses with key and increasing sequence', async () => {
    const updates: PolledCandleState[] = [];
    const fetch = vi.fn()
      .mockResolvedValueOnce({ candles: [candle(BASE - 60)], forming_candle: candle(BASE) })
      .mockResolvedValueOnce({ candles: [candle(BASE)], forming_candle: candle(BASE + 60) });
    const controller = createCandlePollController({
      key: 'instrument\u00001m',
      intervalMs: 1_000_000,
      fetch,
      onUpdate: (state) => updates.push(state),
    });

    controller.start();
    await flush();
    await controller.pollOnce();
    controller.stop();

    expect(updates.map((state) => state.key)).toEqual(['instrument\u00001m', 'instrument\u00001m']);
    expect(updates.map((state) => state.sequence)).toEqual([1, 2]);
    expect(updates[1].formingCandle?.close).toBe(100);
  });

  it('keeps the last valid state when a poll fails', async () => {
    const updates: PolledCandleState[] = [];
    const errors: unknown[] = [];
    const fetch = vi.fn()
      .mockResolvedValueOnce({ candles: [candle(BASE - 60)], forming_candle: candle(BASE) })
      .mockRejectedValueOnce(new Error('provider down'));
    const controller = createCandlePollController({
      key: 'instrument\u00001m',
      intervalMs: 1_000_000,
      fetch,
      onUpdate: (state) => updates.push(state),
      onError: (error) => errors.push(error),
    });

    controller.start();
    await flush();
    await controller.pollOnce();
    controller.stop();

    expect(updates).toHaveLength(1);
    expect(errors).toHaveLength(1);
  });

  it('aborts the in-flight request on stop/unmount', async () => {
    const captured: { signal?: AbortSignal } = {};
    const fetch = vi.fn((requestSignal: AbortSignal) => {
      captured.signal = requestSignal;
      return new Promise<CandlePollResponse>((_resolve, reject) => {
        requestSignal.addEventListener('abort', () => {
          reject(new DOMException('aborted', 'AbortError'));
        });
      });
    });
    const controller = createCandlePollController({
      key: 'instrument\u00001m',
      intervalMs: 1_000_000,
      fetch,
      onUpdate: vi.fn(),
    });

    controller.start();
    expect(captured.signal?.aborted).toBe(false);
    controller.stop();
    expect(captured.signal?.aborted).toBe(true);
  });

  it('discards a late response from a stopped instrument/timeframe', async () => {
    const deferred: { resolve?: (value: CandlePollResponse) => void } = {};
    const oldFetch = vi.fn((signal: AbortSignal) => new Promise<CandlePollResponse>((resolve, reject) => {
      deferred.resolve = resolve;
      signal.addEventListener('abort', () => {
        reject(new DOMException('aborted', 'AbortError'));
      });
    }));
    const oldUpdates: PolledCandleState[] = [];
    const oldController = createCandlePollController({
      key: 'old\u00001m',
      intervalMs: 1_000_000,
      fetch: oldFetch,
      onUpdate: (state) => oldUpdates.push(state),
    });
    const newUpdates: PolledCandleState[] = [];
    const newController = createCandlePollController({
      key: 'new\u00001m',
      intervalMs: 1_000_000,
      fetch: vi.fn().mockResolvedValue({
        candles: [candle(BASE - 60)],
        forming_candle: candle(BASE),
      }),
      onUpdate: (state) => newUpdates.push(state),
    });

    oldController.start();
    newController.start();
    oldController.stop();
    deferred.resolve?.({ candles: [candle(BASE - 120)], forming_candle: null });
    await flush();

    expect(oldUpdates).toHaveLength(0);
    expect(newUpdates).toHaveLength(1);
    newController.stop();
  });

  it('reports a forming_bar_excluded mismatch without dropping the response', async () => {
    const updates: PolledCandleState[] = [];
    const mismatches: string[] = [];
    const controller = createCandlePollController({
      key: 'instrument\u00001m',
      intervalMs: 1_000_000,
      fetch: vi.fn().mockResolvedValue({
        candles: [candle(BASE - 60)],
        forming_candle: null,
        forming_bar_excluded: true,
      }),
      onUpdate: (state) => updates.push(state),
      onContractMismatch: (message) => mismatches.push(message),
    });

    controller.start();
    await flush();
    controller.stop();

    expect(mismatches).toHaveLength(1);
    expect(updates).toHaveLength(1);
    expect(updates[0].formingCandle).toBeNull();
  });
});
