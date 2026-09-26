import "fake-indexeddb/auto";
import { IDBFactory } from "fake-indexeddb";
import { MIN_MEDIA_CHARS, openLibrary } from "./db";
import type { ProjectSnapshot, ProjectSummary } from "./snapshot";
import { Stack } from "../stacks";

function summary(id: string, updatedAt: number): ProjectSummary {
  return { id, name: `Project ${id}`, stack: Stack.HTML_TAILWIND, createdAt: 1, updatedAt, thumbnail: null, versionCount: 1 };
}

function snapshot(id: string): ProjectSnapshot {
  return {
    version: 1,
    id,
    stack: Stack.HTML_TAILWIND,
    inputMode: "text",
    referenceImages: [],
    initialPrompt: "A landing page",
    assetsById: {},
    commits: {
      a: {
        hash: "a",
        parentHash: null,
        dateCreated: new Date(1_000),
        isCommitted: false,
        variants: [{ code: "<html></html>", history: [], status: "complete" }],
        selectedVariantIndex: 0,
        type: "ai_create",
        inputs: { text: "A landing page", images: [] },
      },
    },
    head: "a",
    latestCommitHash: "a",
  };
}

describe("the project library", () => {
  it("saves projects and lists the most recently edited first", async () => {
    const library = await openLibrary(new IDBFactory());
    await library.save(summary("old", 10), snapshot("old"));
    await library.save(summary("new", 20), snapshot("new"));

    expect((await library.list()).map((project) => project.id)).toEqual(["new", "old"]);
    expect(await library.getSummary("old")).toEqual(summary("old", 10));
    const loaded = await library.load("new");
    expect(loaded).toEqual(snapshot("new"));
    // A real Date (from outside jest's sandbox, so not instanceof its Date).
    expect(Object.prototype.toString.call(loaded?.commits.a.dateCreated)).toBe("[object Date]");
  });

  it("replaces a project when it's saved again", async () => {
    const library = await openLibrary(new IDBFactory());
    await library.save(summary("p", 10), snapshot("p"));
    await library.save({ ...summary("p", 30), versionCount: 2 }, { ...snapshot("p"), head: "b" });

    expect(await library.list()).toEqual([{ ...summary("p", 30), versionCount: 2 }]);
    expect((await library.load("p"))?.head).toBe("b");
  });

  it("renames and deletes", async () => {
    const library = await openLibrary(new IDBFactory());
    await library.save(summary("p", 10), snapshot("p"));

    await library.rename("p", "Checkout flow");
    expect((await library.getSummary("p"))?.name).toBe("Checkout flow");
    await library.rename("missing", "Nothing");
    expect(await library.getSummary("missing")).toBeNull();

    await library.remove("p");
    expect(await library.list()).toEqual([]);
    expect(await library.load("p")).toBeNull();
  });

  it("keeps projects across reopening", async () => {
    const factory = new IDBFactory();
    await (await openLibrary(factory)).save(summary("p", 10), snapshot("p"));
    expect((await (await openLibrary(factory)).list()).map((project) => project.id)).toEqual(["p"]);
  });
});

describe("screenshots and videos", () => {
  const SCREENSHOT = `data:image/png;base64,${"S".repeat(MIN_MEDIA_CHARS)}`;
  const OTHER = `data:image/png;base64,${"O".repeat(MIN_MEDIA_CHARS)}`;
  const ICON = "data:image/png;base64,AAAA";

  function withMedia(id: string, images: string[]): ProjectSnapshot {
    const project = snapshot(id);
    return {
      ...project,
      inputMode: "image",
      referenceImages: images,
      assetsById: Object.fromEntries(images.map((dataUrl, i) => [`asset-${i}`, { id: `asset-${i}`, type: "image", dataUrl }])),
      commits: { a: { ...project.commits.a, inputs: { text: "", images: [...images, ICON] } } },
    } as ProjectSnapshot;
  }

  async function storedMedia(factory: IDBFactory): Promise<string[]> {
    const db = await new Promise<IDBDatabase>((resolve, reject) => {
      const request = factory.open("screenshot-to-code-library");
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
    const keys = await new Promise<IDBValidKey[]>((resolve, reject) => {
      const request = db.transaction("media").objectStore("media").getAllKeys();
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
    db.close();
    return keys as string[];
  }

  it("are stored once per project and come back on load", async () => {
    const factory = new IDBFactory();
    const library = await openLibrary(factory);
    const project = withMedia("p", [SCREENSHOT]);
    await library.save(summary("p", 10), project);
    await library.save(summary("p", 20), project);

    const media = await storedMedia(factory);
    expect(media).toHaveLength(1);
    expect(media[0].startsWith("p/")).toBe(true);
    expect(await library.load("p")).toEqual(project);
  });

  it("are dropped when the project stops using them, or is deleted", async () => {
    const factory = new IDBFactory();
    const library = await openLibrary(factory);
    await library.save(summary("p", 10), withMedia("p", [SCREENSHOT, OTHER]));
    await library.save(summary("q", 10), withMedia("q", [SCREENSHOT]));
    expect(await storedMedia(factory)).toHaveLength(3);

    await library.save(summary("p", 20), withMedia("p", [OTHER]));
    expect(await storedMedia(factory)).toHaveLength(2);
    expect(await library.load("p")).toEqual(withMedia("p", [OTHER]));

    await library.remove("p");
    const left = await storedMedia(factory);
    expect(left).toHaveLength(1);
    expect(left[0].startsWith("q/")).toBe(true);
    expect(await library.load("q")).toEqual(withMedia("q", [SCREENSHOT]));
  });
});
