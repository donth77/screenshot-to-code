import { CSSProperties, useEffect, useMemo, useState } from "react";
import type { DeviceProfile } from "../../lib/react-native/previewHtml";
import { reactNativePreviewProfile } from "../../lib/react-native/toolOutput";

interface Props {
  title?: string;
  src?: string;
  srcDoc?: string;
  className?: string;
  style?: CSSProperties;
  frameRef?: (element: HTMLIFrameElement | null) => void;
}

// An eval output or a recorded run's page. React Native outputs are preview
// pages built for one phone (backend react_native/render.py), so they show at
// that phone's size instead of stretched across the pane. Other pages render
// exactly as before.
function PreviewPageFrame({ title, src, srcDoc, className = "", style, frameRef }: Props) {
  const docProfile = useMemo(
    () => (srcDoc !== undefined ? reactNativePreviewProfile(srcDoc) : null),
    [srcDoc]
  );
  const [fetched, setFetched] = useState<{ src: string; profile: DeviceProfile | null } | null>(null);

  useEffect(() => {
    if (srcDoc !== undefined || !src) return;
    let cancelled = false;
    fetch(src)
      .then((response) => (response.ok ? response.text() : ""))
      .then(
        (text) => !cancelled && setFetched({ src, profile: reactNativePreviewProfile(text) }),
        () => {
          /* leave it full size */
        }
      );
    return () => {
      cancelled = true;
    };
  }, [src, srcDoc]);

  const profile =
    srcDoc !== undefined ? docProfile : fetched && fetched.src === src ? fetched.profile : null;
  if (!profile) {
    return <iframe ref={frameRef} title={title} src={src} srcDoc={srcDoc} className={className} style={style} />;
  }
  return (
    <div
      className={`${className} flex justify-center overflow-auto bg-zinc-100 p-4`}
      style={style}
      data-testid="rn-eval-frame"
    >
      <iframe
        ref={frameRef}
        title={title}
        src={src}
        srcDoc={srcDoc}
        className="shrink-0 border-0 bg-white shadow-lg"
        style={{ width: profile.width, height: profile.height }}
      />
    </div>
  );
}

export default PreviewPageFrame;
