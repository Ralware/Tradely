export interface StrategyReference {
  state?: string;
  direction?: string | null;
  entry_reference?: number | null;
  stop_reference?: number | null;
  risk_per_unit?: number | null;
  explanation?: string;
  [key: string]: unknown;
}

export function suppressStaleStrategy(strategy: object): StrategyReference {
  return {
    ...strategy,
    state: 'STALE_DATA',
    direction: null,
    entry_reference: null,
    stop_reference: null,
    risk_per_unit: null,
    explanation: 'The previous strategy output is suppressed because fresh market data could not be obtained. This snapshot is retained for reference only and requires a successful refresh.',
  };
}
