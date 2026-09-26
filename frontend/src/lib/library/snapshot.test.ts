import type { AgentEvent, Commit, Variant } from "../../components/commits/types";
import {
  INTERRUPTED,
  MAX_INLINE_IMAGE_CHARS,
  ProjectState,
  defaultProjectName,
  fromSnapshot,
  projectSummary,
  toSnapshot,
} from "./snapshot";
import { Stack } from "../stacks";

const BIG_IMAGE = `data:image/png;base64,${"A".repeat(MAX_INLINE_IMAGE_CHARS)}`;
const SMALL_IMAGE = "data:image/png;base64,AAAA";
const SHRUNK = "data:image/jpeg;base64,small";
const shrink = jest.fn(async () => SHRUNK);

function commit(overrides: Partial<Commit> & Pick<Commit, "hash">): Commit {
  return {
    parentHash: null,
    dateCreated: new Date(1_000),
    isCommitted: false,
    variants: [{ code: "<html></html>", history: [], status: "complete" }],
    selectedVariantIndex: 0,
    type: "ai_create",
    inputs: { text: "", images: [BIG_IMAGE] },
    ...overrides,
  } as Commit;
}

function project(commits: Commit[], overrides: Partial<ProjectState> = {}): ProjectState {
  return {
    inputMode: "image",
    referenceImages: [BIG_IMAGE],
    initialPrompt: "",
    assetsById: {},
    commits: Object.fromEntries(commits.map((c) => [c.hash, c])),
    head: commits[commits.length - 1]?.hash ?? null,
    latestCommitHash: commits[commits.length - 1]?.hash ?? null,
    ...overrides,
  };
}

function toolEvent(overrides: Partial<AgentEvent> = {}): AgentEvent {
  return {
    id: "tool-1",
    type: "tool",
    status: "complete",
    toolName: "screenshot_preview",
    input: { path: "App.jsx" },
    output: { status: "ok", image: BIG_IMAGE, thumbnail: SMALL_IMAGE, note: "rendered" },
    startedAt: 2_000,
    endedAt: 3_000,
    ...overrides,
  };
}

beforeEach(() => shrink.mockClear());

describe("toSnapshot", () => {
  it("shrinks big inline images in agent activity and nothing else", async () => {
    const variant: Variant = { code: "x", history: [], status: "complete", agentEvents: [toolEvent()] };
    const state = project([commit({ hash: "a", variants: [variant] })]);

    const snapshot = await toSnapshot("p1", Stack.REACT_NATIVE, state, shrink);

    const saved = snapshot.commits.a.variants[0];
    expect(saved.agentEvents?.[0].output).toEqual({
      status: "ok",
      image: SHRUNK,
      thumbnail: SMALL_IMAGE,
      note: "rendered",
    });
    expect(shrink).toHaveBeenCalledTimes(1);
    // The inputs are what a retry sends to the model, so they stay whole.
    expect(snapshot.referenceImages).toEqual([BIG_IMAGE]);
    expect((snapshot.commits.a as { inputs: { images: string[] } }).inputs.images).toEqual([BIG_IMAGE]);
    // The live project isn't touched.
    expect(variant.agentEvents?.[0].output.image).toBe(BIG_IMAGE);
    expect(snapshot).toMatchObject({ version: 1, id: "p1", stack: Stack.REACT_NATIVE, head: "a" });
  });

  it("keeps commit dates as dates", async () => {
    const snapshot = await toSnapshot("p1", Stack.HTML_TAILWIND, project([commit({ hash: "a" })]), shrink);
    expect(snapshot.commits.a.dateCreated).toEqual(new Date(1_000));
  });
});

describe("fromSnapshot", () => {
  it("reopens a finished project as it was saved", async () => {
    const state = project([
      commit({ hash: "a" }),
      commit({ hash: "b", parentHash: "a", type: "ai_edit", inputs: { text: "Make it blue", images: [] } }),
    ]);
    const restored = fromSnapshot(await toSnapshot("p1", Stack.HTML_TAILWIND, state, shrink));
    expect(restored).toEqual(state);
  });

  it("marks what was still generating as failed, with the reason", async () => {
    const variants: Variant[] = [
      { code: "<div>half", history: [], status: "generating", agentEvents: [toolEvent({ status: "running", endedAt: undefined })] },
      { code: "<div></div>", history: [], status: "complete" },
    ];
    const snapshot = await toSnapshot("p1", Stack.HTML_TAILWIND, project([commit({ hash: "a", variants })]), shrink);

    const [interrupted, finished] = fromSnapshot(snapshot).commits.a.variants;

    expect(interrupted).toMatchObject({ code: "<div>half", status: "error", errorMessage: INTERRUPTED });
    expect(interrupted.agentEvents?.[0]).toMatchObject({ status: "error", endedAt: 2_000 });
    expect(finished).toEqual(variants[1]);
  });

  it("turns serialized dates back into dates", async () => {
    const snapshot = await toSnapshot("p1", Stack.HTML_TAILWIND, project([commit({ hash: "a" })]), shrink);
    const serialized = JSON.parse(JSON.stringify(snapshot));
    expect(fromSnapshot(serialized).commits.a.dateCreated).toEqual(new Date(1_000));
  });
});

describe("defaultProjectName", () => {
  const now = new Date(2026, 8, 26, 15, 4);

  it("uses the first version's prompt", () => {
    const state = project(
      [
        commit({ hash: "a", inputs: { text: "  A pricing page\n with three tiers ", images: [] } }),
        commit({ hash: "b", parentHash: "a", type: "ai_edit", inputs: { text: "Make it blue", images: [] } }),
      ],
      { inputMode: "text" }
    );
    expect(defaultProjectName(state, now)).toBe("A pricing page with three tiers");
  });

  it("shortens long prompts", () => {
    const state = project([commit({ hash: "a", inputs: { text: "word ".repeat(30), images: [] } })]);
    const name = defaultProjectName(state, now);
    expect(name).toHaveLength(58);
    expect(name.endsWith("…")).toBe(true);
  });

  it("names screenshots, videos and imported code by kind and time", () => {
    const at = now.toLocaleDateString(undefined, { month: "short", day: "numeric" });
    expect(defaultProjectName(project([commit({ hash: "a" })]), now)).toMatch(new RegExp(`^Screenshot, ${at} `));
    expect(defaultProjectName(project([commit({ hash: "a" })], { inputMode: "video" }), now)).toMatch(/^Video, /);
    const imported = commit({ hash: "a", type: "code_create", inputs: null });
    expect(defaultProjectName(project([imported]), now)).toMatch(/^Imported code, /);
  });
});

it("counts every version in the summary", async () => {
  const state = project([commit({ hash: "a" }), commit({ hash: "b", parentHash: "a" })]);
  const snapshot = await toSnapshot("p1", Stack.VUE_TAILWIND, state, shrink);
  const summary = projectSummary(snapshot, { name: "Mine", createdAt: 1, updatedAt: 2, thumbnail: null });
  expect(summary).toEqual({
    id: "p1",
    name: "Mine",
    stack: Stack.VUE_TAILWIND,
    createdAt: 1,
    updatedAt: 2,
    thumbnail: null,
    versionCount: 2,
  });
});
