// Which phone a screenshot came from, and the preview profile that lines up
// with it: the TypeScript port of backend/react_native/profiles.py. Both run
// the vectors in rn-runtime/test-vectors/device-detection.json, so the phone
// the UI previews is the one the backend prompts for and screenshots.
//
// DESIGN.md §7: scale = pixel width / logical width; the status bar and home
// indicator (the safe-area insets) are cropped off the input; the preview
// renders the remaining content area at the same scale.
import { DeviceProfile } from "./previewHtml";

export type Platform = "ios" | "android";
export type DeviceMatch = "exact" | "scaled" | "guessed" | "default" | "override";

export interface DeviceTableEntry {
  pixelWidth: number;
  pixelHeight: number;
  platform: Platform;
  name: string;
  logicalWidth: number;
  logicalHeight: number;
  scale: number;
  insetTop: number | null;
  insetBottom: number | null;
  status: string;
}

export interface DeviceTable {
  fallbacks: Record<Platform, { logicalWidth: number }>;
  devices: DeviceTableEntry[];
}

export interface ReactNativeDevice {
  platform: Platform;
  name: string | null; // null when the device was guessed
  logicalWidth: number;
  scale: number; // screenshot pixels per pt (iOS) or dp (Android)
  insetTop: number; // pt / dp above the content: status bar, cutout
  insetBottom: number; // pt / dp below it: home indicator, navigation bar
  pixelWidth: number;
  pixelHeight: number;
  match: DeviceMatch;
}

// The user's corrections, sent to the backend as `reactNativeProfile`.
export interface DeviceOverrides {
  platform?: Platform;
  logicalWidth?: number;
  insetTop?: number;
  insetBottom?: number;
}

// The phone a React Native project targets, kept on its commits: the device
// the preview renders, and the overrides that make the backend pick it too.
export interface ReactNativeTarget {
  device: ReactNativeDevice;
  overrides: DeviceOverrides;
}

// A downscaled screenshot keeps its shape: aspect ratios this close match.
const ASPECT_TOLERANCE = 0.004;
const IOS_LOGICAL_WIDTHS = [375, 390, 393, 402, 414, 428, 430, 440];

// Python's round(): halves go to the even neighbour.
export function roundHalfEven(value: number): number {
  const floor = Math.floor(value);
  const diff = value - floor;
  if (diff > 0.5) return floor + 1;
  if (diff < 0.5) return floor;
  return floor % 2 === 0 ? floor : floor + 1;
}

export function cropTopPx(device: ReactNativeDevice): number {
  return roundHalfEven(device.insetTop * device.scale);
}

export function cropBottomPx(device: ReactNativeDevice): number {
  return roundHalfEven(device.insetBottom * device.scale);
}

// Logical height of the screenshot once the insets are cropped off.
export function contentHeight(device: ReactNativeDevice): number {
  return roundHalfEven(
    (device.pixelHeight - cropTopPx(device) - cropBottomPx(device)) / device.scale
  );
}

// "iPhone 14 Pro, 15, 15 Pro, 16", or a generic name for a guessed size.
export function deviceLabel(device: ReactNativeDevice): string {
  const name = device.name ?? (device.platform === "ios" ? "iPhone" : "Android phone");
  return device.match === "guessed" ? `${name} (size guessed)` : name;
}

// The profile the preview renders: the content area at the screenshot's scale.
export function previewProfile(device: ReactNativeDevice): DeviceProfile {
  return {
    platform: device.platform,
    width: device.logicalWidth,
    height: contentHeight(device),
    scale: device.scale,
    insets: { top: 0, right: 0, bottom: 0, left: 0 },
  };
}

function fromEntry(
  entry: DeviceTableEntry,
  pixelWidth: number,
  pixelHeight: number,
  match: DeviceMatch
): ReactNativeDevice {
  const logicalWidth = Math.trunc(entry.logicalWidth);
  return {
    platform: entry.platform,
    name: String(entry.name),
    logicalWidth,
    // From the pixels, not the table's rounded scale: the render must be exactly as wide.
    scale: pixelWidth / logicalWidth,
    insetTop: entry.insetTop || 0,
    insetBottom: entry.insetBottom || 0,
    pixelWidth,
    pixelHeight,
    match,
  };
}

function guessPlatform(pixelWidth: number): Platform {
  for (const scale of [3, 2]) {
    if (pixelWidth % scale === 0 && IOS_LOGICAL_WIDTHS.includes(pixelWidth / scale)) {
      return "ios";
    }
  }
  return "android";
}

// Whether a screenshot this wide can be that device's screen: a downscaled
// copy of its screenshots, or the same logical size at a whole 2x or 3x (an
// iPhone XS Max has the XR's shape at 3x). A 1080 x 1920 Android screenshot
// is neither for an iPhone SE (375 pt at 2x).
function plausibleScale(pixelWidth: number, entry: DeviceTableEntry): boolean {
  const scale = pixelWidth / entry.logicalWidth;
  const whole = Math.round(scale);
  return (
    scale <= entry.pixelWidth / entry.logicalWidth + 1e-9 ||
    ((whole === 2 || whole === 3) && Math.abs(scale - whole) < 0.01)
  );
}

// Exact size match, then a scaled screenshot of a known shape, then a guess.
export function detectDevice(
  pixelWidth: number,
  pixelHeight: number,
  table: DeviceTable,
  platform?: Platform
): ReactNativeDevice {
  const devices = table.devices.filter((entry) => !platform || entry.platform === platform);
  const exact = devices.find(
    (entry) => entry.pixelWidth === pixelWidth && entry.pixelHeight === pixelHeight
  );
  if (exact) return fromEntry(exact, pixelWidth, pixelHeight, "exact");

  if (pixelHeight > pixelWidth) {
    const aspect = pixelHeight / pixelWidth;
    const shaped = devices
      .map((entry, index) => ({
        entry,
        index,
        distance: Math.abs(entry.pixelHeight / entry.pixelWidth - aspect),
      }))
      .filter(({ entry, distance }) => distance <= ASPECT_TOLERANCE * aspect && plausibleScale(pixelWidth, entry))
      .sort((a, b) => a.distance - b.distance || a.index - b.index);
    // Only when every device of that shape is on the same platform.
    if (shaped.length && new Set(shaped.map(({ entry }) => entry.platform)).size === 1) {
      return fromEntry(shaped[0].entry, pixelWidth, pixelHeight, "scaled");
    }
  }

  const guessed = platform || guessPlatform(pixelWidth);
  const logicalWidth = Math.trunc(table.fallbacks[guessed].logicalWidth);
  return {
    platform: guessed,
    name: null,
    logicalWidth,
    scale: pixelWidth / logicalWidth,
    insetTop: 0,
    insetBottom: 0,
    pixelWidth,
    pixelHeight,
    match: "guessed",
  };
}

// The phone for a generation with no screenshot: the platform's first known device.
export function defaultDevice(table: DeviceTable, platform: Platform = "ios"): ReactNativeDevice {
  const entry = table.devices.find((device) => device.platform === platform);
  if (!entry) throw new Error(`no ${platform} device in the device table`);
  return fromEntry(entry, entry.pixelWidth, entry.pixelHeight, "default");
}

function numberIn(value: unknown, low: number, high: number): number | null {
  return typeof value === "number" && Number.isFinite(value) && value >= low && value <= high
    ? value
    : null;
}

function isPlatform(value: unknown): value is Platform {
  return value === "ios" || value === "android";
}

// The user's corrections (the crop overlay): platform, logical width and insets.
export function applyOverrides(
  device: ReactNativeDevice,
  overrides: Record<string, unknown>,
  table: DeviceTable
): ReactNativeDevice {
  const platform = overrides.platform;
  if (isPlatform(platform) && platform !== device.platform) {
    device =
      device.match === "default"
        ? defaultDevice(table, platform)
        : detectDevice(device.pixelWidth, device.pixelHeight, table, platform);
  }
  const changes: Partial<ReactNativeDevice> = {};
  const logicalWidth = numberIn(overrides.logicalWidth, 200, 1100);
  if (logicalWidth !== null) {
    changes.logicalWidth = Math.trunc(logicalWidth);
    changes.scale = device.pixelWidth / Math.trunc(logicalWidth);
  }
  const insetTop = numberIn(overrides.insetTop, 0, 200);
  if (insetTop !== null) changes.insetTop = insetTop;
  const insetBottom = numberIn(overrides.insetBottom, 0, 200);
  if (insetBottom !== null) changes.insetBottom = insetBottom;
  return Object.keys(changes).length ? { ...device, ...changes, match: "override" } : device;
}

// resolveDevice keeps the detected phone's name, as the backend does (it
// never uses the name). For display: once the user sets the width, name the
// table phone that matches what they chose, or none.
export function withChosenName(
  table: DeviceTable,
  device: ReactNativeDevice,
  overrides: DeviceOverrides
): ReactNativeDevice {
  if (overrides.logicalWidth === undefined) return device;
  const entry = table.devices.find(
    (candidate) =>
      candidate.platform === device.platform &&
      candidate.logicalWidth === device.logicalWidth &&
      (candidate.insetTop ?? 0) === device.insetTop &&
      (candidate.insetBottom ?? 0) === device.insetBottom
  );
  return { ...device, name: entry ? entry.name : null };
}

// Keep at least this much of the screen (pt / dp) between the crop strips.
const MIN_CONTENT = 100;
const MAX_INSET = 200; // the backend ignores larger overrides

// An inset (pt / dp, one decimal) from a crop handle dragged `offsetPx`
// screenshot pixels from its edge, leaving room for the other strip.
export function insetFromOffset(
  device: ReactNativeDevice,
  edge: "top" | "bottom",
  offsetPx: number
): number {
  const other = edge === "top" ? device.insetBottom : device.insetTop;
  const limit = Math.min(MAX_INSET, device.pixelHeight / device.scale - other - MIN_CONTENT);
  const inset = Math.max(0, Math.min(limit, offsetPx / device.scale));
  return Math.round(inset * 10) / 10;
}

// What the backend decides for a request (react_native/inputs.py): the
// screenshot's size when there is one, the platform's default phone otherwise.
export function resolveDevice(
  table: DeviceTable,
  size: { width: number; height: number } | null,
  overrides: DeviceOverrides = {}
): ReactNativeDevice {
  const raw = overrides as Record<string, unknown>;
  if (!size) {
    const platform: Platform = overrides.platform === "android" ? "android" : "ios";
    return applyOverrides(defaultDevice(table, platform), raw, table);
  }
  const hint = isPlatform(raw.platform) ? raw.platform : undefined;
  return applyOverrides(detectDevice(size.width, size.height, table, hint), raw, table);
}
