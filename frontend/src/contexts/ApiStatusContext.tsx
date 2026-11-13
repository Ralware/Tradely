import { createContext, useCallback, useContext, useMemo } from 'react';
import type { ReactNode } from 'react';
import { useApi } from '../hooks/useApi';
import { marketService } from '../services/marketService';
import type { HealthResponse, ProvidersResponse } from '../types/api';

interface ApiStatusValue {
  health: HealthResponse | null;
  healthLoading: boolean;
  healthError: string | null;
  providers: ProvidersResponse | null;
  providersLoading: boolean;
  providersError: string | null;
  refresh: () => void;
}

const ApiStatusContext = createContext<ApiStatusValue | null>(null);

export function ApiStatusProvider({ children }: { children: ReactNode }) {
  const health = useApi((signal) => marketService.getHealth(signal), []);
  const providers = useApi((signal) => marketService.getProviders(signal), []);

  const refresh = useCallback(() => {
    health.reload();
    providers.reload();
  }, [health, providers]);

  const value = useMemo<ApiStatusValue>(
    () => ({
      health: health.data,
      healthLoading: health.loading,
      healthError: health.error,
      providers: providers.data,
      providersLoading: providers.loading,
      providersError: providers.error,
      refresh,
    }),
    [health, providers, refresh],
  );

  return <ApiStatusContext.Provider value={value}>{children}</ApiStatusContext.Provider>;
}

export function useApiStatus(): ApiStatusValue {
  const context = useContext(ApiStatusContext);
  if (!context) {
    throw new Error('useApiStatus must be used inside ApiStatusProvider');
  }
  return context;
}
