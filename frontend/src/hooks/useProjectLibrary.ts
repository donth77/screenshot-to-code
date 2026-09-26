// Keeps the open project saved in the browser's project library, and reopens
// the last one after a reload.
import { useCallback, useEffect, useRef, useState } from "react";
import { openLibrary, LibraryDb } from "../lib/library/db";
import { shrinkImage, thumbnail } from "../lib/library/images";
import {
  ProjectSnapshot,
  ProjectState,
  ProjectSummary,
  defaultProjectName,
  projectSummary,
  toSnapshot,
} from "../lib/library/snapshot";
import type { Stack } from "../lib/stacks";
import { useProjectStore } from "../store/project-store";

// Saves happen at most this often while a generation streams, and this long
// after the last change.
const SAVE_INTERVAL_MS = 1500;
const LAST_PROJECT_KEY = "library:lastProjectId";

function readLastProjectId(): string | null {
  try {
    return window.localStorage.getItem(LAST_PROJECT_KEY);
  } catch {
    return null;
  }
}

function writeLastProjectId(id: string | null): void {
  try {
    if (id) window.localStorage.setItem(LAST_PROJECT_KEY, id);
    else window.localStorage.removeItem(LAST_PROJECT_KEY);
  } catch {
    // Storage can be unavailable (private windows); the library still works for this session.
  }
}

function projectStateOf(state: ReturnType<typeof useProjectStore.getState>): ProjectState {
  const { inputMode, referenceImages, initialPrompt, assetsById, commits, head, latestCommitHash } = state;
  return { inputMode, referenceImages, initialPrompt, assetsById, commits, head, latestCommitHash };
}

function newProjectId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `project-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

interface Options {
  stack: Stack;
  // Load a saved project into the app (stores, stack setting, app state).
  onRestore: (snapshot: ProjectSnapshot) => void;
  // The open project was deleted from the library.
  onDeletedCurrent: () => void;
}

export function useProjectLibrary({ stack, onRestore, onDeletedCurrent }: Options) {
  const [db, setDb] = useState<LibraryDb | null>(null);
  const [available, setAvailable] = useState(true);
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [currentProjectId, setCurrentProjectId] = useState<string | null>(null);
  const currentId = useRef<string | null>(null);
  const stackRef = useRef(stack);
  stackRef.current = stack;
  const onRestoreRef = useRef(onRestore);
  onRestoreRef.current = onRestore;
  const onDeletedCurrentRef = useRef(onDeletedCurrent);
  onDeletedCurrentRef.current = onDeletedCurrent;
  const queue = useRef<Promise<void>>(Promise.resolve());
  const timer = useRef<number | undefined>(undefined);
  const restoring = useRef(false);

  const adopt = useCallback((id: string | null) => {
    currentId.current = id;
    setCurrentProjectId(id);
    writeLastProjectId(id);
  }, []);

  // Loading a saved project into the app isn't an edit, so it isn't saved again.
  const restore = useCallback(
    (id: string, snapshot: ProjectSnapshot) => {
      adopt(id);
      restoring.current = true;
      try {
        onRestoreRef.current(snapshot);
      } finally {
        restoring.current = false;
      }
    },
    [adopt]
  );

  // Library writes run one at a time, in order, so a rename can't land in the
  // middle of an autosave and be overwritten by it.
  const enqueue = useCallback((task: () => Promise<void>) => {
    queue.current = queue.current
      .then(task)
      .catch((error) => console.warn("The project library couldn't save a change", error));
    return queue.current;
  }, []);

  // Saves `state` as project `id` (a new project when id is null) and, for a
  // new project, makes it the open one unless `adoptNew` is false.
  const save = useCallback(
    (state: ProjectState, id: string | null, adoptNew = true) => {
      if (!db || Object.keys(state.commits).length === 0) return queue.current;
      return enqueue(async () => {
        const projectId = id ?? currentId.current ?? newProjectId();
        const existing = await db.getSummary(projectId);
        const now = Date.now();
        const snapshot = await toSnapshot(projectId, stackRef.current, state, shrinkImage);
        const summary = projectSummary(snapshot, {
          name: existing?.name ?? defaultProjectName(state),
          createdAt: existing?.createdAt ?? now,
          updatedAt: now,
          thumbnail: existing?.thumbnail ?? (await thumbnail(state.referenceImages[0])),
        });
        await db.save(summary, snapshot);
        if (adoptNew && id === null && currentId.current === null) adopt(projectId);
        setProjects(await db.list());
      });
    },
    [db, adopt, enqueue]
  );

  // Save any change that's waiting for the next interval, now.
  const flush = useCallback(() => {
    if (timer.current === undefined) return queue.current;
    window.clearTimeout(timer.current);
    timer.current = undefined;
    return save(projectStateOf(useProjectStore.getState()), currentId.current);
  }, [save]);

  // Open the library, then reopen the project that was open before the reload.
  useEffect(() => {
    let cancelled = false;
    openLibrary()
      .then(async (library) => {
        if (cancelled) return;
        setDb(library);
        setProjects(await library.list());
        const lastId = readLastProjectId();
        if (!lastId || Object.keys(useProjectStore.getState().commits).length > 0) return;
        const snapshot = await library.load(lastId);
        if (cancelled) return;
        if (snapshot) {
          restore(lastId, snapshot);
        } else {
          writeLastProjectId(null);
        }
      })
      .catch((error) => {
        console.warn("The project library is unavailable", error);
        setAvailable(false);
      });
    return () => {
      cancelled = true;
    };
  }, [restore]);

  // Autosave: at most every SAVE_INTERVAL_MS, and once more after the last change.
  useEffect(() => {
    if (!db) return;
    const unsubscribe = useProjectStore.subscribe((state, previous) => {
      if (
        restoring.current ||
        (state.commits === previous.commits &&
        state.head === previous.head &&
        state.assetsById === previous.assetsById &&
        state.referenceImages === previous.referenceImages)
      ) {
        return;
      }
      if (Object.keys(state.commits).length === 0) {
        // Started over: finish saving the previous project; the next one is new.
        if (timer.current !== undefined) {
          window.clearTimeout(timer.current);
          timer.current = undefined;
          void save(projectStateOf(previous), currentId.current ?? newProjectId(), false);
        }
        adopt(null);
        return;
      }
      if (timer.current === undefined) {
        timer.current = window.setTimeout(() => {
          timer.current = undefined;
          void save(projectStateOf(useProjectStore.getState()), currentId.current);
        }, SAVE_INTERVAL_MS);
      }
    });
    return () => {
      unsubscribe();
      if (timer.current !== undefined) window.clearTimeout(timer.current);
      timer.current = undefined;
    };
  }, [db, save, adopt]);

  const openProject = useCallback(
    async (id: string) => {
      if (!db) return;
      await flush();
      const snapshot = await db.load(id);
      if (!snapshot) {
        setProjects(await db.list());
        return;
      }
      restore(id, snapshot);
    },
    [db, flush, restore]
  );

  const renameProject = useCallback(
    (id: string, name: string) => {
      if (!db || !name.trim()) return queue.current;
      return enqueue(async () => {
        await db.rename(id, name.trim());
        setProjects(await db.list());
      });
    },
    [db, enqueue]
  );

  const deleteProject = useCallback(
    (id: string) => {
      if (!db) return queue.current;
      // Deleting the open project starts a new one first. That queues any
      // save that was waiting for this project, ahead of the removal.
      if (id === currentId.current) onDeletedCurrentRef.current();
      return enqueue(async () => {
        await db.remove(id);
        setProjects(await db.list());
      });
    },
    [db, enqueue]
  );

  // Other tabs save to the same library.
  const refreshProjects = useCallback(() => {
    if (!db) return queue.current;
    return enqueue(async () => setProjects(await db.list()));
  }, [db, enqueue]);

  return {
    available,
    projects,
    currentProjectId,
    openProject,
    renameProject,
    deleteProject,
    refreshProjects,
  };
}
