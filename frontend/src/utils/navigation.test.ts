import { describe, expect, it } from 'vitest';
import { analysisPath, instrumentIdFromLegacy, instrumentPath } from './navigation';

describe('navigation utilities', () => {
  it('builds canonical analysis path for crypto', () => {
    const path = instrumentPath({
      instrument_id: 'crypto:BINANCE:BTCUSDT',
      market: 'crypto',
    });
    expect(path).toBe('/analysis?instrument=crypto%3ABINANCE%3ABTCUSDT');
  });

  it('builds canonical analysis path with interval and days', () => {
    const path = instrumentPath(
      { instrument_id: 'global:NASDAQ:AAPL', market: 'global' },
      { interval: '1h', days: 30 },
    );
    expect(path).toBe('/analysis?instrument=global%3ANASDAQ%3AAAPL&interval=1h&days=30');
  });

  it('resolves legacy identifiers into canonical IDs', () => {
    expect(instrumentIdFromLegacy('reliance', 'india', 'nse')).toBe('india:NSE:RELIANCE');
    expect(instrumentIdFromLegacy('aapl', 'global', 'nasdaq')).toBe('global:NASDAQ:AAPL');
    expect(instrumentIdFromLegacy('btcusdt', 'crypto')).toBe('crypto:BINANCE:BTCUSDT');
  });

  it('redirects legacy analysisPath directly to unified analysis route', () => {
    const path = analysisPath('BTCUSDT', 'crypto');
    expect(path).toBe('/analysis?symbol=BTCUSDT&market=crypto');
  });
});
