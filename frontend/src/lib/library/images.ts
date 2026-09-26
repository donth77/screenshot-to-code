// Downscaled copies of data-URL images, for the library's thumbnails and for
// shrinking the agent's inline screenshots before a project is saved.

const shrunk = new Map<string, Promise<string>>();

async function downscale(dataUrl: string, maxWidth: number, quality: number): Promise<string> {
  try {
    const bitmap = await createImageBitmap(await (await fetch(dataUrl)).blob());
    const scale = Math.min(1, maxWidth / bitmap.width);
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(bitmap.width * scale));
    canvas.height = Math.max(1, Math.round(bitmap.height * scale));
    const context = canvas.getContext("2d");
    if (!context) return dataUrl;
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    bitmap.close();
    return canvas.toDataURL("image/jpeg", quality);
  } catch {
    return dataUrl;
  }
}

// The same image is saved many times (every autosave), so results are cached.
export function shrinkImage(dataUrl: string): Promise<string> {
  let result = shrunk.get(dataUrl);
  if (!result) {
    result = downscale(dataUrl, 480, 0.7);
    shrunk.set(dataUrl, result);
  }
  return result;
}

export async function thumbnail(dataUrl: string | undefined): Promise<string | null> {
  if (!dataUrl || !dataUrl.startsWith("data:image/")) return null;
  const small = await downscale(dataUrl, 240, 0.7);
  return small === dataUrl ? null : small;
}
