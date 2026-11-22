import { apiRequest } from './api';
import { snapshotDatabase } from './snapshotDatabase';
import type { PreparedSnapshot, SnapshotManifestItem } from './snapshotStore';
import { snapshotStore } from './snapshotStore';

type ManifestResponse = { items: SnapshotManifestItem[] };
type WatchlistResponse = { items: Array<{ instrument_id?: string }> };
type Progress = { phase: 'idle' | 'manifest' | 'hydrating' | 'ready' | 'error'; total: number; completed: number; errors: string[]; startedAt?: number; durationMs?: number };
const listeners = new Set<() => void>();
let progress: Progress = { phase: 'idle', total: 0, completed: 0, errors: [] };
let started: Promise<void> | undefined;
let refreshTimer: number | undefined;
const notify = () => listeners.forEach((listener) => listener());
function setProgress(next: Progress): void { progress = next; notify(); }

async function runPool<T>(items: T[], concurrency: number, task: (item: T) => Promise<void>): Promise<void> {
  let index = 0;
  await Promise.all(Array.from({ length: Math.min(concurrency, items.length) }, async () => {
    while (index < items.length) { const item = items[index++]; if (item !== undefined) await task(item); }
  }));
}

async function synchronize(): Promise<void> {
  setProgress({ phase: 'manifest', total: 0, completed: 0, errors: [], startedAt: Date.now() });
  try {
    const [watchlist, manifest] = await Promise.all([
      apiRequest<WatchlistResponse>('/api/watchlist'),
      apiRequest<ManifestResponse>('/api/analytics/precomputed/index'),
    ]);
    snapshotStore.setManifest(manifest.items ?? []);
    const watched = new Set((watchlist.items ?? []).map((item) => item.instrument_id).filter((id): id is string => Boolean(id)));
    const items = (manifest.items ?? []).filter((item) => watched.has(item.instrument_id));
    let completed = 0;
    const errors: string[] = [];
    setProgress({ phase: 'hydrating', total: items.length, completed, errors, startedAt: Date.now() });
    await runPool(items, 2, async (item) => {
      try {
        const local = await snapshotDatabase.get(item.instrument_id, item.interval);
        if (local && local.fingerprint === item.fingerprint) {
          snapshotStore.setSnapshot(item.instrument_id, item.interval, local.payload);
        } else if (item.status === 'READY' && item.fingerprint) {
          const payload = await apiRequest<PreparedSnapshot>(
            `/api/analytics/precomputed/${encodeURIComponent(item.instrument_id)}/${encodeURIComponent(item.interval)}`,
            { timeoutMs: 90_000 },
          );
          if (payload.fingerprint !== item.fingerprint) throw new Error('Manifest/snapshot fingerprint mismatch');
          const bundle = { instrumentId: item.instrument_id, interval: item.interval,
            fingerprint: item.fingerprint, schemaVersion: Number(payload.schema_version ?? 1),
            syncedAt: new Date().toISOString(), payload };
          await snapshotDatabase.put(bundle);
          snapshotStore.setSnapshot(item.instrument_id, item.interval, payload);
        }
      } catch (error) {
        errors.push(`${item.instrument_id} ${item.interval}: ${error instanceof Error ? error.message : String(error)}`);
      } finally {
        completed += 1;
        setProgress({ phase: 'hydrating', total: items.length, completed, errors: [...errors], startedAt: progress.startedAt });
      }
    });
    setProgress({ phase: errors.length ? 'error' : 'ready', total: items.length, completed,
      errors, startedAt: progress.startedAt, durationMs: Date.now() - (progress.startedAt ?? Date.now()) });
  } catch (error) {
    setProgress({ ...progress, phase: 'error', errors: [error instanceof Error ? error.message : String(error)] });
  }
}

export const snapshotHydrator = {
  start(): Promise<void> {
    if (!started) {
      started = synchronize();
      // Manifest polling is application-scoped, not tied to Analytics navigation.
      refreshTimer = window.setInterval(() => { void synchronize(); }, 60_000);
    }
    return started;
  },
  refresh(): Promise<void> { started = synchronize(); return started; },
  getProgress(): Progress { return progress; },
  subscribe(listener: () => void): () => void { listeners.add(listener); return () => listeners.delete(listener); },
  stop(): void { if (refreshTimer !== undefined) window.clearInterval(refreshTimer); refreshTimer = undefined; },
};
