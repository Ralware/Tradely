/**
 * Lightweight, development-only cache instrumentation.
 *
 * Counters are always collected (cheap) so the browser console can inspect
 * them at any time. Verbose per-event logging is opt-in:
 *
 *   localStorage.setItem('tradely:cache-debug', '1')
 *   window.__tradelyCache?.stats()
 *
 * This is intentionally not wired into production logging; it exists to make
 * cache hits, misses, deduplicated requests and background refreshes visible
 * while diagnosing navigation behaviour.
 */
export type CacheEventName =
  | 'hit'
  | 'miss'
  | 'request'
  | 'dedupe'
  | 'background-refresh'
  | 'invalidate'
  | 'cancel'
  | 'prefetch'
  | 'store'
  | 'skip';

const counters = new Map<CacheEventName, number>();
const DEV = import.meta.env.DEV;

function debugEnabled(): boolean {
  if (!DEV || typeof window === 'undefined') return false;
  try {
    return window.localStorage.getItem('tradely:cache-debug') === '1';
  } catch {
    return false;
  }
}

export function cacheEvent(
  event: CacheEventName,
  detail?: Record<string, unknown>,
): void {
  counters.set(event, (counters.get(event) ?? 0) + 1);
  if (debugEnabled()) {
    // eslint-disable-next-line no-console
    console.debug(`[tradely-cache] ${event}`, detail ?? '');
  }
}

export function cacheStats(): Record<string, number> {
  return Object.fromEntries(counters);
}

export function resetCacheStats(): void {
  counters.clear();
}

type CacheDebugWindow = Window & {
  __tradelyCache?: {
    stats: () => Record<string, number>;
    reset: () => void;
    enable: () => void;
    disable: () => void;
  };
};

if (DEV && typeof window !== 'undefined') {
  (window as CacheDebugWindow).__tradelyCache = {
    stats: cacheStats,
    reset: resetCacheStats,
    enable: () => {
      try {
        window.localStorage.setItem('tradely:cache-debug', '1');
      } catch {
        // Storage can be unavailable in private modes.
      }
    },
    disable: () => {
      try {
        window.localStorage.removeItem('tradely:cache-debug');
      } catch {
        // Storage can be unavailable in private modes.
      }
    },
  };
}
