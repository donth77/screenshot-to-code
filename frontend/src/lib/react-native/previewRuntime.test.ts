import {
  inlinePreviewDocument,
  loadDeviceTable,
  loadPreviewRuntime,
  previewDocument,
} from "./previewRuntime";

const PROFILE = {
  platform: "ios" as const,
  width: 390,
  height: 763,
  scale: 3,
  insets: { top: 0, right: 0, bottom: 0, left: 0 },
};
const MANIFEST = {
  runtime: "rn-runtime.abc.js",
  babel: "babel-standalone-7.25.6.def.js",
  template: "preview-template.html",
  deviceProfiles: "device-profiles.json",
  expoSdkVersion: "57.0.0",
  versions: {},
};
const TEMPLATE =
  '<script id="rn-preview-config" type="application/json">__RN_PREVIEW_CONFIG__</script>\n<!--RN_PREVIEW_SCRIPTS-->';

let failNext = false;
const fetchMock = jest.fn(async (url: string) => {
  if (failNext) {
    failNext = false;
    return { ok: false, status: 404 } as Response;
  }
  const path = url.replace(/^.*\/rn-runtime\//, "");
  const bodies: Record<string, string> = {
    "manifest.json": JSON.stringify(MANIFEST),
    "preview-template.html": TEMPLATE,
    "device-profiles.json": JSON.stringify({ fallbacks: {}, devices: [] }),
    "rn-runtime.abc.js": "window.runtime = '</script>';",
    "babel-standalone-7.25.6.def.js": "window.Babel = {};",
  };
  const body = bodies[path];
  if (body === undefined) return { ok: false, status: 404 } as Response;
  return {
    ok: true,
    status: 200,
    json: async () => JSON.parse(body),
    text: async () => body,
  } as Response;
});

beforeAll(() => {
  global.fetch = fetchMock as unknown as typeof fetch;
});

beforeEach(() => fetchMock.mockClear());

function fetchedPaths(): string[] {
  return fetchMock.mock.calls.map(([url]) => url);
}

describe("previewRuntime", () => {
  test("loads the manifest and template once per backend", async () => {
    const base = "http://backend-a:7001/";
    const [first, second] = await Promise.all([loadPreviewRuntime(base), loadPreviewRuntime(base)]);
    expect(first).toBe(second);
    expect(first.baseUrl).toBe("http://backend-a:7001");
    expect(fetchedPaths()).toEqual([
      "http://backend-a:7001/rn-runtime/manifest.json",
      "http://backend-a:7001/rn-runtime/preview-template.html",
    ]);
  });

  test("retries after a failed load", async () => {
    const base = "http://backend-b:7001";
    failNext = true;
    await expect(loadPreviewRuntime(base)).rejects.toThrow("HTTP 404");
    await expect(loadPreviewRuntime(base)).resolves.toMatchObject({ baseUrl: base });
  });

  test("loads the device table named by the manifest", async () => {
    const table = await loadDeviceTable("http://backend-c:7001");
    expect(table).toEqual({ fallbacks: {}, devices: [] });
    expect(fetchedPaths()).toContain("http://backend-c:7001/rn-runtime/device-profiles.json");
  });

  test("builds URL-mode documents that load the runtime from the backend", async () => {
    const runtime = await loadPreviewRuntime("http://backend-d:7001");
    const html = previewDocument(runtime, "export default () => null;", PROFILE);
    expect(html).toContain('<script src="http://backend-d:7001/rn-runtime/babel-standalone-7.25.6.def.js"></script>');
    expect(html).toContain('<script src="http://backend-d:7001/rn-runtime/rn-runtime.abc.js"></script>');
  });

  test("inlines Babel and the runtime, escaping script hazards", async () => {
    const runtime = await loadPreviewRuntime("http://backend-e:7001");
    const html = await inlinePreviewDocument(runtime, "export default () => null;", PROFILE);
    expect(html).not.toContain("<script src");
    expect(html).toContain("<script>window.Babel = {};</script>\n<script>window.runtime = '\\x3C/script>';</script>");
    // Fetched once, then cached.
    const framed = await inlinePreviewDocument(runtime, "export default () => 1;", PROFILE, "<style>x</style>\n");
    expect(framed).toContain("<style>x</style>\n<script>window.Babel = {};</script>");
    const scriptFetches = fetchedPaths().filter((url) => url.endsWith(".js"));
    expect(scriptFetches).toHaveLength(2);
  });
});
