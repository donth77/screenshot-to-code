// Embedding App.jsx's images for the self-contained preview download.
//
// Generated screens load images by URL: extracted assets from the backend's
// /local-assets, and occasionally remote URLs (Replicate delivery URLs
// expire). The download must render offline, so each quoted URL literal
// whose response is an image is replaced by a data: URI. Anything else
// (links, failed or non-image responses) stays as written.

// A quoted http(s) URL or a root-relative /local-assets/ path.
const URL_LITERAL_RE = /(["'`])((?:https?:\/\/|\/local-assets\/)[^"'`\s\\]+)\1/g;

export function findUrlLiterals(source: string): string[] {
  const urls = new Set<string>();
  for (const match of source.matchAll(URL_LITERAL_RE)) {
    // A template literal with ${...} isn't a literal URL.
    if (match[1] === "`" && match[2].includes("${")) continue;
    urls.add(match[2]);
  }
  return [...urls];
}

// Returns a data: URI for an image, or null (not an image, or unreachable).
export type ImageFetcher = (url: string) => Promise<string | null>;

export interface InlinedSource {
  source: string;
  embedded: string[];
  failed: string[];
}

export async function inlineImageUrls(
  source: string,
  fetchImage: ImageFetcher,
  resolveUrl: (url: string) => string = (url) => url
): Promise<InlinedSource> {
  const urls = findUrlLiterals(source);
  const results = await Promise.all(
    urls.map(async (url) => {
      try {
        return { url, dataUrl: await fetchImage(resolveUrl(url)) };
      } catch {
        return { url, dataUrl: null };
      }
    })
  );
  let inlined = source;
  const embedded: string[] = [];
  const failed: string[] = [];
  for (const { url, dataUrl } of results) {
    if (!dataUrl) {
      failed.push(url);
      continue;
    }
    // Only the exact quoted literal: the same text elsewhere stays.
    inlined = inlined.replace(URL_LITERAL_RE, (literal, quote: string, found: string) =>
      found === url ? `${quote}${dataUrl}${quote}` : literal
    );
    embedded.push(url);
  }
  return { source: inlined, embedded, failed };
}
