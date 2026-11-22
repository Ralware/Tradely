import type { PreparedSnapshot } from './snapshotStore';

const DB_NAME = 'tradely-prepared-analytics';
const DB_VERSION = 1;
const STORE = 'snapshots';
export type StoredBundle = { instrumentId: string; interval: string; fingerprint: string; schemaVersion: number; syncedAt: string; payload: PreparedSnapshot };

function openDatabase(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    if (!('indexedDB' in globalThis)) return reject(new Error('IndexedDB is unavailable'));
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(STORE)) {
        const store = db.createObjectStore(STORE, { keyPath: ['instrumentId', 'interval'] });
        store.createIndex('syncedAt', 'syncedAt');
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error ?? new Error('Unable to open snapshot database'));
    request.onblocked = () => reject(new Error('Snapshot database upgrade is blocked by another tab'));
  });
}

export const snapshotDatabase = {
  async get(instrumentId: string, interval: string): Promise<StoredBundle | undefined> {
    const db = await openDatabase();
    try {
      const value = await new Promise<StoredBundle | undefined>((resolve, reject) => {
        const request = db.transaction(STORE, 'readonly').objectStore(STORE).get([instrumentId, interval]);
        request.onsuccess = () => resolve(request.result as StoredBundle | undefined);
        request.onerror = () => reject(request.error);
      });
      if (value && (value.payload?.schema_version !== DB_VERSION || value.payload?.fingerprint !== value.fingerprint)) {
        await this.remove(instrumentId, interval);
        return undefined;
      }
      return value;
    } finally { db.close(); }
  },
  async put(bundle: StoredBundle): Promise<void> {
    const db = await openDatabase();
    try {
      await new Promise<void>((resolve, reject) => {
        const tx = db.transaction(STORE, 'readwrite');
        tx.objectStore(STORE).put(bundle);
        tx.oncomplete = () => resolve();
        tx.onerror = () => reject(tx.error ?? new Error('Snapshot write failed'));
        tx.onabort = () => reject(tx.error ?? new Error('Snapshot write aborted'));
      });
    } catch (error) {
      if (error instanceof DOMException && error.name === 'QuotaExceededError') {
        await this.evictOldest(2);
        throw new Error('Browser storage quota exceeded; old local snapshots were evicted. Retry synchronization.');
      }
      throw error;
    } finally { db.close(); }
  },
  async putMany(items: StoredBundle[]): Promise<void> {
    const db = await openDatabase();
    try {
      await new Promise<void>((resolve, reject) => {
        const tx = db.transaction(STORE, 'readwrite');
        const store = tx.objectStore(STORE);
        items.forEach((item) => store.put(item));
        tx.oncomplete = () => resolve();
        tx.onerror = () => reject(tx.error ?? new Error('Snapshot bundle transaction failed'));
        tx.onabort = () => reject(tx.error ?? new Error('Snapshot bundle transaction aborted'));
      });
    } finally { db.close(); }
  },
  async remove(instrumentId: string, interval: string): Promise<void> {
    const db = await openDatabase();
    try { await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(STORE, 'readwrite');
      tx.objectStore(STORE).delete([instrumentId, interval]);
      tx.oncomplete = () => resolve(); tx.onerror = () => reject(tx.error);
    }); } finally { db.close(); }
  },
  async evictOldest(count = 1): Promise<void> {
    const db = await openDatabase();
    try { await new Promise<void>((resolve, reject) => {
      const tx = db.transaction(STORE, 'readwrite');
      const index = tx.objectStore(STORE).index('syncedAt');
      let removed = 0;
      const cursor = index.openCursor();
      cursor.onsuccess = () => { const value = cursor.result; if (!value || removed >= count) return;
        value.delete(); removed += 1; value.continue(); };
      tx.oncomplete = () => resolve(); tx.onerror = () => reject(tx.error);
    }); } finally { db.close(); }
  },
};
