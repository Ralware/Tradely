import { afterEach, describe, expect, it, vi } from 'vitest';
import type { TransactionRequest } from '../types/api';
import { portfolioService } from './portfolioService';

const request: TransactionRequest = {
  instrument_id: 'crypto:BINANCE:BTCUSDT',
  side: 'BUY',
  amount: 100,
  currency: 'USDT',
  fees: 0,
  trade_time: '2026-02-01T09:30:00.000Z',
  notes: null,
  idempotency_key: 'preview-key-1',
};

function stubBrowser() {
  // apiRequest uses window timers; vitest runs in a Node environment here.
  vi.stubGlobal('window', { setTimeout, clearTimeout });
}

function stubFetch(payload: unknown) {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    statusText: 'OK',
    text: async () => JSON.stringify(payload),
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('amount-based transaction client', () => {
  it('sends previews to the server-authoritative preview endpoint', async () => {
    stubBrowser();
    const fetchMock = stubFetch({
      valid: true,
      error: null,
      quantity: 0.001,
      actual_amount: 100,
      requested_amount: 100,
    });

    const preview = await portfolioService.previewTransaction(request);

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/portfolio/transactions/preview');
    expect(init.method).toBe('POST');
    expect(JSON.parse(String(init.body))).toMatchObject({
      instrument_id: 'crypto:BINANCE:BTCUSDT',
      side: 'BUY',
      amount: 100,
      currency: 'USDT',
      fees: 0,
      trade_time: '2026-02-01T09:30:00.000Z',
    });
    expect(preview.quantity).toBe(0.001);
  });

  it('posts amounts without quantity or price fields and keeps the idempotency key', async () => {
    stubBrowser();
    const fetchMock = stubFetch({
      transaction: { id: 1, side: 'BUY', quantity: 0.001, price: 100000 },
      duplicate: false,
      positions: [],
      transactions: [],
    });

    await portfolioService.addTransaction(request);

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/portfolio/transactions');
    const body = JSON.parse(String(init.body)) as Record<string, unknown>;
    expect(body.amount).toBe(100);
    expect(body.idempotency_key).toBe('preview-key-1');
    expect(body).not.toHaveProperty('quantity');
    expect(body).not.toHaveProperty('price');
  });

  it('rejects a partial preview from the server', async () => {
    stubBrowser();
    stubFetch({ valid: false, error: 'Sell amount exceeds the available holdings market value' });

    const preview = await portfolioService.previewTransaction(request);

    expect(preview.valid).toBe(false);
    expect(preview.error).toContain('exceeds the available holdings');
  });
});
