// The app's React Native preview runtime, served by the backend at
// /rn-runtime (through the Vite proxy in development). Loaded once and cached.
import { useEffect, useState } from "react";
import { HTTP_BACKEND_URL } from "../../config";
import {
  DeviceOverrides,
  DeviceTable,
  ReactNativeTarget,
  ScreenshotPixels,
  resolveDevice,
  withChosenName,
} from "./devices";
import { PreviewRuntime, loadDeviceTable, loadExpoSdk, loadPreviewRuntime } from "./previewRuntime";
import type { ExpoSdk } from "./snack";
import { luminance } from "./systemBars";

export const RUNTIME_UNAVAILABLE_MESSAGE =
  "The React Native preview runtime isn't available. Build it with: cd rn-runtime && pnpm build, then restart the backend.";

export function appPreviewRuntime(): Promise<PreviewRuntime> {
  return loadPreviewRuntime(HTTP_BACKEND_URL);
}

export function appDeviceTable(): Promise<DeviceTable> {
  return loadDeviceTable(HTTP_BACKEND_URL);
}

export function appExpoSdk(): Promise<ExpoSdk> {
  return loadExpoSdk(HTTP_BACKEND_URL);
}

class ScreenshotDecodeError extends Error {}

function loadImage(url: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new ScreenshotDecodeError("The screenshot could not be read as an image."));
    image.src = url;
  });
}

// The pixel size PIL reads on the backend, and the pixels' luminance for
// reading an unknown Android phone's bars. Phone screenshots are PNGs; a JPEG
// with an EXIF rotation would decode rotated here and not there. If the
// pixels can't be read, there's no luminance and no bars are read.
export async function readScreenshot(url: string): Promise<ScreenshotPixels> {
  const image = await loadImage(url);
  const size = { width: image.naturalWidth, height: image.naturalHeight };
  try {
    const canvas = document.createElement("canvas");
    canvas.width = size.width;
    canvas.height = size.height;
    const context = canvas.getContext("2d", { willReadFrequently: true });
    if (!context) return size;
    context.drawImage(image, 0, 0);
    const { data } = context.getImageData(0, 0, size.width, size.height);
    return { ...size, luminance: luminance(data, size.width, size.height) };
  } catch {
    return size;
  }
}

// A message for a failed resolveTarget.
export function describeTargetError(error: unknown): string {
  return error instanceof ScreenshotDecodeError ? error.message : RUNTIME_UNAVAILABLE_MESSAGE;
}

// The phone for a screenshot (or, without one, the platform's default phone),
// resolved exactly as the backend will resolve it.
export async function resolveTarget(
  screenshotUrl: string | null,
  overrides: DeviceOverrides = {}
): Promise<ReactNativeTarget> {
  const [table, screenshot] = await Promise.all([
    appDeviceTable(),
    screenshotUrl ? readScreenshot(screenshotUrl) : Promise.resolve(null),
  ]);
  const device = resolveDevice(table, screenshot, overrides);
  // The backend reads an unknown Android phone's bars too. Sending the ones
  // read here means a screenshot decoded differently there can't be cropped
  // differently from the preview.
  const readBars = Boolean(screenshot?.luminance) && device.name === null && device.platform === "android";
  return {
    device: withChosenName(table, device, overrides),
    overrides: readBars ? { ...overrides, insetTop: device.insetTop, insetBottom: device.insetBottom } : overrides,
  };
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

export function useExpoSdk(enabled = true): Resource<ExpoSdk> {
  return useCachedResource(appExpoSdk, enabled);
}
