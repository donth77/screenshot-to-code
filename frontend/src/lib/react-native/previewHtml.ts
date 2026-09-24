// Fill rn-runtime's preview template: the TypeScript half of a two-language
// contract. backend/react_native/preview_html.py does the same substitution,
// and both must produce byte-identical output for the shared test vectors in
// rn-runtime/test-vectors/preview-html.json.
//
// The template has two placeholders:
//   __RN_PREVIEW_CONFIG__      compact JSON {source, profile, mode}, with "<"
//                              escaped so it can never close its <script>
//   <!--RN_PREVIEW_SCRIPTS-->  <script src> tags, or the scripts inlined
// Substitution is a single pass, so substituted text is never re-scanned.

export type PreviewMode = "final" | "streaming";

export interface DeviceProfile {
  platform: "ios" | "android";
  width: number;
  height: number;
  scale: number;
  insets: { top: number; right: number; bottom: number; left: number };
}

export const CONFIG_PLACEHOLDER = "__RN_PREVIEW_CONFIG__";
export const SCRIPTS_PLACEHOLDER = "<!--RN_PREVIEW_SCRIPTS-->";
const PLACEHOLDER_RE = /__RN_PREVIEW_CONFIG__|<!--RN_PREVIEW_SCRIPTS-->/g;

// "<!--", "<script" and "</script" would put the HTML tokenizer into a script
// data escaped state; \x3C is "<" in strings, template literals and regexes.
const INLINE_HAZARD_RE = /<(?=!--|\/?script)/gi;

const ATTRIBUTE_ESCAPES: Record<string, string> = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#x27;",
};

export function previewConfigJson(
  source: string,
  profile: object,
  mode: PreviewMode = "final"
): string {
  const json = JSON.stringify({ source, profile, mode }, (_key, value: unknown) => {
    if (typeof value === "number" && !Number.isFinite(value)) {
      throw new Error("preview config numbers must be finite");
    }
    return value;
  });
  return json.replace(/</g, "\\u003c");
}

// Tags that load Babel, then the runtime, from `${baseUrl}/rn-runtime/`.
// An empty baseUrl gives URLs relative to the page's origin.
export function scriptTags(baseUrl: string, runtimeFile: string, babelFile: string): string {
  const base = baseUrl.replace(/\/+$/, "");
  return [babelFile, runtimeFile]
    .map((name) => {
      const src = `${base}/rn-runtime/${name}`.replace(/[&<>"']/g, (c) => ATTRIBUTE_ESCAPES[c]);
      return `<script src="${src}"></script>`;
    })
    .join("\n");
}

export function inlineScript(js: string): string {
  return `<script>${js.replace(INLINE_HAZARD_RE, "\\x3C")}</script>`;
}

// Throws unless each placeholder appears exactly once, so a template edit
// that drops or duplicates one fails loudly.
export function renderPreviewHtml(template: string, configJson: string, scriptsHtml: string): string {
  for (const placeholder of [CONFIG_PLACEHOLDER, SCRIPTS_PLACEHOLDER]) {
    const count = template.split(placeholder).length - 1;
    if (count !== 1) {
      throw new Error(`template must contain ${placeholder} once, found ${count}`);
    }
  }
  return template.replace(PLACEHOLDER_RE, (match) =>
    match === CONFIG_PLACEHOLDER ? configJson : scriptsHtml
  );
}
