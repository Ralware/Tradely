import { apiRequest } from './api';
import { cacheEvent } from './cacheDiagnostics';
import { marketService } from './marketService';
import type { WatchlistItem } from '../types/api';
import { watchlistItemKey } from '../utils/watchlistSort';

/**
 * Watchlist sparklines are 24 hours of hourly closes. The cache lives outside
 * React so navigating away and back reuses the same series instead of issuing
 * one candle request per instrument again.
 *
 * Missing entries are requested through one batched backend call. The backend
 * bounds its provider fan-out, and the market candle cache coalesces any
 * overlap with an Analytics chart request for the same instrument.
 */
const SPARKLINE_TTL_MS = 5 * 60_000;
const FALLBACK_CONCURRENCY = 4;
const BATCH_LIMIT = 100;

type SparklineEntry = { values: number[]; fetchedAt: number };
type BatchResponse = {
  items?: Record<string, { closes?: number[] }>;
  errors?: Record<string, string>;
};

const sparklineCache = new Map<string, SparklineEntry>();
const inFlight = new Map<string, Promise<number[]>>();

function fresh(entry: SparklineEntry | undefined): entry is SparklineEntry {
  return Boolean(entry) && Date.now() - entry!.fetchedAt < SPARKLINE_TTL_MS;
}

function store(key: string, values: number[]): void {
  if (values.length === 0) return;
  sparklineCache.set(key, { values, fetchedAt: Date.now() });
  cacheEvent('store', { kind: 'sparkline', key });
}

async function loadOne(item: WatchlistItem, force: boolean): Promise<number[]> {
  const key = watchlistItemKey(item);
  const cached = sparklineCache.get(key);
  if (!force && fresh(cached)) {
    cacheEvent('hit', { kind: 'sparkline', key });
    return cached.values;
  }
  if (force) sparklineCache.delete(key);

  const requestKey = force ? `${key}\u0000force` : key;
  const pending = inFlight.get(requestKey);
  if (pending) {
    cacheEvent('dedupe', { kind: 'sparkline', key });
    return pending;
  }

  cacheEvent('request', { kind: 'sparkline', key, force });
  let request: Promise<number[]>;
  request = marketService
    .getCandles(
      {
        instrumentId: item.instrument_id,
        symbol: item.symbol,
        market: item.market,
        exchange: item.exchange,
        interval: '1h',
        days: 1,
      },
      undefined,
      { force },
    )
    .then((response) => {
      const closes = (response.candles ?? []).map((candle) => candle.close);
      store(key, closes);
      return closes;
    })
    .finally(() => {
      if (inFlight.get(requestKey) === request) inFlight.delete(requestKey);
    });
  inFlight.set(requestKey, request);
  return request;
}

async function runBounded<T>(
  items: T[],
  concurrency: number,
  task: (item: T) => Promise<void>,
): Promise<void> {
  let index = 0;
  await Promise.all(
    Array.from({ length: Math.min(concurrency, items.length) }, async () => {
      while (index < items.length) {
        const item = items[index++];
        if (item !== undefined) await task(item);
      }
    }),
  );
}

async function loadBatch(items: WatchlistItem[]): Promise<Set<string>> {
  const loaded = new Set<string>();
  const requestItems = items
    .filter((item) => item.instrument_id)
    .slice(0, BATCH_LIMIT);
  if (requestItems.length === 0) return loaded;
  cacheEvent('request', { kind: 'sparkline-batch', key: `${requestItems.length}` });
  const response = await apiRequest<BatchResponse>('/api/sparklines', {
    method: 'POST',
    body: {
      instrument_ids: requestItems.map((item) => item.instrument_id),
      interval: '1h',
      days: 1,
    },
    timeoutMs: 90_000,
  });
  for (const item of requestItems) {
    const id = item.instrument_id;
    if (!id) continue;
    const closes = response.items?.[id]?.closes;
    if (Array.isArray(closes) && closes.length > 0) {
      store(watchlistItemKey(item), closes);
      loaded.add(id);
    }
  }
  return loaded;
}

export const sparklineService = {
  get(key: string): number[] | undefined {
    return sparklineCache.get(key)?.values;
  },

  getSnapshot(items: WatchlistItem[]): Map<string, number[]> {
    const snapshot = new Map<string, number[]>();
    for (const item of items) {
      const key = watchlistItemKey(item);
      const entry = sparklineCache.get(key);
      if (entry) snapshot.set(key, entry.values);
    }
    return snapshot;
  },

  async loadMany(
    items: WatchlistItem[],
    options: { force?: boolean } = {},
  ): Promise<Map<string, number[]>> {
    const force = Boolean(options.force);
    if (force) {
      for (const item of items) sparklineCache.delete(watchlistItemKey(item));
    }
    const missing = items.filter((item) => {
      const entry = sparklineCache.get(watchlistItemKey(item));
      return force || !fresh(entry);
    });
    if (missing.length === 0) return this.getSnapshot(items);

    let loaded = new Set<string>();
    try {
      loaded = await loadBatch(missing);
    } catch {
      // Fall back to individual cached requests when the batch endpoint is
      // unavailable. Concurrency stays bounded so a large watchlist cannot
      // create an unbounded request burst.
    }
    const remaining = missing.filter(
      (item) => !item.instrument_id || !loaded.has(item.instrument_id),
    );
    await runBounded(remaining, FALLBACK_CONCURRENCY, async (item) => {
      try {
        await loadOne(item, force);
      } catch {
        // A single unavailable sparkline must not block the rest.
      }
    });
    return this.getSnapshot(items);
  },

  prune(items: WatchlistItem[]): void {
    const allowed = new Set(items.map(watchlistItemKey));
    for (const key of sparklineCache.keys()) {
      if (!allowed.has(key)) sparklineCache.delete(key);
    }
  },

  invalidate(key?: string): void {
    if (key) {
      sparklineCache.delete(key);
      return;
    }
    sparklineCache.clear();
    cacheEvent('invalidate', { kind: 'sparkline' });
  },
};
