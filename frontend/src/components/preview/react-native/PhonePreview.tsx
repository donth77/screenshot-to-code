import { useEffect, useMemo, useRef, useState } from "react";
import {
  ReactNativeDevice,
  deviceLabel,
  previewProfile,
} from "../../../lib/react-native/devices";
import type { PreviewMode } from "../../../lib/react-native/previewHtml";
import type { PreviewStatus } from "../../../lib/react-native/previewRuntime";
import ReactNativeFrame from "./ReactNativeFrame";
import {
  SelectAndEditOptions,
  useSelectAndEditFrame,
} from "../../select-and-edit/useSelectAndEditFrame";
import {
  describeReactNativeElement,
  nearestTestIdElement,
  reactNativeElementLabel,
} from "../../select-and-edit/utils";

// pt around the screen, drawn as the phone's bezel.
const BEZEL = 12;
// Keep this much of the pane free around the phone.
const MARGIN = 16;

// Select the nearest element with a testID, and label the rings with it.
const TEST_ID_SELECTION: SelectAndEditOptions = {
  resolveTarget: nearestTestIdElement,
  describeTarget: (element) => reactNativeElementLabel(describeReactNativeElement(element)),
};

interface Props {
  code: string;
  device: ReactNativeDevice;
  mode: PreviewMode;
  refreshNonce: number;
}

// The status bar and home indicator were cropped from the screenshot, so the
// preview renders only the content area between them. These bands stand in
// for the system UI and are never part of the render.
function SystemBand({
  height,
  edge,
  platform,
}: {
  height: number;
  edge: "top" | "bottom";
  platform: ReactNativeDevice["platform"];
}) {
  if (height <= 0) return null;
  let mark = null;
  let align = "items-center";
  if (edge === "top" && platform === "ios" && height >= 54) {
    // Dynamic Island phones (59 pt and up).
    mark = <div className="h-[30px] w-[110px] rounded-full bg-black" />;
  } else if (edge === "top" && platform === "ios" && height >= 44) {
    // Notch phones (44 to 50 pt).
    mark = <div className="h-[30px] w-[160px] rounded-b-[18px] bg-black" />;
    align = "items-start";
  } else if (edge === "top" && platform === "android") {
    mark = <div className="h-3 w-3 rounded-full bg-black" />;
  } else if (edge === "bottom") {
    mark = (
      <div
        className={`rounded-full bg-zinc-500 ${
          platform === "ios" ? "h-[5px] w-[134px]" : "h-1 w-[108px]"
        }`}
      />
    );
  }
  return (
    <div
      className={`flex shrink-0 justify-center bg-zinc-800 ${align}`}
      style={{ height }}
      title={
        edge === "top"
          ? "Status bar area: cropped from the screenshot and drawn by the phone, not by App.jsx"
          : "Home indicator area: cropped from the screenshot and drawn by the phone, not by App.jsx"
      }
    >
      {mark}
    </div>
  );
}

function StatusPill({
  status,
  expanded,
  onToggle,
}: {
  status: PreviewStatus | null;
  expanded: boolean;
  onToggle: () => void;
}) {
  if (!status) {
    return <span className="text-gray-400 dark:text-zinc-500">Loading preview…</span>;
  }
  const fatal = status.errors.filter((error) => error.fatal).length;
  const warnings = status.errors.length - fatal;
  const [label, tone] =
    status.status === "streaming"
      ? ["Writing App.jsx…", "bg-sky-50 text-sky-700 dark:bg-sky-900/30 dark:text-sky-300"]
      : status.status === "error"
        ? [
            `${fatal || status.errors.length} error${(fatal || status.errors.length) === 1 ? "" : "s"}`,
            "bg-red-50 text-red-700 dark:bg-red-900/30 dark:text-red-300",
          ]
        : status.status === "degraded"
          ? [
              `${warnings} warning${warnings === 1 ? "" : "s"}`,
              "bg-amber-50 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300",
            ]
          : ["Rendered", "bg-emerald-50 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300"];
  const hasErrors = status.errors.length > 0;
  return (
    <button
      type="button"
      onClick={onToggle}
      disabled={!hasErrors}
      aria-expanded={hasErrors ? expanded : undefined}
      className={`rounded-full px-2 py-0.5 font-medium ${tone} ${hasErrors ? "cursor-pointer" : "cursor-default"}`}
      data-testid="rn-preview-status"
      data-status={status.status}
    >
      {label}
    </button>
  );
}

// App.jsx on a phone: one viewport at the target device's content size,
// scaled down to fit the pane.
function PhonePreview({ code, device, mode, refreshNonce }: Props) {
  const areaRef = useRef<HTMLDivElement>(null);
  const frameRef = useRef<HTMLIFrameElement>(null);
  useSelectAndEditFrame(frameRef, TEST_ID_SELECTION);
  const [scale, setScale] = useState(1);
  const [status, setStatus] = useState<PreviewStatus | null>(null);
  const [errorsExpanded, setErrorsExpanded] = useState(false);

  const profile = useMemo(() => previewProfile(device), [device]);
  const radius = Math.min(40, Math.max(12, device.insetTop, device.insetBottom));
  const phoneWidth = profile.width + BEZEL * 2;
  const phoneHeight = device.insetTop + profile.height + device.insetBottom + BEZEL * 2;
  const unit = device.platform === "ios" ? "pt" : "dp";

  useEffect(() => {
    const area = areaRef.current;
    if (!area) return;
    const update = () => {
      const width = area.clientWidth - MARGIN * 2;
      const height = area.clientHeight - MARGIN * 2;
      if (width <= 0 || height <= 0) return;
      setScale(Math.min(1, width / phoneWidth, height / phoneHeight));
    };
    update();
    const observer = new ResizeObserver(update);
    observer.observe(area);
    return () => observer.disconnect();
  }, [phoneWidth, phoneHeight]);

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-gray-100 dark:bg-zinc-900" data-testid="rn-phone-preview">
      <div
        ref={areaRef}
        className="flex min-h-0 flex-1 items-start justify-center overflow-hidden"
        style={{ padding: MARGIN }}
      >
        <div className="shrink-0" style={{ width: phoneWidth * scale, height: phoneHeight * scale }}>
          <div
            className="bg-zinc-900 shadow-2xl ring-1 ring-black/10 dark:ring-white/10"
            style={{
              width: phoneWidth,
              height: phoneHeight,
              padding: BEZEL,
              borderRadius: radius + BEZEL,
              transform: `scale(${scale})`,
              transformOrigin: "top left",
            }}
          >
            <div className="flex h-full w-full flex-col overflow-hidden bg-white" style={{ borderRadius: radius }}>
              <SystemBand height={device.insetTop} edge="top" platform={device.platform} />
              <ReactNativeFrame
                code={code}
                profile={profile}
                mode={mode}
                refreshNonce={refreshNonce}
                onStatus={setStatus}
                frameRef={frameRef}
                title="React Native preview"
                testId="rn-preview-frame"
                className="block shrink-0 border-0 bg-white"
                style={{ width: profile.width, height: profile.height }}
              />
              <SystemBand height={device.insetBottom} edge="bottom" platform={device.platform} />
            </div>
          </div>
        </div>
      </div>
      <div className="shrink-0 border-t border-gray-200 bg-white px-4 py-2 text-xs text-gray-600 dark:border-zinc-800 dark:bg-zinc-950 dark:text-zinc-300">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className="font-medium" data-testid="rn-preview-device">
            {deviceLabel(device)}
          </span>
          <span className="text-gray-400 dark:text-zinc-500">
            {profile.width} × {profile.height} {unit} content
            {scale < 1 ? ` · shown at ${Math.round(scale * 100)}%` : ""}
          </span>
          <span className="ml-auto">
            <StatusPill
              status={status}
              expanded={errorsExpanded}
              onToggle={() => setErrorsExpanded((open) => !open)}
            />
          </span>
        </div>
        {errorsExpanded && status && status.errors.length > 0 && (
          <ul className="mt-2 max-h-40 space-y-1.5 overflow-y-auto" data-testid="rn-preview-errors">
            {status.errors.map((error, index) => (
              <li key={`${error.kind}-${index}`} className="font-mono text-[11px] leading-4">
                <span className={error.fatal ? "text-red-600 dark:text-red-400" : "text-amber-600 dark:text-amber-400"}>
                  {error.kind}
                  {error.rule ? `/${error.rule}` : ""}
                  {error.line ? ` App.jsx:${error.line}` : ""}
                </span>{" "}
                <span className="whitespace-pre-wrap break-words">{error.message}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

export default PhonePreview;
