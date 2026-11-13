import { apiRequest } from './api';
import type { BacktestRequest, BacktestResult } from '../types/api';

export const backtestService = {
  run(payload: BacktestRequest, signal?: AbortSignal): Promise<BacktestResult> {
    return apiRequest<BacktestResult>('/api/backtests/trend-breakout', {
      method: 'POST',
      body: payload,
      signal,
      timeoutMs: 180_000,
    });
  },
};
