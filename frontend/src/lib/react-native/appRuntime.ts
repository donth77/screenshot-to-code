// The app's React Native preview runtime, served by the backend at
// /rn-runtime (through the Vite proxy in development). Loaded once and cached.
import { useEffect, useState } from "react";
import { HTTP_BACKEND_URL } from "../../config";
import { DeviceTable } from "./devices";
import { PreviewRuntime, loadDeviceTable, loadPreviewRuntime } from "./previewRuntime";

export const RUNTIME_UNAVAILABLE_MESSAGE =
  "The React Native preview runtime isn't available. Build it with: cd rn-runtime && pnpm build, then restart the backend.";

export function appPreviewRuntime(): Promise<PreviewRuntime> {
  return loadPreviewRuntime(HTTP_BACKEND_URL);
}

export function appDeviceTable(): Promise<DeviceTable> {
  return loadDeviceTable(HTTP_BACKEND_URL);
}

interface Resource<T> {
  value: T | null;
  error: string | null;
}

function useCachedResource<T>(load: () => Promise<T>, enabled: boolean): Resource<T> {
  const [resource, setResource] = useState<Resource<T>>({ value: null, error: null });
  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    load().then(
      (value) => !cancelled && setResource({ value, error: null }),
      (error: unknown) => {
        console.error("React Native preview runtime failed to load", error);
        if (!cancelled) setResource({ value: null, error: RUNTIME_UNAVAILABLE_MESSAGE });
      }
    );
    return () => {
      cancelled = true;
    };
  }, [load, enabled]);
  return resource;
}

export function usePreviewRuntime(enabled = true): Resource<PreviewRuntime> {
  return useCachedResource(appPreviewRuntime, enabled);
}

export function useDeviceTable(enabled = true): Resource<DeviceTable> {
  return useCachedResource(appDeviceTable, enabled);
}
