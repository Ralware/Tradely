import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { WatchlistItem } from '../types/api';

const mocks = vi.hoisted(() => ({
  apiRequest: vi.fn(),
  getCandles: vi.fn(),
}));

vi.mock('./api', () => ({ apiRequest: mocks.apiRequest }));
vi.mock('./marketService', () => ({
  marketService: { getCandles: mocks.getCandles },
}));

import { sparklineService } from './sparklineService';

function item(index: number): WatchlistItem {
  return {
    instrument_id: `global:NASDAQ:TEST${index}`,
    symbol: `TEST${index}`,
    market: 'global',
    exchange: 'NASDAQ',
  } as WatchlistItem;
}

beforeEach(() => {
  sparklineService.invalidate();
  vi.clearAllMocks();
  mocks.getCandles.mockResolvedValue({ candles: [{ close: 1 }] });
});

describe('sparklineService', () => {
  it('loads missing sparklines through one batched request and reuses the cache', async () => {
    const items = [item(1), item(2), item(3)];
    mocks.apiRequest.mockResolvedValue({
      items: {
        'global:NASDAQ:TEST1': { closes: [1, 2] },
        'global:NASDAQ:TEST2': { closes: [3, 4] },
        'global:NASDAQ:TEST3': { closes: [5, 6] },
      },
    });

    const first = await sparklineService.loadMany(items);
    const second = await sparklineService.loadMany(items);

    expect(mocks.apiRequest).toHaveBeenCalledTimes(1);
    expect(mocks.apiRequest.mock.calls[0][0]).toBe('/api/sparklines');
    expect(mocks.apiRequest.mock.calls[0][1]).toMatchObject({ method: 'POST' });
    expect(first.get('global:NASDAQ:TEST1')).toEqual([1, 2]);
    expect(second.get('global:NASDAQ:TEST3')).toEqual([5, 6]);
    expect(mocks.getCandles).not.toHaveBeenCalled();
  });

  it('force refresh requests the batch again', async () => {
    const items = [item(1)];
    mocks.apiRequest.mockResolvedValue({
      items: { 'global:NASDAQ:TEST1': { closes: [1] } },
    });

    await sparklineService.loadMany(items);
    await sparklineService.loadMany(items, { force: true });

    expect(mocks.apiRequest).toHaveBeenCalledTimes(2);
  });

  it('falls back to bounded individual requests when the batch endpoint fails', async () => {
    const items = Array.from({ length: 6 }, (_, index) => item(index + 1));
    mocks.apiRequest.mockRejectedValue(new Error('batch unavailable'));
    let active = 0;
    let maxActive = 0;
    const resolvers: Array<() => void> = [];
    mocks.getCandles.mockImplementation(() => {
      active += 1;
      maxActive = Math.max(maxActive, active);
      return new Promise((resolve) => {
        resolvers.push(() => {
          active -= 1;
          resolve({ candles: [{ close: 1 }] });
        });
      });
    });

    const pending = sparklineService.loadMany(items);
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(resolvers.length).toBe(4);
    expect(maxActive).toBeLessThanOrEqual(4);

    while (resolvers.length > 0) {
      const wave = resolvers.splice(0);
      wave.forEach((resolve) => resolve());
      await new Promise((resolve) => setTimeout(resolve, 0));
    }
    const snapshot = await pending;

    expect(maxActive).toBeLessThanOrEqual(4);
    expect(mocks.getCandles).toHaveBeenCalledTimes(6);
    expect(snapshot.size).toBe(6);
  });

  it('removes entries for instruments that left the watchlist', async () => {
    const items = [item(1), item(2)];
    mocks.apiRequest.mockResolvedValue({
      items: {
        'global:NASDAQ:TEST1': { closes: [1] },
        'global:NASDAQ:TEST2': { closes: [2] },
      },
    });
    await sparklineService.loadMany(items);

    sparklineService.prune([item(1)]);

    expect(sparklineService.get('global:NASDAQ:TEST1')).toEqual([1]);
    expect(sparklineService.get('global:NASDAQ:TEST2')).toBeUndefined();
  });
});
