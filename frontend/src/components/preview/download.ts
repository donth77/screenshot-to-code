import { HTTP_BACKEND_URL } from "../../config";
import { normalizeBabelCdn } from "../../lib/babelCdn";
import { appPreviewRuntime } from "../../lib/react-native/appRuntime";
import { inlineImageUrls } from "../../lib/react-native/assets";
import { ReactNativeDevice, previewProfile } from "../../lib/react-native/devices";
import { inlinePreviewDocument } from "../../lib/react-native/previewRuntime";

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function filenameFromContentDisposition(contentDisposition: string | null) {
  const match = contentDisposition?.match(/filename="?([^"]+)"?/i);
  return match?.[1] ?? "screenshot-to-code-export.zip";
}

export const downloadCode = async (code: string) => {
  try {
    const response = await fetch(`${HTTP_BACKEND_URL}/api/export`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        code,
        baseUrl: window.location.href,
      }),
    });

    if (!response.ok) {
      throw new Error(`Export failed with status ${response.status}`);
    }

    const blob = await response.blob();
    downloadBlob(
      blob,
      filenameFromContentDisposition(response.headers.get("Content-Disposition"))
    );
  } catch (error) {
    console.warn("Falling back to downloading index.html", error);
    downloadBlob(
      new Blob([normalizeBabelCdn(code)], { type: "text/html" }),
      "index.html"
    );
  }
};

async function fetchImageAsDataUrl(url: string): Promise<string | null> {
  // Skip the HTTP cache: the preview's <img> loaded the same URL without an
  // Origin header, and that cached response lacks the CORS header a fetch
  // needs (the backend doesn't send Vary: Origin).
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) return null;
  const blob = await response.blob();
  if (!blob.type.startsWith("image/")) return null;
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(blob);
  });
}

// The downloaded page fills a phone's screen. In a wider window, frame it at
// the phone's size instead of stretching the layout across the window.
function phoneFrameStyle(width: number, height: number): string {
  return `<style>@media (min-width: ${width + 160}px) {
  html { background: #e5e7eb; }
  body { width: ${width}px; height: ${height}px; margin: 40px auto; border-radius: 28px; box-shadow: 0 12px 48px rgba(0, 0, 0, 0.25); }
}</style>
`;
}

// URLs in App.jsx that look like images but couldn't be embedded.
function looksLikeImage(url: string): boolean {
  return /\/local-assets\/|\.(png|jpe?g|gif|webp|svg)(\?|$)/i.test(url);
}

// React Native: one self-contained HTML file with Babel, the runtime and
// App.jsx's images inlined, so it opens from file:// with no network.
export const downloadReactNativePreview = async (
  code: string,
  device: ReactNativeDevice
): Promise<{ missingImages: string[] }> => {
  const runtime = await appPreviewRuntime();
  const { source, failed } = await inlineImageUrls(
    code,
    fetchImageAsDataUrl,
    (url) => new URL(url, HTTP_BACKEND_URL).href
  );
  const profile = previewProfile(device);
  const html = await inlinePreviewDocument(
    runtime,
    source,
    profile,
    phoneFrameStyle(profile.width, profile.height)
  );
  downloadBlob(new Blob([html], { type: "text/html" }), "App-preview.html");
  return { missingImages: failed.filter(looksLikeImage) };
};
