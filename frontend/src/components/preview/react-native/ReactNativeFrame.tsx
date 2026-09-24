import { CSSProperties, RefObject, useEffect, useMemo, useRef, useState } from "react";
import { usePreviewRuntime } from "../../../lib/react-native/appRuntime";
import { HotSwapChannel, PreviewRequest } from "../../../lib/react-native/hotSwap";
import type { DeviceProfile, PreviewMode } from "../../../lib/react-native/previewHtml";
import { PreviewStatus, previewDocument } from "../../../lib/react-native/previewRuntime";

interface Props {
  code: string;
  profile: DeviceProfile;
  mode: PreviewMode;
  title: string;
  // Changing it reloads the document with the current code.
  refreshNonce?: number;
  // Load the runtime only once the frame scrolls into view (thumbnails).
  lazy?: boolean;
  onStatus?: (status: PreviewStatus) => void;
  frameRef?: RefObject<HTMLIFrameElement>;
  className?: string;
  style?: CSSProperties;
  sandbox?: string;
  testId?: string;
}

// An App.jsx rendered by rn-runtime in an iframe. The runtime loads once;
// later code, profile and mode changes are posted to it (hot-swap).
function ReactNativeFrame({
  code,
  profile,
  mode,
  title,
  refreshNonce = 0,
  lazy = false,
  onStatus,
  frameRef,
  className,
  style,
  sandbox,
  testId,
}: Props) {
  const localRef = useRef<HTMLIFrameElement>(null);
  const iframeRef = frameRef ?? localRef;
  const [visible, setVisible] = useState(!lazy);
  const { value: runtime, error } = usePreviewRuntime(visible);

  // Stable across renders unless something the frame would render changed.
  const profileKey = JSON.stringify(profile);
  const request = useMemo<PreviewRequest>(
    () => ({ source: code, profile: JSON.parse(profileKey) as DeviceProfile, mode }),
    [code, profileKey, mode]
  );
  const requestRef = useRef(request);

  const channelRef = useRef<HotSwapChannel | null>(null);
  if (!channelRef.current) {
    channelRef.current = new HotSwapChannel((next) =>
      iframeRef.current?.contentWindow?.postMessage({ type: "rn-preview:update", ...next }, "*")
    );
  }

  const onStatusRef = useRef(onStatus);
  useEffect(() => {
    onStatusRef.current = onStatus;
  }, [onStatus]);

  useEffect(() => {
    if (visible) return;
    const frame = iframeRef.current;
    if (!frame || typeof IntersectionObserver === "undefined") {
      setVisible(true);
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          setVisible(true);
          observer.disconnect();
        }
      },
      { rootMargin: "200px" }
    );
    observer.observe(frame);
    return () => observer.disconnect();
  }, [visible, iframeRef]);

  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      const frame = iframeRef.current;
      if (!frame || event.source !== frame.contentWindow) return;
      if (event.data?.type !== "rn-preview:status") return;
      const status = event.data as PreviewStatus;
      channelRef.current?.rendered(status.renderId);
      onStatusRef.current?.(status);
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [iframeRef]);

  // Build the document once the runtime is here, and again on refresh.
  useEffect(() => {
    const frame = iframeRef.current;
    if (!runtime || !frame) return;
    const { source, profile: loadProfile, mode: loadMode } = requestRef.current;
    channelRef.current?.loaded(requestRef.current);
    frame.srcdoc = previewDocument(runtime, source, loadProfile, loadMode);
  }, [runtime, refreshNonce, iframeRef]);

  useEffect(() => {
    requestRef.current = request;
    channelRef.current?.want(request);
  }, [request]);

  if (error) {
    return (
      <div
        className={`flex items-center justify-center bg-white p-6 text-center text-sm text-gray-500 dark:bg-zinc-900 dark:text-zinc-400 ${className ?? ""}`}
        style={style}
        data-testid={testId ? `${testId}-unavailable` : undefined}
      >
        {error}
      </div>
    );
  }

  return (
    <iframe
      ref={iframeRef}
      title={title}
      className={className}
      style={style}
      sandbox={sandbox}
      data-testid={testId}
      data-rn-preview=""
    />
  );
}

export default ReactNativeFrame;
