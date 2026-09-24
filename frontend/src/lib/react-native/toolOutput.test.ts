import * as fs from "fs";
import * as path from "path";
import { previewConfigJson, renderPreviewHtml, scriptTags } from "./previewHtml";
import {
  codeLanguageForPath,
  parseReactNativeScreenshot,
  reactNativePreviewProfile,
} from "./toolOutput";

const PROFILE = {
  platform: "android" as const,
  width: 412,
  height: 841,
  scale: 2.621359223300971,
  insets: { top: 0, right: 0, bottom: 0, left: 0 },
};

describe("parseReactNativeScreenshot", () => {
  test("reads the React Native summary", () => {
    const parsed = parseReactNativeScreenshot({
      status: "error",
      viewport: { platform: "ios", width: 390, height: 763, scale: 3 },
      runtime_errors: [
        { kind: "runtime", message: "Cannot read properties of undefined", fatal: true, line: 10 },
        { kind: "native_compat", message: "cursor is web-only", fatal: false, line: 4, rule: "web-style" },
        "not an error record",
      ],
      screenshots: [{ viewport: "ios", image_url: "data:image/png;base64,AAAA" }],
    });
    expect(parsed).toEqual({
      status: "error",
      platform: "ios",
      width: 390,
      height: 763,
      imageUrl: "data:image/png;base64,AAAA",
      errors: [
        { kind: "runtime", message: "Cannot read properties of undefined", fatal: true, line: 10, rule: undefined },
        { kind: "native_compat", message: "cursor is web-only", fatal: false, line: 4, rule: "web-style" },
      ],
    });
  });

  test("is null for other stacks' desktop and mobile summary", () => {
    expect(
      parseReactNativeScreenshot({
        screenshots: [
          { viewport: "desktop", image_url: "data:a" },
          { viewport: "mobile", image_url: "data:b" },
        ],
      })
    ).toBeNull();
    expect(parseReactNativeScreenshot(null)).toBeNull();
  });
});

describe("codeLanguageForPath", () => {
  test("highlights App.jsx as JavaScript and everything else as HTML", () => {
    expect(codeLanguageForPath("App.jsx")).toBe("javascript");
    expect(codeLanguageForPath("index.html")).toBe("html");
    expect(codeLanguageForPath(undefined)).toBe("html");
  });
});

describe("reactNativePreviewProfile", () => {
  const template = fs.readFileSync(
    path.resolve(__dirname, "../../../../rn-runtime/src/preview-template.html"),
    "utf8"
  );

  test("reads the profile from a real preview page", () => {
    const html = renderPreviewHtml(
      template,
      previewConfigJson("const s = '</script>';\nexport default () => null;", PROFILE),
      scriptTags("http://127.0.0.1:7001", "rn-runtime.js", "babel.js")
    );
    expect(reactNativePreviewProfile(html)).toEqual(PROFILE);
  });

  test("is null for other pages", () => {
    expect(reactNativePreviewProfile("<!doctype html><html><body>Hi</body></html>")).toBeNull();
    expect(
      reactNativePreviewProfile('<script id="rn-preview-config" type="application/json">{oops</script>')
    ).toBeNull();
  });
});
