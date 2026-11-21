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

  it('prepares every alternate timeframe using the configured history window', async () => {
    stubBrowser();
    const fetchMock = stubFetch();

    await analysisService.prefetchTimeframes(
      { instrumentId, interval: '1d', days: 500 },
      ['1wk', '1mo', '1h'],
    );

    expect(fetchMock).toHaveBeenCalledTimes(3);
    const requestedUrls = fetchMock.mock.calls.map(([input]) => new URL(String(input), 'http://localhost'));
    expect(requestedUrls.map((url) => url.searchParams.get('interval')).sort()).toEqual(['1h', '1mo', '1wk']);
    expect(requestedUrls.map((url) => url.searchParams.get('days')).sort()).toEqual(['1825', '365', '3650']);
    expect(requestedUrls.every((url) => url.pathname.endsWith('/analytics-snapshot'))).toBe(true);
    expect(requestedUrls.every((url) => url.searchParams.get('prefetch') === 'true')).toBe(true);
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

  it('uses the TradingView v3 technical-ratings endpoint', async () => {
    stubBrowser();
    const fetchMock = stubFetch();
    await analysisService.getTechnicals({ instrumentId, interval: '1h', days: 365 });
    const url = new URL(String(fetchMock.mock.calls[0][0]), 'http://localhost');
    expect(url.pathname).toBe(`/api/instruments/${encodeURIComponent(instrumentId)}/technical-ratings`);
    expect(url.searchParams.get('interval')).toBe('1h');
  });

  it('exposes a prepared analytics snapshot synchronously from the exact timeframe cache key', async () => {
    stubBrowser();
    const fetchMock = stubFetch();
    const query = { instrumentId, interval: '4h', days: 365 };

    await analysisService.getAnalyticsSnapshot(query);

    expect(analysisService.getCachedAnalyticsSnapshot(query)?.interval).toBe('4h');
    expect(analysisService.getCachedAnalyticsSnapshot({ ...query, interval: '1h' })).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('requests a forced server refresh for an analytics snapshot', async () => {
    stubBrowser();
    const fetchMock = stubFetch();
    await analysisService.getAnalyticsSnapshot(
      { instrumentId, interval: '1d', days: 3650 },
      undefined,
      { forceRefresh: true },
    );
    const url = new URL(String(fetchMock.mock.calls[0][0]), 'http://localhost');
    expect(url.pathname.endsWith('/analytics-snapshot')).toBe(true);
    expect(url.searchParams.get('refresh')).toBe('true');
    expect(url.searchParams.get('direction_mode')).toBe('long_only');
  });


  it('limits background timeframe preparation to two active jobs', async () => {
    stubBrowser();
    let active = 0;
    let maximumActive = 0;
    const fetchMock = vi.fn().mockImplementation(() => new Promise((resolve) => {
      active += 1;
      maximumActive = Math.max(maximumActive, active);
      setTimeout(() => {
        active -= 1;
        resolve({
          ok: true,
          status: 200,
          statusText: 'OK',
          text: async () => JSON.stringify({ source: 'test-provider', is_adjusted: true }),
        });
      }, 15);
    }));
    vi.stubGlobal('fetch', fetchMock);

    await analysisService.prefetchTimeframes(
      { instrumentId, interval: '1d', days: 3650 },
      ['1m', '5m', '15m', '1h'],
    );

    expect(fetchMock).toHaveBeenCalledTimes(4);
    expect(maximumActive).toBe(2);
  });

  it('continues preparing other intervals when one timeframe fails', async () => {
    stubBrowser();
    const fetchMock = vi.fn().mockImplementation((input: RequestInfo | URL) => {
      const url = new URL(String(input), 'http://localhost');
      const failed = url.searchParams.get('interval') === '1wk';
      return Promise.resolve({
        ok: !failed,
        status: failed ? 502 : 200,
        statusText: failed ? 'Bad Gateway' : 'OK',
        text: async () => JSON.stringify(failed ? { detail: 'provider timeout' } : { source: 'test-provider', is_adjusted: true }),
      });
    });
    vi.stubGlobal('fetch', fetchMock);

    const result = await analysisService.prefetchTimeframes(
      { instrumentId, interval: '1d', days: 3650 },
      ['1wk', '1mo', '1h'],
    );

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(result.completed).toBe(3);
    expect(result.failures).toEqual([{ interval: '1wk', error: 'provider timeout' }]);
  });

});
