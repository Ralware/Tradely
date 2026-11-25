export type PreparedSnapshot = Record<string, any> & {
  instrument?: { instrument_id?: string };
  interval: string;
  fingerprint: string;
  generated_at: string;
  strategy_variants?: Record<string, unknown>;
};

export type SnapshotManifestItem = {
  instrument_id: string;
  interval: string;
  status: string;
  snapshot_id?: string | null;
  fingerprint?: string | null;
  generated_at?: string | null;
  latest_candle_at?: string | null;
  candle_count?: number;
  last_error?: string | null;
};

type Listener = () => void;
const snapshots = new Map<string, PreparedSnapshot>();
const manifests = new Map<string, SnapshotManifestItem>();
const listeners = new Map<string, Set<Listener>>();
const manifestListeners = new Set<Listener>();
const key = (instrumentId: string, interval: string) => `${instrumentId}\u0000${interval}`;

function notify(id: string, interval: string): void {
  listeners.get(key(id, interval))?.forEach((listener) => listener());
}

function snapshotTime(snapshot: PreparedSnapshot | undefined): number {
  if (!snapshot) return Number.NaN;
  const value =
    snapshot.provenance?.latest_candle_timestamp
    ?? snapshot.analysis?.as_of
    ?? snapshot.generated_at;
  return typeof value === 'string' ? Date.parse(value) : Number.NaN;
}

export const snapshotStore = {
  getSnapshot(instrumentId: string, interval: string): PreparedSnapshot | undefined {
    return snapshots.get(key(instrumentId, interval));
  },
  getStrategyVariant(instrumentId: string, interval: string, directionMode: string, positionSide: string | null): unknown {
    return snapshots.get(key(instrumentId, interval))?.strategy_variants?.[`${directionMode}:${positionSide ?? 'NONE'}`];
  },
  setSnapshot(instrumentId: string, interval: string, snapshot: PreparedSnapshot): void {
    const itemKey = key(instrumentId, interval);
    const existing = snapshots.get(itemKey);
    // A late/queued response must never roll the chart back to older candles.
    const incomingTime = snapshotTime(snapshot);
    const existingTime = snapshotTime(existing);
    if (
      Number.isFinite(incomingTime)
      && Number.isFinite(existingTime)
      && incomingTime < existingTime
    ) {
      return;
    }
    snapshots.set(itemKey, snapshot);
    const previous = manifests.get(itemKey);
    manifests.set(itemKey, {
      ...previous, instrument_id: instrumentId, interval, status: 'READY',
      snapshot_id: snapshot.snapshot_id, fingerprint: snapshot.fingerprint,
      generated_at: snapshot.generated_at,
      latest_candle_at: snapshot.provenance?.latest_candle_timestamp,
      candle_count: snapshot.provenance?.candle_count,
    });
    notify(instrumentId, interval);
    manifestListeners.forEach((listener) => listener());
  },
  updateSnapshot(instrumentId: string, interval: string, update: Partial<PreparedSnapshot>): void {
    const current = snapshots.get(key(instrumentId, interval));
    if (current) this.setSnapshot(instrumentId, interval, { ...current, ...update });
  },
  invalidateSnapshot(instrumentId: string, interval: string): void {
    snapshots.delete(key(instrumentId, interval));
    notify(instrumentId, interval);
  },
  getManifestItem(instrumentId: string, interval: string): SnapshotManifestItem | undefined {
    return manifests.get(key(instrumentId, interval));
  },
  getManifest(instrumentId?: string): SnapshotManifestItem[] {
    return [...manifests.values()].filter((item) => !instrumentId || item.instrument_id === instrumentId);
  },
  setManifest(items: SnapshotManifestItem[]): void {
    for (const item of items) manifests.set(key(item.instrument_id, item.interval), item);
    manifestListeners.forEach((listener) => listener());
  },
  subscribe(instrumentId: string, interval: string, listener: Listener): () => void {
    const itemKey = key(instrumentId, interval);
    const bucket = listeners.get(itemKey) ?? new Set<Listener>();
    bucket.add(listener);
    listeners.set(itemKey, bucket);
    return () => { bucket.delete(listener); if (!bucket.size) listeners.delete(itemKey); };
  },
  subscribeManifest(listener: Listener): () => void {
    manifestListeners.add(listener);
    return () => manifestListeners.delete(listener);
  },
  clear(): void { snapshots.clear(); manifests.clear(); listeners.forEach((bucket) => bucket.forEach((listener) => listener())); manifestListeners.forEach((listener) => listener()); },
};
