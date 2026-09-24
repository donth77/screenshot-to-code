import * as fs from "fs";
import * as path from "path";
import {
  PreviewMode,
  inlineScript,
  previewConfigJson,
  renderPreviewHtml,
  scriptTags,
} from "./previewHtml";

// Shared with backend/tests/test_rn_preview_html.py: both implementations
// must produce every expected string exactly.
interface Vectors {
  configJson: { name: string; source: string; profile: object; mode: PreviewMode; expected: string }[];
  inlineScript: { name: string; js: string; expected: string }[];
  scriptTags: { name: string; baseUrl: string; runtime: string; babel: string; expected: string }[];
  render: { name: string; template: string; configJson: string; scripts: string; expected: string }[];
  renderErrors: { name: string; template: string }[];
}

const vectors: Vectors = JSON.parse(
  fs.readFileSync(
    path.resolve(__dirname, "../../../../rn-runtime/test-vectors/preview-html.json"),
    "utf8"
  )
);

describe("previewConfigJson", () => {
  test.each(vectors.configJson)("$name", ({ source, profile, mode, expected }) => {
    expect(previewConfigJson(source, profile, mode)).toBe(expected);
  });

  test("refuses non-finite numbers instead of writing null", () => {
    expect(() => previewConfigJson("", { scale: Number.NaN })).toThrow();
  });
});

describe("inlineScript", () => {
  test.each(vectors.inlineScript)("$name", ({ js, expected }) => {
    expect(inlineScript(js)).toBe(expected);
  });
});

describe("scriptTags", () => {
  test.each(vectors.scriptTags)("$name", ({ baseUrl, runtime, babel, expected }) => {
    expect(scriptTags(baseUrl, runtime, babel)).toBe(expected);
  });
});

describe("renderPreviewHtml", () => {
  test.each(vectors.render)("$name", ({ template, configJson, scripts, expected }) => {
    expect(renderPreviewHtml(template, configJson, scripts)).toBe(expected);
  });

  test.each(vectors.renderErrors)("rejects: $name", ({ template }) => {
    expect(() => renderPreviewHtml(template, "{}", "")).toThrow();
  });
});
