import { beforeEach, describe, expect, it, vi } from 'vitest';
import { apiRequest } from './api';
import { newsService } from './newsService';
import type { NewsFeedResponse, NewsSearchResponse } from './newsService';

vi.mock('./api', () => ({ apiRequest: vi.fn() }));
const requestMock = vi.mocked(apiRequest);

const emptyFeed: NewsFeedResponse = {
  items: [], count: 0, page: 1, page_size: 5, stale: false,
  symbol: 'TEST', yahoo_symbol: 'TEST',
};

describe('newsService', () => {
  beforeEach(() => requestMock.mockReset());

  it('sends canonical identity and date filters and keeps selected-feed caches isolated', async () => {
    requestMock.mockResolvedValue(emptyFeed);
    const instrumentId = 'global:NASDAQ:NEWS-TEST-1';
    const filters = { page: 1, pageSize: 5, dateFrom: '2025-01-01', dateTo: '2025-01-31' };

    await newsService.symbolFeed(instrumentId, 'TEST', filters);

    expect(requestMock).toHaveBeenCalledWith('/api/news/TEST', expect.objectContaining({
      query: {
        instrument_id: instrumentId, page: 1, page_size: 5,
        q: undefined, date_from: '2025-01-01', date_to: '2025-01-31',
      },
      timeoutMs: 15_000,
    }));
    expect(newsService.cachedSymbol(instrumentId, 1, 5, filters)).toEqual(emptyFeed);
    expect(newsService.cachedSymbol(instrumentId, 1, 5)).toBeUndefined();
  });

  it('searches supported Yahoo Finance listings through the backend service', async () => {
    const result: NewsSearchResponse = {
      query: 'Acme', count: 1, provider: 'Yahoo Finance',
      items: [{
        instrument_id: 'global:NASDAQ:ACME', symbol: 'ACME', yahoo_symbol: 'ACME',
        name: 'Acme Corporation', exchange: 'NASDAQ', market: 'global',
        instrument_type: 'Equity', instrument: {} as NewsSearchResponse['items'][number]['instrument'],
      }],
    };
    requestMock.mockResolvedValue(result);

    await expect(newsService.search('Acme')).resolves.toEqual(result);
    expect(requestMock).toHaveBeenCalledWith('/api/news/search', expect.objectContaining({
      query: { q: 'Acme' }, timeoutMs: 12_000,
    }));
  });
});
