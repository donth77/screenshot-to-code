// Loads rn-runtime's manifest and template from the backend once, and builds
// preview documents for an iframe's srcdoc. The documents load the runtime
// from `${baseUrl}/rn-runtime/`; with an empty baseUrl that's the page's own
// origin, which the Vite dev server proxies to the backend. A srcdoc iframe
// resolves those URLs against its parent page.
import type { DeviceTable } from "./devices";
import {
  DeviceProfile,
  PreviewMode,
  inlineScript,
  previewConfigJson,
  renderPreviewHtml,
  scriptTags,
} from "./previewHtml";

export interface RuntimeManifest {
  runtime: string;
  babel: string;
  template: string;
  deviceProfiles: string;
  expoSdkVersion: string;
  versions: Record<string, string>;
}

export interface PreviewRuntime {
  baseUrl: string;
  manifest: RuntimeManifest;
  template: string;
}

export interface PreviewError {
  kind: string;
  message: string;
  fatal: boolean;
  line?: number;
  column?: number;
  rule?: string;
}

// What the preview posts to its parent after every render.
export interface PreviewStatus {
  type: "rn-preview:status";
  renderId: number;
  status: "ok" | "degraded" | "error" | "streaming";
  errors: PreviewError[];
  meta: Record<string, unknown>;
}

const runtimes = new Map<string, Promise<PreviewRuntime>>();
const deviceTables = new Map<string, Promise<DeviceTable>>();
const inlineScriptSets = new Map<string, Promise<string>>();

async function fetchOk(url: string): Promise<Response> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`${url}: HTTP ${response.status}`);
  }
  return response;
}

// One promise per key, shared by every caller. A failed load (backend down,
// runtime not built) is dropped, so the next call retries.
function cached<T>(cache: Map<string, Promise<T>>, key: string, load: () => Promise<T>): Promise<T> {
  let value = cache.get(key);
  if (!value) {
    value = load();
    value.catch(() => cache.delete(key));
    cache.set(key, value);
  }
  return value;
}

function normalizeBase(baseUrl: string): string {
  return baseUrl.replace(/\/+$/, "");
}

export function loadPreviewRuntime(baseUrl = ""): Promise<PreviewRuntime> {
  const base = normalizeBase(baseUrl);
  return cached(runtimes, base, async () => {
    const manifest = (await (await fetchOk(`${base}/rn-runtime/manifest.json`)).json()) as RuntimeManifest;
    const template = await (await fetchOk(`${base}/rn-runtime/${manifest.template}`)).text();
    return { baseUrl: base, manifest, template };
  });
}

// rn-runtime/device-profiles.json: the known phones (DESIGN.md §7.2).
export function loadDeviceTable(baseUrl = ""): Promise<DeviceTable> {
  const base = normalizeBase(baseUrl);
  return cached(deviceTables, base, async () => {
    const { manifest } = await loadPreviewRuntime(base);
    return (await (await fetchOk(`${base}/rn-runtime/${manifest.deviceProfiles}`)).json()) as DeviceTable;
  });
}

export function previewDocument(
  runtime: PreviewRuntime,
  source: string,
  profile: DeviceProfile,
  mode: PreviewMode = "final"
): string {
  const { baseUrl, manifest, template } = runtime;
  return renderPreviewHtml(
    template,
    previewConfigJson(source, profile, mode),
    scriptTags(baseUrl, manifest.runtime, manifest.babel)
  );
}

// Babel and the runtime as inline <script>s, fetched once (about 4.7 MB).
function inlineScripts(runtime: PreviewRuntime): Promise<string> {
  const { baseUrl, manifest } = runtime;
  return cached(inlineScriptSets, `${baseUrl}|${manifest.runtime}|${manifest.babel}`, async () => {
    const [babel, runtimeJs] = await Promise.all(
      [manifest.babel, manifest.runtime].map(async (name) =>
        (await fetchOk(`${baseUrl}/rn-runtime/${name}`)).text()
      )
    );
    return `${inlineScript(babel)}\n${inlineScript(runtimeJs)}`;
  });
}

// A self-contained preview page: everything inlined, so it opens from file://
// with no network (gate RNW-3). `extraHead` goes before the scripts.
export async function inlinePreviewDocument(
  runtime: PreviewRuntime,
  source: string,
  profile: DeviceProfile,
  extraHead = ""
): Promise<string> {
  return renderPreviewHtml(
    runtime.template,
    previewConfigJson(source, profile, "final"),
    extraHead + (await inlineScripts(runtime))
  );
}

// The next status the frame posts. Listen before loading the frame (or
// posting it an rn-preview:update) so the message can't be missed.
export function nextPreviewStatus(frame: HTMLIFrameElement, timeoutMs = 15000): Promise<PreviewStatus> {
  return new Promise((resolve, reject) => {
    const onMessage = (event: MessageEvent) => {
      if (event.source !== frame.contentWindow || event.data?.type !== "rn-preview:status") {
        return;
      }
      window.clearTimeout(timer);
      window.removeEventListener("message", onMessage);
      resolve(event.data as PreviewStatus);
    };
    const timer = window.setTimeout(() => {
      window.removeEventListener("message", onMessage);
      reject(new Error(`no preview status within ${timeoutMs} ms`));
    }, timeoutMs);
    window.addEventListener("message", onMessage);
  });
}
