// Reading React Native results that other views receive as plain data: the
// screenshot_preview tool summary, recorded files and preview pages.
import type { DeviceProfile } from "./previewHtml";

export interface ReactNativeRuntimeError {
  kind: string;
  message: string;
  fatal?: boolean;
  line?: number;
  rule?: string;
}

export interface ReactNativeScreenshot {
  status: string;
  platform: "ios" | "android";
  width: number;
  height: number;
  imageUrl: string | null;
  errors: ReactNativeRuntimeError[];
}

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

// screenshot_preview's summary for React Native (backend
// agent/tools/screenshot_preview.py): {status, runtime_errors, viewport,
// screenshots: [{viewport: "ios" | "android", image_url}]}. null for the
// desktop/mobile summary of other stacks.
export function parseReactNativeScreenshot(summary: unknown): ReactNativeScreenshot | null {
  const data = record(summary);
  const viewport = record(data?.viewport);
  const platform = viewport?.platform;
  if (platform !== "ios" && platform !== "android") return null;
  const screenshots = Array.isArray(data?.screenshots) ? data.screenshots : [];
  const imageUrl = record(screenshots[0])?.image_url;
  const errors = (Array.isArray(data?.runtime_errors) ? data.runtime_errors : [])
    .map(record)
    .filter((error): error is Record<string, unknown> => error !== null)
    .map((error) => ({
      kind: String(error.kind ?? "error"),
      message: String(error.message ?? ""),
      fatal: error.fatal === true,
      line: typeof error.line === "number" ? error.line : undefined,
      rule: typeof error.rule === "string" ? error.rule : undefined,
    }));
  return {
    status: typeof data?.status === "string" ? data.status : "ok",
    platform,
    width: Number(viewport?.width) || 0,
    height: Number(viewport?.height) || 0,
    imageUrl: typeof imageUrl === "string" ? imageUrl : null,
    errors,
  };
}

// Highlighting for a file the agent wrote.
export function codeLanguageForPath(path: unknown): "javascript" | "html" {
  return typeof path === "string" && /\.jsx?$/i.test(path) ? "javascript" : "html";
}

const CONFIG_RE = /<script id="rn-preview-config" type="application\/json">([\s\S]*?)<\/script>/;

// The device profile of a React Native preview page (eval outputs, recorded
// runs, downloads), or null for any other page.
export function reactNativePreviewProfile(html: string): DeviceProfile | null {
  const match = CONFIG_RE.exec(html);
  if (!match) return null;
  try {
    const profile = record(record(JSON.parse(match[1]))?.profile);
    if (profile && typeof profile.width === "number" && typeof profile.height === "number") {
      return profile as unknown as DeviceProfile;
    }
  } catch {
    // not a preview page after all
  }
  return null;
}
