import { afterEach, describe, expect, it, vi } from 'vitest';
import { analysisService } from './analysisService';

const instrumentId = 'global:NASDAQ:AAPL';

function stubBrowser() {
  vi.stubGlobal('window', { setTimeout, clearTimeout });
}

function stubFetch() {
  const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
    const url = new URL(String(input), 'http://localhost');
    return Promise.resolve({
      ok: true,
      status: 200,
      statusText: 'OK',
      text: async () => JSON.stringify({
        source: 'test-provider',
        is_adjusted: true,
        interval: url.searchParams.get('interval'),
      }),
    });
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

afterEach(() => {
  analysisService.invalidateInstrumentCache(instrumentId);
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('market analysis cache', () => {
  it('keys analysis by instrument, timeframe, and strategy direction', async () => {
    stubBrowser();
    const fetchMock = stubFetch();
    const query = { instrumentId, interval: '1d', days: 500 };

    await analysisService.getAnalysis(query);
    await analysisService.getAnalysis(query);
    await analysisService.getAnalysis({ ...query, directionMode: 'short_only' });
    await analysisService.getAnalysis({ ...query, interval: '1wk', days: 1825 });

    expect(fetchMock).toHaveBeenCalledTimes(3);
    const requestedUrls = fetchMock.mock.calls.map(
      ([input]) => new URL(String(input), 'http://localhost'),
    );
    expect(requestedUrls[0].searchParams.get('direction_mode')).toBe('long_only');
    expect(requestedUrls[1].searchParams.get('direction_mode')).toBe('short_only');
  });

  it('prefetches only a bounded number of alternate timeframes', async () => {
    stubBrowser();
    const fetchMock = stubFetch();

    await analysisService.prefetchTimeframes(
      { instrumentId, interval: '1d', days: 500 },
      ['1wk', '1mo', '1h'],
    );

    expect(fetchMock).toHaveBeenCalledTimes(2);
    const requestedUrls = fetchMock.mock.calls.map(([input]) => new URL(String(input), 'http://localhost'));
    expect(requestedUrls.map((url) => url.searchParams.get('interval'))).toEqual(['1wk', '1mo']);
    expect(requestedUrls.map((url) => url.searchParams.get('days'))).toEqual(['1825', '3650']);
  });

  it('does not start prefetch requests after the instrument scope is cancelled', async () => {
    stubBrowser();
    const fetchMock = stubFetch();
    const controller = new AbortController();
    controller.abort();

    await analysisService.prefetchTimeframes(
      { instrumentId, interval: '1d', days: 500 },
      ['1wk', '1mo'],
      controller.signal,
    );

    expect(fetchMock).not.toHaveBeenCalled();
  });
});
