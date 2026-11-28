import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { CandlesResponse } from '../types/api';

const mocks = vi.hoisted(() => ({
  apiRequest: vi.fn(),
}));

vi.mock('./api', () => ({ apiRequest: mocks.apiRequest }));

import { marketService } from './marketService';

const response = {
  symbol: 'BTCUSDT',
  market: 'crypto',
  exchange: 'BINANCE',
  interval: '1m',
  source: 'tradingview',
  is_adjusted: null,
  freshness: 'provider-dependent',
  is_stale: false,
  history_truncated: false,
  history_pages: 1,
  last_candle_at: '2026-11-27T18:00:00Z',
  count: 0,
  candles: [],
  warnings: [],
} as unknown as CandlesResponse;

beforeEach(() => {
  marketService.invalidateCandles();
  vi.clearAllMocks();
  mocks.apiRequest.mockResolvedValue(response);
});

describe('marketService.getCandles', () => {
  it('passes the abort signal and poll timeout through to the request', async () => {
    const controller = new AbortController();
    await marketService.getCandles(
      { instrumentId: 'crypto:BINANCE:BTCUSDT', interval: '1m', days: 7, refreshLatest: true },
      controller.signal,
      { force: true, refreshLatest: true, timeoutMs: 8_000 },
    );

    expect(mocks.apiRequest).toHaveBeenCalledWith(
      '/api/market/candles',
      expect.objectContaining({
        signal: controller.signal,
        timeoutMs: 8_000,
      }),
    );
  });

  it('rejects an already-aborted signal without starting a request', async () => {
    const controller = new AbortController();
    controller.abort();

    await expect(marketService.getCandles(
      { instrumentId: 'crypto:BINANCE:BTCUSDT', interval: '1m' },
      controller.signal,
      { force: true },
    )).rejects.toMatchObject({ name: 'AbortError' });
    expect(mocks.apiRequest).not.toHaveBeenCalled();
  });

  it('honors an abort while the request is in flight', async () => {
    mocks.apiRequest.mockImplementation((_path: string, options: { signal?: AbortSignal }) => (
      new Promise((_resolve, reject) => {
        options.signal?.addEventListener('abort', () => {
          reject(new DOMException('aborted', 'AbortError'));
        });
      })
    ));
    const controller = new AbortController();
    const pending = marketService.getCandles(
      { instrumentId: 'crypto:BINANCE:BTCUSDT', interval: '1m' },
      controller.signal,
      { force: true },
    );
    controller.abort();

    await expect(pending).rejects.toMatchObject({ name: 'AbortError' });
  });
});
