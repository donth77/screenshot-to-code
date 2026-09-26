// The project library's storage: this browser's IndexedDB. Summaries (for the
// list) and snapshots (the whole project) live in separate stores, so listing
// projects never loads their screenshots. Screenshots and videos are data URLs
// that repeat within a project (its inputs, each version's inputs, its assets)
// and don't change while it autosaves, so each one is stored once, in a third
// store, and the snapshot refers to it by content.
import { isPlainObject, ProjectSnapshot, ProjectSummary } from "./snapshot";

const DB_NAME = "screenshot-to-code-library";
const DB_VERSION = 2;
const SUMMARIES = "summaries";
const SNAPSHOTS = "snapshots";
const MEDIA = "media";

// Data URLs at least this long move to the media store.
export const MIN_MEDIA_CHARS = 4096;
const MEDIA_REF = "\u0000library-media:";

export interface LibraryDb {
  list(): Promise<ProjectSummary[]>;
  load(id: string): Promise<ProjectSnapshot | null>;
  getSummary(id: string): Promise<ProjectSummary | null>;
  save(summary: ProjectSummary, snapshot: ProjectSnapshot): Promise<void>;
  rename(id: string, name: string): Promise<void>;
  remove(id: string): Promise<void>;
}

function done(request: IDBRequest): Promise<unknown> {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

function committed(transaction: IDBTransaction): Promise<void> {
  const result = new Promise<void>((resolve, reject) => {
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error);
    transaction.onabort = () => reject(transaction.error ?? new Error("Library transaction aborted"));
  });
  // A failed request rejects its own promise first; this one is awaited last.
  result.catch(() => undefined);
  return result;
}

// cyrb53: a fast 53-bit string hash. Keys are per project, so collisions
// would need two different data URLs of the same length in one project.
function hash(text: string): string {
  let h1 = 0xdeadbeef;
  let h2 = 0x41c6ce57;
  for (let i = 0; i < text.length; i++) {
    const ch = text.charCodeAt(i);
    h1 = Math.imul(h1 ^ ch, 2654435761);
    h2 = Math.imul(h2 ^ ch, 1597334677);
  }
  h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
  h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
  return (4294967296 * (2097151 & h2) + (h1 >>> 0)).toString(36);
}

// Hashing a screenshot takes a few milliseconds and autosave sees the same
// strings every time.
const hashes = new Map<string, string>();

function mediaKey(projectId: string, dataUrl: string): string {
  let digest = hashes.get(dataUrl);
  if (digest === undefined) {
    if (hashes.size >= 200) hashes.clear();
    digest = `${dataUrl.length.toString(36)}-${hash(dataUrl)}`;
    hashes.set(dataUrl, digest);
  }
  return `${projectId}/${digest}`;
}

function projectMedia(projectId: string): IDBKeyRange {
  return IDBKeyRange.bound(`${projectId}/`, `${projectId}/￿`);
}

// A copy of `value` with every string passed through `replace`.
function mapStrings(value: unknown, replace: (text: string) => string): unknown {
  if (typeof value === "string") return replace(value);
  if (Array.isArray(value)) return value.map((item) => mapStrings(item, replace));
  if (isPlainObject(value)) {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, mapStrings(item, replace)]));
  }
  return value;
}

export async function openLibrary(factory: IDBFactory = indexedDB): Promise<LibraryDb> {
  const request = factory.open(DB_NAME, DB_VERSION);
  request.onupgradeneeded = () => {
    const db = request.result;
    if (!db.objectStoreNames.contains(SUMMARIES)) db.createObjectStore(SUMMARIES, { keyPath: "id" });
    if (!db.objectStoreNames.contains(SNAPSHOTS)) db.createObjectStore(SNAPSHOTS, { keyPath: "id" });
    if (!db.objectStoreNames.contains(MEDIA)) db.createObjectStore(MEDIA);
  };
  const db = (await done(request)) as IDBDatabase;

  return {
    async list() {
      const store = db.transaction(SUMMARIES, "readonly").objectStore(SUMMARIES);
      const summaries = (await done(store.getAll())) as ProjectSummary[];
      return summaries.sort((a, b) => b.updatedAt - a.updatedAt);
    },
    async load(id) {
      const transaction = db.transaction([SNAPSHOTS, MEDIA], "readonly");
      const stored = (await done(transaction.objectStore(SNAPSHOTS).get(id))) as ProjectSnapshot | undefined;
      if (!stored) return null;
      const media = transaction.objectStore(MEDIA);
      const [keys, dataUrls] = (await Promise.all([
        done(media.getAllKeys(projectMedia(id))),
        done(media.getAll(projectMedia(id))),
      ])) as [string[], string[]];
      const byKey = new Map(keys.map((key, index) => [key, dataUrls[index]]));
      return mapStrings(stored, (text) =>
        text.startsWith(MEDIA_REF) ? byKey.get(text.slice(MEDIA_REF.length)) ?? text : text
      ) as ProjectSnapshot;
    },
    async getSummary(id) {
      const store = db.transaction(SUMMARIES, "readonly").objectStore(SUMMARIES);
      return ((await done(store.get(id))) as ProjectSummary | undefined) ?? null;
    },
    async save(summary, snapshot) {
      const referenced = new Map<string, string>();
      const stored = mapStrings(snapshot, (text) => {
        if (!text.startsWith("data:") || text.length < MIN_MEDIA_CHARS) return text;
        const key = mediaKey(snapshot.id, text);
        referenced.set(key, text);
        return MEDIA_REF + key;
      });

      const transaction = db.transaction([SUMMARIES, SNAPSHOTS, MEDIA], "readwrite");
      const finished = committed(transaction);
      transaction.objectStore(SUMMARIES).put(summary);
      transaction.objectStore(SNAPSHOTS).put(stored);
      // Write only new media, and drop what the project no longer uses.
      const media = transaction.objectStore(MEDIA);
      const existing = new Set((await done(media.getAllKeys(projectMedia(snapshot.id)))) as string[]);
      for (const [key, dataUrl] of referenced) if (!existing.has(key)) media.put(dataUrl, key);
      for (const key of existing) if (!referenced.has(key)) media.delete(key);
      await finished;
    },
    async rename(id, name) {
      const transaction = db.transaction(SUMMARIES, "readwrite");
      const finished = committed(transaction);
      const store = transaction.objectStore(SUMMARIES);
      const summary = (await done(store.get(id))) as ProjectSummary | undefined;
      if (summary) store.put({ ...summary, name });
      await finished;
    },
    async remove(id) {
      const transaction = db.transaction([SUMMARIES, SNAPSHOTS, MEDIA], "readwrite");
      const finished = committed(transaction);
      transaction.objectStore(SUMMARIES).delete(id);
      transaction.objectStore(SNAPSHOTS).delete(id);
      transaction.objectStore(MEDIA).delete(projectMedia(id));
      await finished;
    },
  };
}
