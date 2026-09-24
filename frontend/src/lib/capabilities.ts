import { useEffect, useState } from "react";
import { HTTP_BACKEND_URL } from "../config";

// GET /api/capabilities (backend/routes/capabilities.py).
export interface Capabilities {
  screenshot_preview: boolean;
  // rn-runtime/dist is built: the React Native stack can be previewed.
  react_native_preview: boolean;
}

let capabilities: Promise<Capabilities> | null = null;

function loadCapabilities(): Promise<Capabilities> {
  if (!capabilities) {
    capabilities = fetch(`${HTTP_BACKEND_URL}/api/capabilities`).then((response) => {
      if (!response.ok) throw new Error(`capabilities: HTTP ${response.status}`);
      return response.json() as Promise<Capabilities>;
    });
    // Retry next time if the backend was unreachable.
    capabilities.catch(() => {
      capabilities = null;
    });
  }
  return capabilities;
}

// null until the backend answers (and while it's unreachable).
export function useCapabilities(): Capabilities | null {
  const [value, setValue] = useState<Capabilities | null>(null);
  useEffect(() => {
    let cancelled = false;
    loadCapabilities().then(
      (loaded) => !cancelled && setValue(loaded),
      () => {
        /* unknown: callers treat null as "don't know" */
      }
    );
    return () => {
      cancelled = true;
    };
  }, []);
  return value;
}
