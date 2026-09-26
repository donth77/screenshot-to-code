// A project as the library stores it: everything needed to reopen it where it
// left off (the inputs, every version with its variants' code, history and
// agent activity, the stack) plus a small summary for the library's list.
import type {
  AgentEvent,
  Commit,
  CommitHash,
  Variant,
} from "../../components/commits/types";
import type { PromptAsset } from "../../types";
import type { Stack } from "../stacks";

export const SNAPSHOT_VERSION = 1;

// Inline images in agent tool output (screenshot_preview's renders) only
// illustrate the activity log. Bigger ones are shrunk before saving so a
// project stays small; input screenshots are kept whole.
export const MAX_INLINE_IMAGE_CHARS = 100_000;

export interface ProjectState {
  inputMode: "image" | "video" | "text";
  referenceImages: string[];
  initialPrompt: string;
  assetsById: Record<string, PromptAsset>;
  commits: Record<string, Commit>;
  head: CommitHash | null;
  latestCommitHash: CommitHash | null;
}

export interface ProjectSnapshot extends ProjectState {
  version: number;
  id: string;
  stack: Stack;
}

export interface ProjectSummary {
  id: string;
  name: string;
  stack: Stack;
  createdAt: number;
  updatedAt: number;
  // A small JPEG data URL of the first input screenshot, when there is one.
  thumbnail: string | null;
  versionCount: number;
}

// Shrinks an image data URL; returns it unchanged if it can't.
export type ShrinkImage = (dataUrl: string) => Promise<string>;

// An object literal, as opposed to a Date or other built-in (from any realm:
// IndexedDB hands back values made outside jest's sandbox).
export function isPlainObject(value: unknown): value is Record<string, unknown> {
  return Object.prototype.toString.call(value) === "[object Object]";
}

async function shrinkLargeImages(value: unknown, shrink: ShrinkImage): Promise<unknown> {
  if (typeof value === "string") {
    return value.startsWith("data:image/") && value.length > MAX_INLINE_IMAGE_CHARS
      ? shrink(value)
      : value;
  }
  if (Array.isArray(value)) {
    return Promise.all(value.map((item) => shrinkLargeImages(item, shrink)));
  }
  if (isPlainObject(value)) {
    const entries = await Promise.all(
      Object.entries(value).map(async ([key, item]) => [key, await shrinkLargeImages(item, shrink)] as const)
    );
    return Object.fromEntries(entries);
  }
  return value;
}

async function saveableVariant(variant: Variant, shrink: ShrinkImage): Promise<Variant> {
  const agentEvents = variant.agentEvents
    ? ((await shrinkLargeImages(variant.agentEvents, shrink)) as AgentEvent[])
    : undefined;
  return { ...variant, agentEvents };
}

export async function toSnapshot(
  id: string,
  stack: Stack,
  state: ProjectState,
  shrink: ShrinkImage
): Promise<ProjectSnapshot> {
  const commits: Record<string, Commit> = {};
  for (const [hash, commit] of Object.entries(state.commits)) {
    commits[hash] = {
      ...commit,
      variants: await Promise.all(commit.variants.map((variant) => saveableVariant(variant, shrink))),
    };
  }
  return {
    version: SNAPSHOT_VERSION,
    id,
    stack,
    inputMode: state.inputMode,
    referenceImages: state.referenceImages,
    initialPrompt: state.initialPrompt,
    assetsById: state.assetsById,
    commits,
    head: state.head,
    latestCommitHash: state.latestCommitHash,
  };
}

// What was still generating when the project was saved can't resume: the
// request died with the page. The sidebar shows it as a failed option ("This
// option failed to generate because …") with Retry.
export const INTERRUPTED = "the page was reloaded or closed before it finished.";

export function fromSnapshot(snapshot: ProjectSnapshot): ProjectState {
  const commits: Record<string, Commit> = {};
  for (const [hash, commit] of Object.entries(snapshot.commits)) {
    commits[hash] = {
      ...commit,
      dateCreated: new Date(commit.dateCreated),
      variants: commit.variants.map((variant) => ({
        ...variant,
        ...(variant.status === "generating" ? { status: "error" as const, errorMessage: INTERRUPTED } : {}),
        agentEvents: variant.agentEvents?.map((event) =>
          event.status === "running" ? { ...event, status: "error" as const, endedAt: event.endedAt ?? event.startedAt } : event
        ),
      })),
    };
  }
  return {
    inputMode: snapshot.inputMode,
    referenceImages: snapshot.referenceImages,
    initialPrompt: snapshot.initialPrompt,
    assetsById: snapshot.assetsById,
    commits,
    head: snapshot.head,
    latestCommitHash: snapshot.latestCommitHash,
  };
}

// The first version's prompt, or what kind of input the project started from.
export function defaultProjectName(state: ProjectState, now: Date = new Date()): string {
  const first = Object.values(state.commits)
    .filter((commit) => commit.parentHash === null)
    .sort((a, b) => new Date(a.dateCreated).getTime() - new Date(b.dateCreated).getTime())[0];
  const text = (first?.inputs?.text || state.initialPrompt || "").trim().replace(/\s+/g, " ");
  if (text) return text.length > 60 ? `${text.slice(0, 57)}…` : text;
  const kind =
    first?.type === "code_create" ? "Imported code" : state.inputMode === "video" ? "Video" : "Screenshot";
  const date = now.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  const time = now.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
  return `${kind}, ${date} ${time}`;
}

export function projectSummary(
  snapshot: ProjectSnapshot,
  details: { name: string; createdAt: number; updatedAt: number; thumbnail: string | null }
): ProjectSummary {
  return {
    id: snapshot.id,
    stack: snapshot.stack,
    versionCount: Object.keys(snapshot.commits).length,
    ...details,
  };
}
