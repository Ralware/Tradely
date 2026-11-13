import { apiRequest } from './api';
import type { RiskRequest, RiskResult } from '../types/api';

export const riskService = {
  calculate(payload: RiskRequest): Promise<RiskResult> {
    return apiRequest<RiskResult>('/api/risk/position-size', {
      method: 'POST',
      body: payload,
      timeoutMs: 15_000,
    });
  },
};
