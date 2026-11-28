import type { Candle, Market } from '../../types/api';
import {
  isActiveInterval,
  type CandleStatus,
  type LiveCandleEntry,
} from './candleReconcile';

const MAX_CACHED_LIVE_BARS = 1_000;
const MAX_CACHED_CHARTS = 50;
const cache = new Map<string, Map<number, LiveCandleEntry>>();

function sortedEntries(entries: Map<number, LiveCandleEntry>): LiveCandleEntry[] {
  return [...entries.values()].sort((left, right) => left.time - right.time);
}

function touch(key: string): Map<number, LiveCandleEntry> {
  const existing = cache.get(key);
  if (existing) {
    // Refresh LRU order on access.
    cache.delete(key);
    cache.set(key, existing);
    return existing;
  }
  const created = new Map<number, LiveCandleEntry>();
  cache.set(key, created);
  return created;
}

function evictOldCharts(): void {
  while (cache.size > MAX_CACHED_CHARTS) {
    const oldestKey = cache.keys().next().value;
    if (!oldestKey) break;
    cache.delete(oldestKey);
  }
}

function shouldReplace(existing: LiveCandleEntry, incoming: LiveCandleEntry): boolean {
  // Finalization is a lifecycle upgrade, not a fetch-order decision. A final
  // bar always wins over a forming bar, even after a sequence reset on remount.
  if (existing.status !== incoming.status) return incoming.status === 'final';
  if (incoming.sequence !== existing.sequence) return incoming.sequence > existing.sequence;
  return incoming.updatedAt >= existing.updatedAt;
}

/** Restore live entries for one instrument + timeframe, newest last. */
export function getCachedLiveCandles(key: string): LiveCandleEntry[] | undefined {
  const entries = cache.get(key);
  if (!entries) return undefined;
  touch(key);
  return sortedEntries(entries);
}

/** Replace the live state for one instrument + timeframe. */
export function setCachedLiveCandles(key: string, entries: LiveCandleEntry[]): void {
  const target = touch(key);
  target.clear();
  for (const entry of entries.slice(-MAX_CACHED_LIVE_BARS)) {
    const existing = target.get(entry.time);
    if (!existing || shouldReplace(existing, entry)) {
      target.set(entry.time, entry);
    }
  }
  evictOldCharts();
}

/** Timestamp-keyed upsert with finalized-wins semantics. */
export function upsertCachedLiveCandle(key: string, entry: LiveCandleEntry): void {
  const target = touch(key);
  const existing = target.get(entry.time);
  if (!existing || shouldReplace(existing, entry)) {
    target.set(entry.time, entry);
    while (target.size > MAX_CACHED_LIVE_BARS) {
      const oldest = [...target.keys()].sort((left, right) => left - right)[0];
      if (oldest === undefined) break;
      target.delete(oldest);
    }
  }
  evictOldCharts();
}

export interface PruneLiveCandlesOptions {
  interval: string;
  market?: Market;
  now?: number;
  finalizedTimes?: Iterable<number>;
}

/**
 * Expire forming entries once their bar is finalized or their interval ends.
 * Finalized entries stay final; they are never resurrected as forming.
 */
export function pruneCachedLiveCandles(
  key: string,
  options: PruneLiveCandlesOptions,
): void {
  const entries = cache.get(key);
  if (!entries) return;
  const now = options.now ?? Math.floor(Date.now() / 1000);
  const finalized = new Set(options.finalizedTimes ?? []);
  for (const [time, entry] of entries) {
    if (entry.status !== 'forming') continue;
    if (finalized.has(time) || !isActiveInterval(time, options.interval, options.market, now)) {
      entries.delete(time);
    }
  }
  touch(key);
}

export function clearCachedLiveCandles(): void {
  cache.clear();
}

/** Convenience constructor used by the chart when persisting reconciled output. */
export function liveEntry(
  candle: Candle,
  time: number,
  status: CandleStatus,
  interval: string,
  sequence: number,
  updatedAt = Date.now(),
): LiveCandleEntry {
  return { candle, time, status, interval, sequence, updatedAt };
}
