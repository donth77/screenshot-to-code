import { PointerEvent as ReactPointerEvent, useEffect, useMemo, useRef, useState } from "react";
import { imageSize, useDeviceTable } from "../../lib/react-native/appRuntime";
import {
  DeviceOverrides,
  Platform,
  ReactNativeDevice,
  contentHeight,
  cropBottomPx,
  cropTopPx,
  deviceLabel,
  insetFromOffset,
  resolveDevice,
  withChosenName,
} from "../../lib/react-native/devices";

interface Props {
  // The uploaded screenshot; null in text mode (the platform's default phone).
  screenshotUrl: string | null;
  overrides: DeviceOverrides;
  onChange: (overrides: DeviceOverrides) => void;
}

// Displayed height of the screenshot with its crop overlay.
const CROP_VIEW_HEIGHT = 420;

const MATCH_NOTES: Record<ReactNativeDevice["match"], string> = {
  exact: "Detected from the screenshot's size.",
  scaled: "Detected from the screenshot's shape (it was resized).",
  guessed: "Unknown size: the width is a guess. Pick the phone or check the crop.",
  default: "No screenshot: the platform's default phone.",
  override: "Adjusted by you.",
};

function CropHandle({
  edge,
  position,
  label,
  onDrag,
}: {
  edge: "top" | "bottom";
  position: number;
  label: string;
  onDrag: (clientY: number) => void;
}) {
  const dragging = useRef(false);
  const onPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    dragging.current = true;
    event.currentTarget.setPointerCapture(event.pointerId);
    event.preventDefault();
  };
  const onPointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (dragging.current) onDrag(event.clientY);
  };
  const onPointerUp = (event: ReactPointerEvent<HTMLDivElement>) => {
    dragging.current = false;
    event.currentTarget.releasePointerCapture(event.pointerId);
  };
  return (
    <div
      role="slider"
      aria-label={edge === "top" ? "Status bar crop" : "Home indicator crop"}
      aria-valuetext={label}
      tabIndex={0}
      data-testid={`rn-crop-handle-${edge}`}
      className="absolute inset-x-0 z-10 flex h-4 -translate-y-1/2 cursor-row-resize touch-none items-center"
      style={{ top: position }}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
    >
      <div className="h-0.5 w-full bg-violet-500" />
      <span
        className={`absolute right-1 whitespace-nowrap rounded bg-violet-600 px-1.5 py-0.5 text-[10px] font-medium text-white ${
          edge === "top" ? "top-3" : "bottom-3"
        }`}
      >
        {label}
      </span>
    </div>
  );
}

// The phone a React Native screen targets: detected from the screenshot and
// the device table, correctable by the user. The crop overlay shows (and
// sets) the status bar and home indicator strips cut off before the model
// sees the screenshot.
function ReactNativeDeviceControls({ screenshotUrl, overrides, onChange }: Props) {
  const { value: table, error } = useDeviceTable();
  const [size, setSize] = useState<{ width: number; height: number } | null>(null);
  const cropRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setSize(null);
    if (!screenshotUrl) return;
    let cancelled = false;
    imageSize(screenshotUrl).then(
      (loaded) => !cancelled && setSize(loaded),
      () => {
        /* App.tsx reports an unreadable screenshot on generate */
      }
    );
    return () => {
      cancelled = true;
    };
  }, [screenshotUrl]);

  const device = useMemo(
    () =>
      table && (size || !screenshotUrl)
        ? withChosenName(table, resolveDevice(table, size, overrides), overrides)
        : null,
    [table, size, screenshotUrl, overrides]
  );

  if (error) {
    return <p className="text-xs text-amber-600 dark:text-amber-400">{error}</p>;
  }
  if (!table || !device) {
    return <p className="text-xs text-gray-400 dark:text-zinc-500">Detecting the phone…</p>;
  }

  const unit = device.platform === "ios" ? "pt" : "dp";
  const phones = table.devices
    .map((entry, index) => ({ entry, index }))
    .filter(({ entry }) => entry.platform === device.platform);
  const chosenIndex = phones.find(
    ({ entry }) =>
      overrides.logicalWidth === entry.logicalWidth &&
      overrides.insetTop === (entry.insetTop ?? 0) &&
      overrides.insetBottom === (entry.insetBottom ?? 0)
  )?.index;

  const setPlatform = (platform: Platform) => {
    if (platform !== device.platform) onChange({ platform });
  };
  const choosePhone = (value: string) => {
    if (value === "auto") {
      onChange(overrides.platform ? { platform: overrides.platform } : {});
      return;
    }
    const entry = table.devices[Number(value)];
    onChange({
      platform: entry.platform,
      logicalWidth: entry.logicalWidth,
      insetTop: entry.insetTop ?? 0,
      insetBottom: entry.insetBottom ?? 0,
    });
  };
  const setWidth = (value: string) => {
    const width = Number(value);
    if (Number.isFinite(width) && width >= 200 && width <= 1100) {
      onChange({ ...overrides, platform: device.platform, logicalWidth: Math.round(width) });
    }
  };

  const displayScale = size ? CROP_VIEW_HEIGHT / size.height : 1;
  const topPx = cropTopPx(device) * displayScale;
  const bottomPx = cropBottomPx(device) * displayScale;
  const dragInset = (edge: "top" | "bottom", clientY: number) => {
    const box = cropRef.current?.getBoundingClientRect();
    if (!box) return;
    const offset = edge === "top" ? clientY - box.top : box.bottom - clientY;
    const inset = insetFromOffset(device, edge, offset / displayScale);
    onChange({
      ...overrides,
      platform: device.platform,
      ...(edge === "top" ? { insetTop: inset } : { insetBottom: inset }),
    });
  };

  return (
    <div className="flex flex-col gap-4 sm:flex-row" data-testid="rn-device-controls">
      {screenshotUrl && size && (
        <div
          ref={cropRef}
          className="relative mx-auto shrink-0 select-none overflow-hidden rounded-md border border-gray-200 dark:border-zinc-700"
          style={{ height: CROP_VIEW_HEIGHT, width: size.width * displayScale }}
        >
          <img
            src={screenshotUrl}
            alt="Uploaded phone screenshot with its crop"
            className="block h-full w-full"
            draggable={false}
          />
          <div className="absolute inset-x-0 top-0 bg-black/50" style={{ height: topPx }} />
          <div className="absolute inset-x-0 bottom-0 bg-black/50" style={{ height: bottomPx }} />
          <CropHandle
            edge="top"
            position={topPx}
            label={`Status bar ${device.insetTop} ${unit}`}
            onDrag={(clientY) => dragInset("top", clientY)}
          />
          <CropHandle
            edge="bottom"
            position={CROP_VIEW_HEIGHT - bottomPx}
            label={`${device.platform === "ios" ? "Home indicator" : "Navigation bar"} ${device.insetBottom} ${unit}`}
            onDrag={(clientY) => dragInset("bottom", clientY)}
          />
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col gap-3 text-sm">
        <div className="flex items-center gap-2">
          <span className="w-16 shrink-0 text-xs font-medium text-gray-500 dark:text-zinc-400">Platform</span>
          <div className="inline-flex rounded-lg bg-gray-100 p-1 dark:bg-zinc-800">
            {(["ios", "android"] as const).map((platform) => (
              <button
                key={platform}
                type="button"
                onClick={() => setPlatform(platform)}
                data-testid={`rn-platform-${platform}`}
                className={`rounded-md px-3 py-1 text-xs font-medium transition-all ${
                  device.platform === platform
                    ? "bg-white text-gray-900 shadow-sm dark:bg-zinc-600 dark:text-zinc-100"
                    : "text-gray-500 hover:text-gray-900 dark:text-zinc-400 dark:hover:text-zinc-200"
                }`}
              >
                {platform === "ios" ? "iOS" : "Android"}
              </button>
            ))}
          </div>
        </div>
        {screenshotUrl && (
          <>
            <label className="flex items-center gap-2">
              <span className="w-16 shrink-0 text-xs font-medium text-gray-500 dark:text-zinc-400">Phone</span>
              <select
                value={chosenIndex === undefined ? "auto" : String(chosenIndex)}
                onChange={(event) => choosePhone(event.target.value)}
                data-testid="rn-device-select"
                className="min-w-0 flex-1 rounded-md border border-gray-200 bg-white px-2 py-1.5 text-xs dark:border-zinc-700 dark:bg-zinc-900"
              >
                <option value="auto">Auto: {deviceLabel(resolveDevice(table, size, overrides.platform ? { platform: overrides.platform } : {}))}</option>
                {phones.map(({ entry, index }) => (
                  <option key={index} value={index}>
                    {entry.name} ({entry.logicalWidth} {unit})
                  </option>
                ))}
              </select>
            </label>
            <label className="flex items-center gap-2">
              <span className="w-16 shrink-0 text-xs font-medium text-gray-500 dark:text-zinc-400">Width</span>
              <input
                type="number"
                min={200}
                max={1100}
                value={device.logicalWidth}
                onChange={(event) => setWidth(event.target.value)}
                data-testid="rn-width-input"
                className="w-20 rounded-md border border-gray-200 bg-white px-2 py-1 text-xs dark:border-zinc-700 dark:bg-zinc-900"
              />
              <span className="text-xs text-gray-400 dark:text-zinc-500">{unit}</span>
            </label>
          </>
        )}
        <div className="space-y-1 text-xs text-gray-500 dark:text-zinc-400" data-testid="rn-device-summary">
          <p>
            <span className="font-medium text-gray-700 dark:text-zinc-200">{deviceLabel(device)}</span>
            {" · "}
            {device.logicalWidth} × {contentHeight(device)} {unit} content at {device.scale.toFixed(2)}×
          </p>
          <p>{MATCH_NOTES[device.match]}</p>
          {screenshotUrl && (
            <p>The shaded strips are cropped off: the model builds only the area between them.</p>
          )}
        </div>
        {Object.keys(overrides).length > 0 && (
          <button
            type="button"
            onClick={() => onChange({})}
            className="self-start text-xs text-gray-500 underline hover:text-gray-800 dark:text-zinc-400 dark:hover:text-zinc-200"
            data-testid="rn-device-reset"
          >
            Reset to detected
          </button>
        )}
      </div>
    </div>
  );
}

export default ReactNativeDeviceControls;
