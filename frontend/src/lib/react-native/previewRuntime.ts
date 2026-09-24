// Loads rn-runtime's manifest and template from the backend once, and builds
// preview documents for an iframe's srcdoc. The documents load the runtime
// from `${baseUrl}/rn-runtime/`; with an empty baseUrl that's the page's own
// origin, which the Vite dev server proxies to the backend. A srcdoc iframe
// resolves those URLs against its parent page.
import {
  DeviceProfile,
  PreviewMode,
  previewConfigJson,
  renderPreviewHtml,
  scriptTags,
} from "./previewHtml";

export interface RuntimeManifest {
  runtime: string;
  babel: string;
  template: string;
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

async function fetchOk(url: string): Promise<Response> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`${url}: HTTP ${response.status}`);
  }
  return response;
}

export function loadPreviewRuntime(baseUrl = ""): Promise<PreviewRuntime> {
  const base = baseUrl.replace(/\/+$/, "");
  let runtime = runtimes.get(base);
  if (!runtime) {
    runtime = (async () => {
      const manifest = (await (await fetchOk(`${base}/rn-runtime/manifest.json`)).json()) as RuntimeManifest;
      const template = await (await fetchOk(`${base}/rn-runtime/${manifest.template}`)).text();
      return { baseUrl: base, manifest, template };
    })();
    // A failed load (backend down, runtime not built) is retried next time.
    runtime.catch(() => runtimes.delete(base));
    runtimes.set(base, runtime);
  }
  return runtime;
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
