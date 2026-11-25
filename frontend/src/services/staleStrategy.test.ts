import { describe, expect, it } from 'vitest';
import { suppressStaleStrategy } from './staleStrategy';

describe('suppressStaleStrategy', () => {
  it('clears direction, entry, stop, and risk while preserving non-actionable context', () => {
    const result = suppressStaleStrategy({
      state: 'BUY', direction: 'LONG', entry_reference: 100,
      stop_reference: 95, risk_per_unit: 5, strategy: 'Trend breakout',
    });
    expect(result).toMatchObject({
      state: 'STALE_DATA', direction: null, entry_reference: null,
      stop_reference: null, risk_per_unit: null, strategy: 'Trend breakout',
    });
    expect(result.explanation).toContain('retained for reference only');
  });
});
