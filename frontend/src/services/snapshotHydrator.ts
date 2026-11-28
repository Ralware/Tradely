import { apiRequest } from './api';
import { ANALYTICS_SCHEMA_VERSION, isCompleteSnapshot } from './analyticsSnapshotLoader';
import { portfolioService } from './portfolioService';
import { snapshotDatabase } from './snapshotDatabase';
import type { PreparedSnapshot, SnapshotManifestItem } from './snapshotStore';
import { snapshotStore } from './snapshotStore';

type ManifestResponse = { items: SnapshotManifestItem[] };
type Progress = {
  phase: 'idle' | 'manifest' | 'hydrating' | 'ready' | 'error';
  total: number;
  completed: number;
  errors: string[];
  startedAt?: number;
  durationMs?: number;
};

const listeners = new Set<() => void>();
let progress: Progress = { phase: 'idle', total: 0, completed: 0, errors: [] };
let started: Promise<void> | undefined;
let refreshTimer: ReturnType<typeof setInterval> | undefined;
let syncing: Promise<void> | undefined;
let lastSyncAt = 0;
let generation = 0;
let visibilityBound = false;

/** Fingerprint last synchronized for each identity. Unchanged entries are
 * skipped entirely on later polls, including their IndexedDB reads. */
const lastSynced = new Map<string, string>();
/** In-flight downloads keyed by identity, so two pollers share one request. */
const downloadInFlight = new Map<string, Promise<PreparedSnapshot>>();

const notify = () => listeners.forEach((listener) => listener());
function setProgress(next: Progress): void {
  progress = next;
  notify();
}
function identityKey(instrumentId: string, interval: string): string {
  return `${instrumentId}\u0000${interval}`;
}

async function runPool<T>(
  items: T[],
  concurrency: number,
  task: (item: T, index: number) => Promise<void>,
): Promise<void> {
  let index = 0;
  await Promise.all(
    Array.from({ length: Math.min(concurrency, items.length) }, async () => {
      while (index < items.length) {
        const current = index++;
        const item = items[current];
        if (item !== undefined) await task(item, current);
      }
    }),
  );
}

function download(item: SnapshotManifestItem): Promise<PreparedSnapshot> {
  const key = identityKey(item.instrument_id, item.interval);
  const pending = downloadInFlight.get(key);
  if (pending) return pending;
  let request: Promise<PreparedSnapshot>;
  request = apiRequest<PreparedSnapshot>(
    `/api/analytics/precomputed/${encodeURIComponent(item.instrument_id)}/${encodeURIComponent(item.interval)}`,
    { timeoutMs: 90_000 },
    )
    .then((payload) => {
      if ((item.snapshot_id && payload.snapshot_id !== item.snapshot_id)
        || payload.fingerprint !== item.fingerprint
        || payload.interval !== item.interval
        || payload.provenance?.instrument_id !== item.instrument_id) {
        throw new Error('Manifest/snapshot fingerprint mismatch');
      }
      if (!isCompleteSnapshot(payload)) {
        throw new Error('The server returned an incomplete analytics snapshot');
      }
      return payload;
    })
    .finally(() => {
      if (downloadInFlight.get(key) === request) downloadInFlight.delete(key);
    });
  downloadInFlight.set(key, request);
  return request;
}

async function synchronize(force: boolean): Promise<void> {
  const currentGeneration = generation;
  setProgress({ phase: 'manifest', total: 0, completed: 0, errors: [], startedAt: Date.now() });
  try {
    const [watchlist, manifest] = await Promise.all([
      // Share the application-scoped watchlist cache (and its in-flight
      // request) instead of issuing a second `/api/watchlist` call.
      portfolioService.getWatchlist(),
      apiRequest<ManifestResponse>('/api/analytics/precomputed/index'),
    ]);
    if (currentGeneration !== generation) return;
    snapshotStore.setManifest(manifest.items ?? []);
    const watched = new Set(
      (watchlist.items ?? [])
        .map((item) => item.instrument_id)
        .filter((id): id is string => Boolean(id)),
    );
    const items = (manifest.items ?? []).filter((item) => watched.has(item.instrument_id));
    const errors: string[] = [];
    let completed = 0;
    const pending: SnapshotManifestItem[] = [];

    for (const item of items) {
      const key = identityKey(item.instrument_id, item.interval);
      if (item.status !== 'READY' || !item.fingerprint) {
        completed += 1;
        continue;
      }
      // Already synchronized this exact fingerprint and still in memory.
      if (
        !force
        && lastSynced.get(key) === (item.snapshot_id ?? item.fingerprint)
        && snapshotStore.getSnapshot(item.instrument_id, item.interval)
      ) {
        completed += 1;
        continue;
      }
      pending.push(item);
    }

    setProgress({
      phase: 'hydrating',
      total: items.length,
      completed,
      errors,
      startedAt: progress.startedAt,
    });

    // One batched read for every entry that actually needs checking.
    let locals: Array<Awaited<ReturnType<typeof snapshotDatabase.get>>> = [];
    if (pending.length > 0) {
      try {
        locals = await snapshotDatabase.getMany(
          pending.map((item) => [item.instrument_id, item.interval] as const),
        );
      } catch (error) {
        errors.push(`local snapshot read: ${error instanceof Error ? error.message : String(error)}`);
      }
    }

    await runPool(pending, 2, async (item, index) => {
      const key = identityKey(item.instrument_id, item.interval);
      try {
        const local = locals[index];
        if (
          local
          && (!item.snapshot_id || local.payload.snapshot_id === item.snapshot_id)
          && local.fingerprint === item.fingerprint
          && local.schemaVersion === ANALYTICS_SCHEMA_VERSION
          && isCompleteSnapshot(local.payload)
          && local.payload.fingerprint === item.fingerprint
          && local.payload.interval === item.interval
          && local.payload.provenance?.instrument_id === item.instrument_id
        ) {
          snapshotStore.setSnapshot(item.instrument_id, item.interval, local.payload);
          lastSynced.set(key, item.snapshot_id ?? item.fingerprint!);
          return;
        }
        if (item.status === 'READY' && item.fingerprint) {
          const payload = await download(item);
          const bundle = {
            instrumentId: item.instrument_id,
            interval: item.interval,
            fingerprint: item.fingerprint,
            schemaVersion: Number(payload.schema_version ?? 1),
            syncedAt: new Date().toISOString(),
            payload,
          };
          if (currentGeneration !== generation) return;
          snapshotStore.setSnapshot(item.instrument_id, item.interval, payload);
          lastSynced.set(key, item.snapshot_id ?? item.fingerprint);
          await snapshotDatabase.put(bundle);
        }
      } catch (error) {
        errors.push(
          `${item.instrument_id} ${item.interval}: ${error instanceof Error ? error.message : String(error)}`,
        );
      } finally {
        completed += 1;
        if (currentGeneration === generation) {
          setProgress({
            phase: 'hydrating',
            total: items.length,
            completed,
            errors: [...errors],
            startedAt: progress.startedAt,
          });
        }
      }
    });

    if (currentGeneration !== generation) return;
    lastSyncAt = Date.now();
    setProgress({
      phase: errors.length ? 'error' : 'ready',
      total: items.length,
      completed,
      errors,
      startedAt: progress.startedAt,
      durationMs: Date.now() - (progress.startedAt ?? Date.now()),
    });
  } catch (error) {
    if (currentGeneration !== generation) return;
    lastSyncAt = Date.now();
    setProgress({
      ...progress,
      phase: 'error',
      errors: [error instanceof Error ? error.message : String(error)],
    });
  }
}

function synchronizeOnce(force = false): Promise<void> {
  if (syncing) return syncing;
  syncing = synchronize(force).finally(() => {
    syncing = undefined;
  });
  return syncing;
}

function onVisibilityChange(): void {
  if (document.visibilityState === 'visible' && Date.now() - lastSyncAt >= 30_000) {
    void synchronizeOnce();
  }
}

export const snapshotHydrator = {
  start(): Promise<void> {
    if (!started) {
      if (!visibilityBound && typeof document !== 'undefined') {
        document.addEventListener('visibilitychange', onVisibilityChange);
        visibilityBound = true;
      }
      started = synchronizeOnce();
      // Manifest polling is application-scoped, not tied to Analytics
      // navigation. Hidden tabs pause polling and catch up when visible.
      refreshTimer = setInterval(() => {
        if (typeof document === 'undefined' || document.visibilityState !== 'hidden') {
          void synchronizeOnce();
        }
      }, 60_000);
    }
    return started;
  },
  /**
   * Reconcile the manifest. Manual refresh forces every ready entry to be
   * rechecked; passing `false` keeps the per-entry fingerprint short-circuit.
   */
  refresh(force = true): Promise<void> {
    started = synchronizeOnce(force);
    return started;
  },
  getProgress(): Progress {
    return progress;
  },
  subscribe(listener: () => void): () => void {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },
  stop(): void {
    if (refreshTimer !== undefined) clearInterval(refreshTimer);
    refreshTimer = undefined;
    if (visibilityBound && typeof document !== 'undefined') {
      document.removeEventListener('visibilitychange', onVisibilityChange);
      visibilityBound = false;
    }
    generation += 1;
    started = undefined;
    syncing = undefined;
    lastSyncAt = 0;
    lastSynced.clear();
    downloadInFlight.clear();
  },
};
