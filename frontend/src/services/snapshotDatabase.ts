import type { PreparedSnapshot } from './snapshotStore';

const DB_NAME = 'tradely-prepared-analytics';
const DB_VERSION = 1;
const STORE = 'snapshots';
const MAX_BUNDLES = 64;

export type StoredBundle = {
  instrumentId: string;
  interval: string;
  fingerprint: string;
  schemaVersion: number;
  syncedAt: string;
  payload: PreparedSnapshot;
};

export type SnapshotKey = readonly [instrumentId: string, interval: string];

let connection: Promise<IDBDatabase> | undefined;

/**
 * One reusable connection for the whole application. Opening and closing
 * IndexedDB for every snapshot read/write adds latency and blocks other tabs
 * during upgrades; the connection is recreated only if it is closed or a newer
 * tab requests a version change.
 */
function openDatabase(): Promise<IDBDatabase> {
  if (connection) return connection;
  const opening = new Promise<IDBDatabase>((resolve, reject) => {
    if (!('indexedDB' in globalThis)) {
      reject(new Error('IndexedDB is unavailable'));
      return;
    }
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(STORE)) {
        const store = db.createObjectStore(STORE, { keyPath: ['instrumentId', 'interval'] });
        store.createIndex('syncedAt', 'syncedAt');
      } else {
        const store = request.transaction?.objectStore(STORE);
        if (store && !store.indexNames.contains('syncedAt')) {
          store.createIndex('syncedAt', 'syncedAt');
        }
      }
    };
    request.onsuccess = () => {
      const db = request.result;
      db.onversionchange = () => {
        db.close();
        connection = undefined;
      };
      db.onclose = () => {
        connection = undefined;
      };
      resolve(db);
    };
    request.onerror = () => reject(request.error ?? new Error('Unable to open snapshot database'));
    request.onblocked = () => reject(new Error('Snapshot database upgrade is blocked by another tab'));
  });
  opening.catch(() => {
    if (connection === opening) connection = undefined;
  });
  connection = opening;
  return opening;
}

function validBundle(value: StoredBundle | undefined): value is StoredBundle {
  if (!value?.payload || !value.fingerprint) return false;
  // The database schema version and the analytics payload schema version are
  // independent. Comparing them (the previous behaviour) discarded every
  // valid payload whose analytics schema had advanced, forcing a refetch.
  const payloadSchema = Number(value.payload.schema_version);
  return Number.isFinite(payloadSchema)
    && payloadSchema >= 1
    && value.payload.fingerprint === value.fingerprint;
}

function requestResult<T>(request: IDBRequest<T>): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error('IndexedDB request failed'));
  });
}

async function removeKeys(keys: SnapshotKey[]): Promise<void> {
  if (keys.length === 0) return;
  const db = await openDatabase();
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(STORE, 'readwrite');
    const store = tx.objectStore(STORE);
    for (const [instrumentId, interval] of keys) store.delete([instrumentId, interval]);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error ?? new Error('Snapshot delete failed'));
    tx.onabort = () => reject(tx.error ?? new Error('Snapshot delete aborted'));
  });
}

async function writeBundles(items: StoredBundle[]): Promise<void> {
  const deduped = new Map<string, StoredBundle>();
  for (const item of items) deduped.set(`${item.instrumentId}\u0000${item.interval}`, item);
  const bundles = [...deduped.values()];
  if (bundles.length === 0) return;
  const db = await openDatabase();
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(STORE, 'readwrite');
    const store = tx.objectStore(STORE);
    for (const bundle of bundles) store.put(bundle);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error ?? new Error('Snapshot bundle transaction failed'));
    tx.onabort = () => reject(tx.error ?? new Error('Snapshot bundle transaction aborted'));
  });
}

async function evictOldestBundles(count: number): Promise<void> {
  if (count <= 0) return;
  const db = await openDatabase();
  await new Promise<void>((resolve, reject) => {
    const tx = db.transaction(STORE, 'readwrite');
    const index = tx.objectStore(STORE).index('syncedAt');
    let removed = 0;
    const cursor = index.openCursor();
    cursor.onsuccess = () => {
      const value = cursor.result;
      if (!value || removed >= count) return;
      value.delete();
      removed += 1;
      value.continue();
    };
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error ?? new Error('Snapshot eviction failed'));
    tx.onabort = () => reject(tx.error ?? new Error('Snapshot eviction aborted'));
  });
}

export const snapshotDatabase = {
  async get(instrumentId: string, interval: string): Promise<StoredBundle | undefined> {
    const [bundle] = await this.getMany([[instrumentId, interval]]);
    return bundle;
  },

  async getMany(keys: SnapshotKey[]): Promise<Array<StoredBundle | undefined>> {
    if (keys.length === 0) return [];
    const db = await openDatabase();
    const results = await new Promise<Array<StoredBundle | undefined>>((resolve, reject) => {
      const tx = db.transaction(STORE, 'readonly');
      const store = tx.objectStore(STORE);
      const requests = keys.map(([instrumentId, interval]) => store.get([instrumentId, interval]));
      tx.oncomplete = () => resolve(requests.map((request) => request.result as StoredBundle | undefined));
      tx.onerror = () => reject(tx.error ?? new Error('Snapshot read failed'));
      tx.onabort = () => reject(tx.error ?? new Error('Snapshot read aborted'));
    });
    const invalid: SnapshotKey[] = [];
    const valid = results.map((value, index) => {
      if (value && !validBundle(value)) {
        invalid.push(keys[index]);
        return undefined;
      }
      return value;
    });
    if (invalid.length > 0) {
      // Repair corrupt/old rows without blocking the caller's read.
      void removeKeys(invalid).catch(() => undefined);
    }
    return valid;
  },

  async put(bundle: StoredBundle): Promise<void> {
    await this.putMany([bundle]);
  },

  async putMany(items: StoredBundle[]): Promise<void> {
    if (items.length === 0) return;
    try {
      await writeBundles(items);
    } catch (error) {
      if (error instanceof DOMException && error.name === 'QuotaExceededError') {
        await evictOldestBundles(Math.max(2, Math.ceil(items.length / 2)));
        await writeBundles(items);
      } else {
        throw error;
      }
    }
    try {
      await this.prune();
    } catch {
      // Retention is best-effort; a successful write must not fail because
      // the quota cleanup cursor was interrupted.
    }
  },

  async remove(instrumentId: string, interval: string): Promise<void> {
    await removeKeys([[instrumentId, interval]]);
  },

  async evictOldest(count = 1): Promise<void> {
    await evictOldestBundles(count);
  },

  async prune(maxEntries = MAX_BUNDLES): Promise<number> {
    const db = await openDatabase();
    const count = await requestResult(db.transaction(STORE, 'readonly').objectStore(STORE).count());
    const excess = count - Math.max(1, maxEntries);
    if (excess <= 0) return 0;
    await evictOldestBundles(excess);
    return excess;
  },

  async count(): Promise<number> {
    const db = await openDatabase();
    return requestResult(db.transaction(STORE, 'readonly').objectStore(STORE).count());
  },

  /** Close and forget the cached connection (tests and full app teardown). */
  close(): void {
    const pending = connection;
    connection = undefined;
    void pending?.then((db) => db.close()).catch(() => undefined);
  },
};
