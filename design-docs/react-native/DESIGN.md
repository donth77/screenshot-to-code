# React Native (Expo) output stack: design

Status: **Phases 0–3 complete. Phase 4 (export) is built, but its gate is only partly passed; it awaits review.** Phase 3 is in §12.1 and Phase 4 in §13.5.
Date: 2026-09-24. Branch: `react-native-stack`.
Companion documents: [`PLAN.md`](PLAN.md) (ordered tasks and estimates), `EVALS.md` (created in Phase 5).

Uncertainty labels used throughout:

- **Verified**: observed in this repo or on a real renderer during Phase 0, with evidence linked.
- **Assumed**: taken from documentation or public specs, not observed here.
- **Untested**: a plan that has not run yet.

> These documents live in `design-docs/react-native/` rather than the repo root:
> the root already has `plan.md`, and on macOS's case-insensitive filesystem a
> root `PLAN.md` would overwrite it.

---

## 1. Summary

| Topic | Decision | Basis |
| --- | --- | --- |
| Source format | The model writes a real React Native module, `App.jsx`. The preview HTML is derived from it, and the model never sees the wrapper. | Verified: the same `App.jsx` rendered unchanged in the web preview, the iOS Simulator and the Android emulator (§3, §10). |
| Preview runtime | A single esbuild IIFE containing React 19.2.3, ReactDOM, react-native-web 0.21.2, react-native-svg 15.15.4, react-native-safe-area-context 5.7.0, lucide-react-native 1.48.0 and an expo-status-bar shim. `@babel/standalone@7.25.6` is a separate pinned file. | Verified: gates RNW-1, RNW-4 and RNW-7 pass in headless Chromium (§4). |
| Runtime size | 1,789 KB raw / 662 KB gzip (development React build), plus Babel at 2,809 KB / 590 KB (KB = 1024 B). Budget: runtime ≤ 700 KB gzip. | Verified (§4.4). |
| Export SDK | **Expo SDK 57**, not SDK 56 as the brief proposed. Both pin identical web-side versions; SDK 57 is `latest` and what Expo Go runs today. | Verified: the npm registry, Expo's versions API and `npx expo install --check` (§2, §13). |
| Hosting | The backend serves `rn-runtime/dist` at `/rn-runtime/`. Playwright intercepts those URLs with `page.route`. The frontend iframe loads them by URL. The downloaded HTML inlines everything. | Verified for all three loading modes, the iframe case and offline `file://` (§6). |
| Fonts | Inter (iOS) and Roboto (Android) are bundled. RNW's hardcoded `System` font stack is rewritten at build time to a CSS variable. | Verified by CDP platform-font inspection (§8). Text is calibrated against the iOS Simulator and Android emulator (§8.3). |
| Device profile | Scale = pixel width ÷ logical width. The viewport is the content area only: the status bar and home indicator are cropped from the input. Capture is viewport-only. | Verified: renders are exactly logical size × scale; fractional scales land within 1 px (§7). |
| Shadows (RNW-8) | Always `boxShadow` (CSS string with `px` units). Never `shadow*` or `elevation`. | Verified on web, the iOS Simulator and the Android emulator (§9). |
| Safe area | The *host* provides `SafeAreaProvider`: the preview wrapper does, and the exported `index.js` does. `App.jsx` uses `SafeAreaView` only. | Verified: without a provider, native `SafeAreaView` applies no insets (§10). |
| System prompt | The existing `SYSTEM_PROMPT` stays byte-identical for current stacks. React Native gets its own composed prompt. | Deviation from the brief, explained in §11.2. |
| Snack | Snack supports up to SDK 55 (the npm SDK only to 54). Plan: URL prefill pinned to SDK 55, behind a flag, with documented limits. | Verified (§13.4). |

---

## 2. Re-verification of the brief's prior findings

| Claim in the brief | Status | Notes |
| --- | --- | --- |
| Stack registered in `frontend/src/lib/stacks.ts` and `backend/prompts/prompt_types.py`; the comment in `stacks.ts` wrongly says `prompts/types.py` | Verified | Also shown in `StackLabel.tsx` (logo map) and listed by `/models` in `routes/evals.py` via `Stack.__args__`. |
| `system_prompt.py` has a stack-specific section per stack | Verified, with a nuance | All sections live in **one static string** sent to every stack. The stack is named only in the user turn (`Selected stack: {stack}.`, from `prompts/policies.py`). No per-stack prompt assembly exists. |
| The React stack uses React 18 browser builds and `@babel/standalone@7.25.6` | Verified | Specifically React 18.0.0 **UMD development** builds from jsdelivr, plus the Tailwind CDN. |
| General instructions: Font Awesome except for Ionic. Targeted edits use `outerHTML`. | Verified | |
| `babel_cdn.py` pins 7.25.6 | Verified | Mirrored in `frontend/src/lib/babelCdn.ts`. Both normalise any `@babel/standalone` URL. |
| `screenshot_preview.py`: `("desktop", "mobile")`, `full_page=True`, multimodal parts | Verified | The summary also inlines data URLs for the UI. |
| `preview_screenshot/`: `base.py`, `playwright_backend.py`, `registry.py` | Verified | The backend is pluggable (`set_screenshot_backend`). The Playwright backend uses `page.set_content(..., wait_until="networkidle")`, so the base URL is `about:blank`, with `device_scale_factor=1` and a new page per capture. |
| `PreviewComponent.tsx` iframe, `device: "mobile" \| "desktop"`, width constants | Verified | `srcdoc`, **no `sandbox` attribute, no CSP**, same-origin (select-and-edit reads `contentWindow.document`). Variant thumbnails use `sandbox="allow-scripts allow-same-origin"`. |
| Agent tools listed in the prompt | Verified | Also `save_assets`. The engine allows 30 tool turns (`agent-tool-calling-flow.md` still says 20). |
| ai-app-cloner dependency set (SDK 56, React 19.2.3, RN 0.85.3, RNW ~0.21.0, svg 15.15.4, safe-area ~5.7.0, lucide ^1.22.0) | Verified, but **superseded** | Expo SDK 57.0.0 shipped 2026-06-30 (57.0.24 today) with the **same** React, RNW, svg and safe-area pins; only RN differs (0.86.3). SDK 58 is in RC (RN 0.88.0-rc.1, React 19.3.0). lucide-react-native is at 1.48.0. |
| ai-app-cloner verifies at "about 390px" | Partly | `SKILL.md` says ~390 px, but `e2e/verify.mjs` uses **402 × 874 at `deviceScaleFactor: 2`**. |
| No browser builds for react-native-web or React 19 | Consistent | We bundle both. |
| RNW as a global with React `external` leaves `require("react")` | Not re-tested | Avoided by design: React is bundled in. |
| twrnc needed `--legacy-peer-deps` | Avoided | Installing `"react-native": "npm:react-native-web@0.21.2"` satisfies every `react-native` peer with no flags. The build then aliases `react-native` → `react-native-web` so one copy is bundled, and asserts it (§4.3). |
| RNW bundle about 260 KB without React | Consistent | RNW contributes 241 KB (246,689 B) to the output. |
| jsdom-only results | Superseded | Everything below ran in real Chromium 149 through the repo's Playwright backend. |
| `snack-sdk` 6.6.2 on npm | Verified | But it only knows SDKs 50–54 (§13.4). |
| **New:** react-native-svg's web build imports `@react-native/assets-registry/registry` | Verified | Pinned `@react-native/assets-registry@0.86.3` (it matches RN 0.86.3). |

### Baseline (before any product change)

- Backend `pytest`: **276 passed**.
- `pyright`: **0 errors, 36 warnings**.
- Frontend `jest`: **42 passed, 6 skipped**.
- Frontend `pnpm lint`: **19 errors, 6 warnings**, all pre-existing (as `AGENTS.md` notes).
- Setup: Poetry was not installed; installed with `pipx install poetry` (2.5.1). No API keys are configured on this machine.

### Existing React stack, end to end

There are no LLM keys, so a scripted `ProviderSession` stood in for the model. The real prompt pipeline, `AgentEngine`, tool runtime, Playwright `screenshot_preview` and `/api/export` all ran.

Result (Verified): 7 streamed `setCode` events; desktop 1280 × 832 and mobile 342 × 684 screenshots rendered the React page (with the unversioned Babel URL normalised to 7.25.6); the export zip contained `index.html` with Babel pinned. The **LLM leg itself is untested** without keys.

---

## 3. Source-format decision: `App.jsx`

### 3.1 Audit: everywhere generated code is rendered, stored or exported

#### Backend: `index.html` path literals (default-path sites)

| Location | What it assumes |
| --- | --- |
| `agent/state.py:11, 48, 69` | `AgentFileState.path = "index.html"` and seed defaults |
| `agent/engine.py:84, 192` | initial file path; streamed `toolStart` path |
| `agent/tools/runtime.py:102, 236` | `create_file` / `edit_file` default path |
| `agent/tools/definitions.py:14-18, 196-211, 269-292` | tool descriptions say "HTML" and "index.html"; `screenshot_preview` says "desktop and mobile" |
| `prompts/system_prompt.py:14-19` | "The main file is a single HTML file… `index.html`" |
| `prompts/message_builder.py:10` | history wrapped as `<file path="index.html">` |
| `prompts/update/from_file_snapshot.py:19` | default path |
| `routes/generate_code.py:355` | `fileState.path` default |
| `routes/export.py:445` | zip entry `index.html` |

#### Backend: HTML-shaped consumers

| Location | What it does |
| --- | --- |
| `codegen/utils.extract_html_content` | Used by `create_file`, history seeding and the finalize fallback. Non-HTML passes through unchanged plus a log line, so JSX survives today *by accident*. |
| `preview_screenshot` | Renders `file_state.content` as a page; the Babel normaliser runs first. |
| `routes/export.py` | Parses the code with BeautifulSoup and collects `<img>`, `srcset` and CSS URLs. |
| `evals/runner.py` | Writes `<name>_<n>.html`; `routes/evals.py` lists `.html` outputs. |
| `fs_logging/agent_runs.py` | Snapshots `final.html` and `final_selfcontained.html`. |
| `prompts/create/image.py` | Says "Generate code for a *web page*…"; the multi-screenshot guidance is about web pages. |

#### Frontend: path literals and HTML assumptions

| Location | What it assumes |
| --- | --- |
| `lib/prompt-history.ts:157` | `fileState.path: "index.html"` |
| `components/preview/PreviewComponent.tsx` | `iframe.srcdoc = normalizeBabelCdn(code)`; select-and-edit reads `outerHTML` |
| `components/preview/PreviewPane.tsx` | desktop/mobile tabs; `openInNewTab` (Blob plus `<base>`); `extractHtml` for video streaming; download |
| `components/preview/download.ts` | `/api/export`; fallback downloads `index.html` |
| `components/preview/CodeMirror.tsx` | `@codemirror/lang-html` |
| `components/preview/CodeTab.tsx` | CodePen export |
| `components/variants/Variants.tsx` | thumbnails use `srcdoc = code` (raw, not normalised) |
| `App.tsx:704`, `select-and-edit/utils.ts` | selected element is `outerHTML` plus a DOM path |
| `components/agent/AgentActivity.tsx` | `create_file` preview highlighted as `html`; screenshot grid hardcodes `["desktop", "mobile"]` |
| `components/evals/*`, `agent-run-tool-preview.tsx` | render outputs as `srcDoc`; hardcode desktop and mobile |
| `unified-input/tabs/ImportTab.tsx` | accepts `.html` |
| `lib/takeScreenshot.ts` | `html2canvas` of `#preview-desktop` (appears unused) |

Project state is in memory (zustand); only settings persist, in `localStorage`. No stored artifact assumes a filename.

### 3.2 Why `App.jsx` intercepts cleanly (Verified)

1. **The agent is strictly single-file.** The path travels in one place (`AgentFileState.path`), and `setCode` carries content only. A stack-aware *main path* passed into `AgentEngine` / `AgentToolRuntime` covers every backend literal above. All other stacks keep `"index.html"`.
2. **The HTML consumers are few and identifiable.** Rendering (iframe, thumbnails, Playwright), export and evals each gain an RN branch that wraps `App.jsx` with the template. None needs `App.jsx` to *be* HTML.
3. **The same file runs everywhere, unchanged.** The fixture `App.jsx` rendered in the web preview, bundled with `npx expo export --platform ios --platform android`, and ran in Expo Go on the iOS Simulator and the Android emulator. The only change was an entry-file `SafeAreaProvider` (§10). This is the core argument against the `index.html` fallback, which would need a lossy HTML → project extraction at export time and would show the model wrapper boilerplate it could damage.

The fallback (inline RN in `index.html`) is **rejected**.

---

## 4. Preview runtime

### 4.1 Composition (Verified in the Phase 0 spike; now the `rn-runtime/` package)

| Package | Version | Why this version |
| --- | --- | --- |
| react / react-dom | 19.2.3 | = SDK 57 `bundledNativeModules.json` |
| react-native-web | 0.21.2 | SDK 57 pins `~0.21.0`; resolves to 0.21.2 |
| react-native-svg | 15.15.4 | = SDK 57 |
| react-native-safe-area-context | 5.7.0 | SDK 57 pins `~5.7.0`; 5.7.0 is the only 5.7.x |
| lucide-react-native | 1.48.0 | latest; peers `react-native-svg ^12–15` |
| @react-native/assets-registry | 0.86.3 | needed by svg's web asset resolver; = SDK 57's RN |
| @babel/standalone | 7.25.6 | same pin as `babel_cdn.py`; classic JSX runtime |
| @fontsource/inter, @fontsource/roboto | 5.3.0 | OFL 1.1; Latin, weights 300–800 |
| esbuild | 0.28.2 | build only |

Build settings:

- **Bundle format:** IIFE targeting `chrome115`/`safari16`/`firefox115`.
- **Module resolution:** `resolveExtensions` prefers `.web.*` files, `mainFields` is `browser, module, main` (which avoids svg's `src/*.ts` "react-native" entry), and `alias: {'react-native': 'react-native-web'}`.
- **Globals:** `process.env.NODE_ENV`, `__DEV__` and `global` are defined.

### 4.2 What the runtime exposes (Verified)

- `window.React` (the real `module.exports`) and `window.ReactDOM`.
- `window.__RN_MODULES__`, frozen, allowlist only: `react`, `react-native`, `react-native-safe-area-context`, `react-native-svg`, `lucide-react-native`, `expo-status-bar`. `__RN_MODULES__.react === window.React` is gated (RNW-4).
- `window.__RN_RUNTIME__`: versions and build mode, used for RNW-5.
- `window.__RN_PREVIEW__.boot()` and `.transform()`. Boot logic lives in the hashed, tested runtime rather than as inline template script.

Module rules:

- **ESM namespaces are flagged `__esModule: true`.** Without this, Babel's interop makes `import Svg, { Circle } from 'react-native-svg'` yield the *namespace* as `Svg`. Found while designing the spike; the fixture exercises it.
- **`react-native` returns the namespace for `default`,** matching Metro's native semantics. A Proxy reports unknown capitalised names as `unknown_export`, for example `PlatformColor`, which RNW lacks.
- **`lucide-react-native` is a Proxy.** An unknown capitalised name records `unknown_icon`, with the five closest real names, and returns a cached dashed placeholder component (`testID="unknown-icon-<Name>"`), so the render doesn't crash (Verified). Named imports are live bindings, so the trap fires at render time.
- **Legacy icon names still resolve.** All 63 common names checked resolve in 1.48.0, including `Home`, `Edit`, `MoreHorizontal` and `AlertCircle`, since lucide keeps aliases (6,344 export names).
- **`expo-status-bar` is a shim** that renders nothing on web (as does the real web implementation). It records `{style, hidden, …}` in `window.__RN_PREVIEW_META__.statusBar`.

### 4.3 Build-time assertions (Verified; the build fails otherwise)

- The system-font rewrite (§8) matched RNW's `SYSTEM_FONT_STACK` exactly once.
- The safe-area provider substitution (§5.4) matched.
- There is exactly one bundled copy each of `react`, `react-dom`, `react-native-web` and `scheduler`, and **no** file from the `react-native` alias package (checked through esbuild's metafile).
- `</script` never appears raw in the output; esbuild already emits `<\/script`.

### 4.4 Size (Verified, `measure-sizes.mjs`; KB = 1024 bytes)

| Build | Raw | gzip -9 | brotli |
| --- | --- | --- | --- |
| @babel/standalone 7.25.6 (separate file) | 2809 KB | 590 KB | 388 KB |
| **Runtime, development React (chosen)** | **1789 KB** | **662 KB** | **584 KB** |
| Runtime, dev, no lucide | 1057 KB | 486 KB | 447 KB |
| Runtime, dev, no fonts | 1426 KB | 389 KB | 313 KB |
| Runtime, production React | 1589 KB | 603 KB | 538 KB |
| Runtime, production, no lucide, no fonts | 496 KB | 154 KB | 131 KB |

Bytes contributed to the development runtime: lucide 729 KB, base64 fonts 363 KB, react-dom (dev) 353 KB, RNW 241 KB, svg 38 KB, react 20 KB.

**Choice: the development React build.** The agent reads React's error messages and component stacks, and RNW's deprecation warnings. A production build would replace them with minified error codes, and would save only 58 KB gzip.

**Budget:** runtime ≤ 1,900 KB raw / **700 KB gzip**; Babel stays fixed. First load is about 1,250 KB gzip; afterwards, content-hashed `immutable` files are served from cache. The Phase 1 build fails over budget.

Levers if needed:

- Serve fonts as separate woff2 files: saves about 270 KB gzip from the JS.
- A custom Babel build (core + preset-react + commonjs): **untested**.

---

## 5. Source format, template and wrapper

### 5.1 One template (Verified)

`preview-template.html` has two placeholders:

| Placeholder | Replaced with |
| --- | --- |
| `__RN_PREVIEW_CONFIG__`, inside `<script id="rn-preview-config" type="application/json">` | JSON `{source, profile}`, with `<` escaped as `<` so it can never close the element |
| `<!--RN_PREVIEW_SCRIPTS-->` | either two `<script src>` tags (Babel, runtime) or both files inlined |

- **Substitution is single-pass** (one regex with a callback), so substituted content is never re-scanned.
- **Inlined JS is escaped** by rewriting `<!--`, `<script` and `</script` as `\x3C…`. That is valid in strings, template literals and regex literals (the runtime contains `/<!--/` from svg's CSS parser, which could otherwise flip the HTML tokenizer into its double-escaped script state).

Python and TypeScript implementations will share one set of test vectors (Phase 1).

*Deviation from the brief:* a scripts placeholder replaces a bare "runtime URL" placeholder, so one template serves URL mode and inline mode alike.

### 5.2 Transform and execute (Verified)

```js
Babel.transform(source, {
  filename: 'App.jsx', sourceType: 'module', retainLines: true,
  presets: [['react', { runtime: 'classic' }]],
  plugins: ['transform-modules-commonjs'],
});
new Function('require', 'module', 'exports', 'React', code + '\n//# sourceURL=App.jsx')
```

- The output uses classic `React.createElement` (41 calls in the fixture) and never `react/jsx-runtime`.
- `React` is injected as a parameter, so `App.jsx` without `import React` works, as it does on native with Expo's automatic runtime (fixture `no-react-import`: `ok`).
- `require` resolves only through `__RN_MODULES__`. An unknown specifier throws `Cannot import "<spec>". Allowed modules: …` with the source line (fixture `broken-import`: `import`, line 3).
- `retainLines` keeps transformed lines aligned with the source; stack lines minus the 2-line `Function` header give **source lines**. Columns refer to transformed code, so runtime errors report the line only. Transform errors report exact line **and** column (1-based) plus Babel's code frame.

### 5.3 Mount (Verified)

```
AppRegistry.runApplication('App')
  -> PreviewRoot
       SafeAreaProvider initialMetrics = {profile insets, viewport frame}
         ErrorBoundary -> <App/>
         ReadySignal
```

The error boundary renders a red panel built from RN primitives, so errors appear in screenshots ([`evidence/broken-syntax.png`](evidence/broken-syntax.png)). Fatal transform, import and module errors render the same panel through a separate app key.

### 5.4 Safe-area provider on web (Verified)

react-native-safe-area-context's web `NativeSafeAreaProvider` measures CSS `env(safe-area-inset-*)` after mount and **overwrites** `initialMetrics` (always 0 in Chromium). The build swaps in a shim that reports the device profile's insets and the viewport frame.

The gate renders a full-device profile (insets 59/34) and checks that `SafeAreaView` padding is exactly `59px`/`34px`. In the default content-only mode the insets are 0.

### 5.5 Error, readiness and status contract (Verified; Phase 1 hardens it)

`window.__RN_PREVIEW_ERRORS__` entries have the shape `{kind, message, fatal?, line?, column?, name?, componentStack?, frame?}`:

| `kind` | Source | Fatal |
| --- | --- | --- |
| `transform` | Babel syntax error: line, column, code frame | yes |
| `import` | unknown module specifier | yes |
| `module` | throw at module top level | yes |
| `no_default_export` | `App.jsx` lacks `export default` | yes |
| `runtime` | error boundary: message, source line, component stack such as `Price (App.jsx:4) < App` | yes |
| `unknown_icon` | lucide Proxy, with closest names | no |
| `unknown_export` | react-native Proxy | no |
| `image_load` | the `window.Image` wrapper saw an error | no |
| `console_error`, `invalid_hook_call`, `uncaught`, `unhandled_rejection`, `runtime_load` | inline template hook, installed before any script loads | varies |

Behaviour of the error log:

- Entries are deduplicated.
- React 19 logs every boundary-caught error again through `console.error("%o\n\n%s…")`; that duplicate is removed when the runtime error is recorded.
- The hook applies printf formatting, and each report is also logged as `[rn-preview] <kind>: …` for Playwright.

Readiness:

- `__RN_PREVIEW_READY__` becomes true after the first commit, then `document.fonts.ready`, then images settled, then two animation frames.
- "Images settled" means no pending loads through a `window.Image` wrapper (RNW's `ImageLoader` uses `new window.Image()`) and every `document.images` entry complete, capped at 5 s.
- `__RN_PREVIEW_STATUS__` is `ok`, `degraded` (non-fatal problems only) or `error`.

Measured on an M2 Max: ready ≈ **0.5 s** after `set_content` with the runtime by URL or route, ≈ **0.7 s** inlined.

Planned for Phase 1 (**Untested**):

1. A **native-compatibility lint**, run as a Babel visitor in the same transform, reporting `native_compat`:
   - **Fatal:** lowercase JSX host tags (`<div>` crashes on native) and `onClick`.
   - **Warning:** `Platform.OS` and `Platform.select`.
   - **Warning:** web-only style keys (`cursor`, `transition*`, `display: 'grid'`, `position: 'fixed' | 'sticky'`).
   - **Warning:** CSS shorthand strings (`border: '1px solid'`, `padding: '8px 16px'`), unit strings in numeric styles (`fontSize: '14px'`; RNW accepts them, native does not), `shadow*` and `elevation`, and `className`.

   Metro bundling (RNW-6) cannot catch these; the lint is the main static guard.
2. **Streaming mode.** During `create_file` streaming a partial file is a syntax error. The iframe keeps the last good render and shows a quiet "Writing App.jsx…" badge instead of the red panel.
3. **Hot-swap.** The template accepts `postMessage({type: 'rn-preview:update', source, profile})` and re-transforms and remounts without re-parsing about 4,600 KB of scripts. This matters because the frontend runs up to four variant iframes plus the main preview (§12).

---

## 6. Hosting

| Consumer | How it loads the runtime | Evidence |
| --- | --- | --- |
| Backend Playwright (`screenshot_preview`, evals) | Template scripts point at `…/rn-runtime/<hashed file>`. `page.route` fulfils those URLs from `rn-runtime/dist` on disk: no dependency on the backend's public host, the Vite proxy or the port. | Verified, "route" mode: identical results to URL mode, ready in 0.54 s. |
| Frontend iframe (`srcdoc`, same origin) | `${HTTP_BACKEND_URL}/rn-runtime/<file>`. The default same-origin setup goes through the Vite proxy (add `/rn-runtime`); cross-origin also works for classic scripts. | Verified: iframe unsandboxed with absolute URLs, and sandboxed `allow-scripts allow-same-origin` with **relative** URLs. Both `ok`; the parent reached 25 `data-testid` nodes (select-and-edit). The real Vite dev server is RNW-2 in Phase 3. |
| Downloaded preview HTML | Babel and the runtime inlined; assets as data URIs | Verified: the 4,611 KB file rendered from `file://` in an **offline** context with zero network attempts. The product download is RNW-3. |
| The unmodified existing tool path | `capture_preview_screenshot(html, "mobile")` also renders the template (non-blank) | Verified. Useful as a fallback, but it cannot wait on readiness or return errors. |

Backend serving:

- Mount `rn-runtime/dist` at `/rn-runtime`, the same way `uploaded_assets` mounts `/local-assets`.
- Hashed files get `Cache-Control: public, max-age=31536000, immutable`. `manifest.json` and `preview-template.html` get `no-cache`.
- The frontend fetches both once and caches them in memory.
- **As built (Phase 1).** `backend/react_native/serving.py`. Without a build the URLs 404, not 500. The Vite dev server proxies `/rn-runtime` like `/api`.
  - `frontend/src/lib/react-native/previewRuntime.ts` loads the manifest and template once and builds `srcdoc` documents.
  - `backend/tests/test_rn_vite_preview.py` renders the full fixture through the real Vite dev server in an iframe (RNW-2, library level). The immutable header survives the proxy.
  - Gotcha: `vite-plugin-html`'s history fallback answers every `Accept: text/html` navigation with the app's `index.html`, so a dev page other than the app must be requested without that header.

Artifacts:

- **Recommendation:** don't commit `dist/` (4.7 MB of minified JS per change). Build with Node (already required for the frontend) and add a Node stage to `backend/Dockerfile`.
- **As built.** `backend/Dockerfile` builds `rn-runtime` in a `node:22.22.1-bookworm-slim` stage (pnpm 10.32.1, frozen lockfile), copying only the build's inputs. `docker-compose.yml` passes `rn-runtime/` as the named build context `rn-runtime`, and the image sets `RN_RUNTIME_DIST`.
  - The stage's steps, replayed in a clean directory, give a byte-identical bundle.
  - **The `rn-runtime` stage builds (Verified, Phase 3, Linux, Docker 29.3.1):** `docker build --target rn-runtime-build` produced a `dist/` byte-identical to the host build (same `rn-runtime.20452ffe797c.js`).
  - **The full image is untested.** Its build got through `poetry install` and then stopped at `playwright install --with-deps chromium`: the sandbox's network policy answers `deb.debian.org` and Playwright's CDN with 403.
    - Docker Hub rate-limited anonymous pulls (429), so the two base images came from `mirror.gcr.io` under the same tags.
    - The sandbox's TLS-intercepting proxy CA was added to local copies of those base images.
    - The committed Dockerfile is unchanged.
- If `dist/` is missing, `/api/capabilities` reports `react_native_preview: false` and the stack is disabled with a clear message.

Pluggable screenshot backends:

- `ScreenshotBackend` gains an **optional** `capture_react_native(html, profile, routes)` returning `(png, runtime_errors, meta)`.
- A deployment whose backend lacks it (for example an external rendering API on the `hosted` branch) doesn't offer `screenshot_preview` for this stack. The existing HTML path is untouched.

---

## 7. Device profiles and screenshot alignment

### 7.1 Derivation (Verified by the gates)

```
scale          = image_px_width / logical_width
content_height = round(image_px_height / scale) - inset_top - inset_bottom   (logical)
viewport       = { width: logical_width, height: content_height }, deviceScaleFactor = scale
input crop     = remove inset_top * scale px from the top and inset_bottom * scale px from the bottom
```

- iPhone 15-class content area (390 × 751 at 3): screenshot exactly **1170 × 2253**.
- Pixel 8 (412 wide, scale 1080 / 412 = 2.6214): **1080 × 2275**, against 2275.3 expected. Scale is derived from the pixel width, so the width is exact and the height rounds to within 1 px. The comparison pipeline pads or crops by at most 2 px.

Capture is **viewport-only**. `ScrollView`/`FlatList` content scrolls inside an `overflow: auto` element, so `full_page` would not capture it. Verified: the fixture's `FlatList` is cut at the viewport edge. For stitched long screenshots, the viewport height is the input's logical content height, using the same formula.

### 7.2 Known-device table (single source: `rn-runtime/device-profiles.json`, served to the frontend)

| Pixel size (portrait) | Devices | Logical | Scale | Insets top/bottom (pt) | Status |
| --- | --- | --- | --- | --- | --- |
| 1170 × 2532 | iPhone 12, 12 Pro, 13, 13 Pro, 14, 17e | 390 × 844 | 3 | 47 / 34 | Size verified on the iPhone 17e simulator; insets assumed |
| 1179 × 2556 | iPhone 14 Pro, 15, 15 Pro, 16 | 393 × 852 | 3 | 59 / 34 | Assumed |
| 1206 × 2622 | iPhone 16 Pro, 17, 17 Pro | 402 × 874 | 3 | 62 / 34 | Assumed |
| 1284 × 2778 | iPhone 12/13 Pro Max, 14 Plus | 428 × 926 | 3 | 47 / 34 | Assumed |
| 1290 × 2796 | iPhone 14 Pro Max, 15 Plus, 15 Pro Max, 16 Plus | 430 × 932 | 3 | 59 / 34 | Assumed |
| 1320 × 2868 | iPhone 16 Pro Max, 17 Pro Max | 440 × 956 | 3 | 62 / 34 | Assumed |
| 1125 × 2436 | iPhone X, XS, 11 Pro | 375 × 812 | 3 | 44 / 34 | Assumed |
| 1080 × 2340 | iPhone 12 mini, 13 mini | 375 × 812 | 2.88 | 50 / 34 | Assumed |
| 828 × 1792 | iPhone XR, 11 | 414 × 896 | 2 | 48 / 34 | Assumed |
| 750 × 1334 | iPhone SE (2nd/3rd gen), 6–8 | 375 × 667 | 2 | 20 / 0 | Assumed |
| 1080 × 2400 | Pixel 8 and many 20:9 Androids | 412 × 915 | 2.62 | 50.3 / 24 (dp) | Verified on the emulator (`dumpsys window`): display cutout 132 px, navigation bar 63 px |
| 1344 × 2992 | Pixel 8 Pro | 448 × 997 | 3 | Untested | Size verified (emulator) |

Insets are **safe-area insets**, the values `SafeAreaView` applies, so they include display cutouts. On the Pixel 8 the cutout (132 px = 50.3 dp) is taller than the status bar (63 px = 24 dp), so the top inset is the cutout's. The earlier estimate of 52.6 dp came from a render (avatar offset minus header padding) and is superseded. Crops follow the same insets.

Fallbacks:

- An unknown iOS device uses logical width 390; an unknown Android device uses 412 dp.
- The platform guess: exact table hits first, then aspect and pixel-density heuristics.
- The user can override the platform, the device and both insets with the crop overlay (§12). Android status-bar heights vary widely, so the overlay matters most there.

### 7.3 Status bar handling

The model receives the **cropped** image and cannot draw a fake clock or battery. The backend infers the status bar style deterministically from the cropped-off top strip:

1. Take the strip's dominant background colour.
2. Find the foreground glyph pixels.
3. Light glyphs mean `style="light"`; dark glyphs mean `style="dark"`.

The result is passed to the model as a fact, and the runtime's `StatusBar` shim reports what the model actually chose. **Untested; Phase 2.**

Code still wraps the screen in `SafeAreaView`. It applies 0 insets in the preview and real insets on devices (§10).

---

## 8. Fonts

### 8.1 Mechanism (Verified)

In RNW 0.21.2, `Text` and `TextInput` default to `font: '14px System'`. `createReactDOMStyle.js` replaces `System` with the hardcoded stack `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif`, and nested `Text` uses `font: inherit`.

- **The rewrite.** An esbuild `onLoad` plugin rewrites that one constant to `var(--rn-preview-system-font, <original stack>)`. User fonts other than `System` are untouched, and nested-text inheritance is preserved.
- **Where the font comes from.** The runtime injects `@font-face` rules (data URLs, `font-display: block`) for the profile's family and sets the variable: "RNP Inter" for iOS, "RNP Roboto" for Android.
- **Verification.** `CSS.getPlatformFontsForNode` over CDP reports `familyName: "Inter"` or `"Roboto"` with `isCustomFont: true` for the fixture title. This is the *rasterised* font, not just the computed style, so the render doesn't depend on fonts installed on the host.
- **Weights and fallback.** Weights 300–800 are bundled, Latin subset only. Glyphs outside it fall back to host fonts, which in the Docker image are fixed by the image itself.
  - **What's already installed.** `playwright install --with-deps chromium` installs, per Playwright 1.61's Debian 12 dependency list: CJK (IPA Gothic, WenQuanYi Zen Hei), Noto Color Emoji, Thai (TLWG Loma), FreeFont, Liberation and Unifont.
  - **Noto is deferred.** Installing `fonts-noto-*` system-wide, as planned, could change what `sans-serif` resolves to in the existing stacks' screenshots, and checking that needs a Docker run.
  - **Status.** Untested in the image.

### 8.2 Web vs native text metrics before calibration (Verified; measured from the same fixture)

| Comparison | 22 pt bold title width | 15 pt subtitle width | Title ink height |
| --- | --- | --- | --- |
| Preview Inter vs **iOS SF Pro** (Simulator) | **1.057** (204.7 vs 193.7 pt) | **1.036** | 21.7 vs 20.7 pt |
| Preview Roboto vs **Android Roboto** (emulator) | 0.997 | 0.987 | 21.4 vs 21.0 pt |

Also observed: native Android list rows are taller. The row pitch is 72.5 dp natively against 67.1 dp in the preview, so each two-line row gains about 5.4 dp (≈ 2.7 dp per line of text) and the offset accumulates down the list. This matches RN Android's default `includeFontPadding`, which pads each `Text` to the font's top and bottom metrics.

### 8.3 Calibration (Verified on the iOS 26.4 Simulator and an Android 16 emulator; Phase 1)

The `Text` that generated code imports is a wrapper (`rn-runtime/src/text-metrics.js`) that applies each platform's text rules on top of react-native-web. `rn-runtime/calibration/README.md` has the rules, the measurements behind them and how to re-measure. What changed from the plan above:

- **`size-adjust` was the wrong fix.** The iOS width gap depends on size and weight. SF Pro tracks size-dependently: at 400 weight Inter needs +0.005 em at 11 pt and −0.050 em at 34 pt. A single scale factor can't close that, so the wrapper applies fitted tracking (`letterSpacing`) per size and weight. An explicit `letterSpacing` adds on top, as `NSKern` does natively. `letterSpacing: 0` also turns pair kerning off, since CoreText treats kern 0 as "no kerning".
- **The Android gap isn't about glyph widths.** React Native renders at `ceil(size × density)` pixels. Its lines are spaced by Roboto's rounded hhea ascent + descent, and `includeFontPadding` pads only the first and last line of a `Text`, out to the font's bounding box. The §8.2 row-pitch gap was that padding. The uniform `ascent-override` / `descent-override` proposed above would have been wrong for any `Text` longer than one line.
- **Only iOS tracking is fitted.** Every other constant comes from the fonts: `UIFont` on the Simulator for SF Pro, and the bundled Roboto files. `fit.py` checks the line rules against all 97 native samples per platform (single lines, paragraphs, explicit `lineHeight`, padding off, default size) and fails on any mismatch.

Results, as median / max over the samples the fit never saw:

| | Width, before | Width, after | Line height, before | Line height, after |
| --- | --- | --- | --- | --- |
| iOS (held-out sizes, weights, spacing, paragraphs) | 2–6% / 12% | 0.4–1.0% / 1.8% | ≤ 0.67 / 1.33 pt | ≤ 0.30 pt |
| Android (same) | 0.1–1.1% / 4.0% | 0.1–0.5% / 1.3% | 0.3–3.6 / 6.5 dp | ≤ 0.03 dp |

That meets the targets of median width ≤ 1.5% and line height ≤ 0.5 pt. `test_text_lays_out_like_the_device` holds them.

**Untested:**

- Linux Chromium, where the Docker backend renders: **measured in Phase 3.**
  - Chromium 141 on Linux fails the width limits on both platforms (iOS grid max 3.46%, Android grid median 1.28% and max 6.06%); every height passes.
  - With `--font-render-hinting=none` every category passes, and the iOS figures equal the macOS ones. The cause is font hinting, not the Chromium version.
  - The image's own Chromium 149 is untested.
  - Whether the backend should pass that flag is an open question (§17). Figures: `rn-runtime/calibration/README.md` and `evidence/phase3-gate.json`.
- Real phones and OEM fonts (Samsung's One UI doesn't use Roboto).
- Font scaling other than 100%.
- Densities other than 3× and 2.625.
- Scripts outside Latin, and emoji.

**Prompt guidance (Phase 2).** The system prompt says the preview font is a metric-matched stand-in, and that font size should be matched by glyph height, not by text width.

---

## 9. Shadows (RNW-8)

The fixture has two identical cards, one with `boxShadow: '0px 4px 12px rgba(17, 24, 39, 0.12)'` and one with the equivalent `shadowColor/Offset/Opacity/Radius` plus `elevation: 4`. See [`evidence/shadows-web-vs-native.png`](evidence/shadows-web-vs-native.png).

| Renderer | `boxShadow` | `shadow*` | `elevation` |
| --- | --- | --- | --- |
| react-native-web 0.21.2 (Chromium) | CSS `box-shadow` | converted to the *same* CSS `box-shadow`, with a dev warning: `"shadow*" style props are deprecated. Use "boxShadow".` | ignored (`ignoredProps`) |
| iOS, RN 0.86.3 (Expo Go 57, Simulator) | renders, and matches web | renders visibly more diffuse (CALayer `shadowRadius` semantics) | ignored |
| Android, RN 0.86.3 (Expo Go 57, emulator) | renders, and matches web | ignored | renders a crisper Material shadow |

No native warnings were logged on either platform.

**Convention:** `boxShadow` as a CSS-style string with explicit `px` units (e.g. `'0px 4px 12px rgba(0, 0, 0, 0.12)'`). It is the only form that renders, with the same semantics, on all three.

- The array form is also accepted by RNW (`createBoxShadowArrayValue`) and by RN.
- `boxShadow` requires the New Architecture (the default in SDK 57 and in Expo Go). Android outset shadows need API 28+ (**Assumed**, from RN docs).
- The Phase 1 lint flags `shadow*` and `elevation`.

The brief named React Native 0.85; SDK 57 ships 0.86.3, which is what was tested.

---

## 10. Native parity findings (from running the fixture natively)

Evidence: [`evidence/fixture-web-vs-native.png`](evidence/fixture-web-vs-native.png).

- **The same file runs on all three.** The only probe change was the avatar URL, swapped for a data URI because a phone can't reach the local asset server. It bundled natively (`npx expo export --platform ios --platform android`: 2,571 modules, Hermes bytecode 3.7 MB each, about 22 s) and ran in Expo Go 57 on the iPhone 17e Simulator (iOS 26.4) and a Pixel 8 AVD (API 36).
- **A provider is required on native.** Without `SafeAreaProvider`, native `SafeAreaView` (Fabric `RNCSafeAreaView`) applies **no insets**, and the header rendered under the status bar. With the provider in `index.js` it is correct. The web preview wraps `App` in a provider, so the export must too, or the preview lies. Decision: the host owns the provider, and the system prompt forbids adding one in `App.jsx`.
- **Data-URI images render on iOS and Android.** This supports the export's asset strategy (§13.2).
- **Layout parity is otherwise close.** Spacing, radii, lucide icons, SVG and list layout match; the text-metric gaps are in §8.2.
- **One unexplained artifact.** After a relaunch on iOS, the horizontal chip `ScrollView` appeared pre-scrolled. It is noted but not investigated.

Tooling learned for Phase 4 and 6:

- Expo Go's dev-menu onboarding sheet can be suppressed on iOS with `defaults write host.exp.Exponent EXDevMenuIsOnboardingFinished -bool YES`.
- On Android, it can be dismissed with `adb shell input tap`.
- `adb exec-out screencap -p` and `xcrun simctl io <device> screenshot` capture natively.

---

## 11. Backend design (Phase 2)

Every change is gated on `stack == "react_native"`. Existing stacks keep identical prompts, paths and behaviour; tests assert byte-identity.

### 11.1 Stack registration

- Add `react_native` to `Stack` in `prompt_types.py` and to the frontend `Stack` enum: "React Native (Expo)", logos React and Expo (`SiReact`, `SiExpo`), `inBeta: true`.
- Fix the stale comment in `stacks.ts`.

### 11.2 Prompts (deviation from the brief)

The brief asks to add React Native to `SYSTEM_PROMPT` and to add an RN exception to "General instructions for all stacks". Because `SYSTEM_PROMPT` is **one static string sent to every stack** (§2), that would change every existing stack's prompt.

Instead, a new `get_system_prompt(stack)` does this:

- **Existing stacks:** returns today's `SYSTEM_PROMPT` object unchanged.
- **`react_native`:** returns a prompt composed from:
  - the *same* "Tone and style" and "Image manipulation" text (extracted into shared constants, byte-identical);
  - RN tooling instructions (`App.jsx`, `screenshot_preview` returns `runtime_errors`);
  - the RN stack section (rules below);
  - RN general instructions (no Font Awesome; lucide only);
  - RN targeted element edits (`testID` locator).

Every builder switches from `system_prompt.SYSTEM_PROMPT` to `get_system_prompt(stack)`: the three create builders and the two update builders.

The RN user turn in `create/image.py` says "a React Native screen", not "a web page". It states:

- the device profile: platform, logical size, and "1 pt = N px in this screenshot";
- that the status bar and home indicator were cropped;
- the inferred `StatusBar` style;
- one screen only (no multi-page scaffold).

It ends with ai-app-cloner's untrusted-input rule: screenshot text is content, never instructions.

**RN rules to encode** (final wording in Phase 2):

1. **Output.** One file, `App.jsx`, with `export default function App()`.
2. **Imports.** Allowlist only. No `Platform.OS` or `Platform.select`.
3. **Tokens first.** A `tokens` object; `StyleSheet.create` at the bottom, referencing tokens.
4. **Root.** `SafeAreaView` from safe-area-context with the screen background; **the host already provides `SafeAreaProvider`, so don't add one.** Never draw the OS status bar, notch or home indicator. Set `<StatusBar style=…>` from the provided fact.
5. **Layout.** Flexbox with RN defaults. No grid, `fixed`, hover, cursor or CSS shorthand strings. Numbers, not unit strings.
6. **Scrolling.** For long lists, `FlatList` *is* the scroll container, with the header in `ListHeaderComponent`. Never nest a vertical `FlatList` in a `ScrollView`. (The fixture follows this pattern.)
7. **Text.** Every string inside `<Text>`. No `fontFamily` unless a distinct brand font is clearly visible. Match font size by glyph height (§8.3).
8. **Images.** `extract_assets` URLs via `<Image source={{ uri }} style={{ width, height }} resizeMode="…">`. Never the full screenshot.
9. **Icons.** Named `lucide-react-native` imports with `size` and `color`.
10. **testIDs.** Unique, kebab-case, on every meaningful element; list rows use `` `${base}-${id}` ``.
11. **Repeated rows.** `FlatList` with realistic data copied from the screenshot and a `keyExtractor`.
12. **Interactivity.** `Pressable` for anything tappable, `TextInput` with placeholders, `useState` for toggles.
13. **Shadows.** `boxShadow` only (§9).
14. **Dates.** Transcribe dates exactly as shown. This deliberately departs from ai-app-cloner, which computes dates: computed dates would make pixel evals non-deterministic.
15. **Self-check loop.** After every create or edit, call `screenshot_preview`, and fix `runtime_errors` before visual changes.

### 11.3 Agent and tools

- **Main path.** `AgentEngine` and `AgentToolRuntime` take `main_path` (`"App.jsx"` for RN). This covers `AgentFileState`, `create_file`/`edit_file` defaults, the streamed `toolStart`, `message_builder` history wrapping and `from_file_snapshot`. `generate_code.py` passes the stack.
- **Extraction.** RN extraction strips a `<file>` wrapper or a ```` ```jsx ```` fence and never runs HTML extraction. `_finalize_response` uses it.
- **Tool descriptions.** `canonical_tool_definitions(stack=…)` gives RN wording for `create_file`, `edit_file` and `screenshot_preview`.
- **`screenshot_preview` (RN).**
  1. Render the template with the profile (route mode).
  2. Wait for `__RN_PREVIEW_READY__`; after 15 s, report a `timeout` error.
  3. Capture the viewport only.
  4. Collect `pageerror`, `[rn-preview]` console errors and `__RN_PREVIEW_ERRORS__`, deduplicated and capped at 20 entries of ≤ 500 chars each (the ai-app-cloner `verify.mjs` pattern).

  The model-facing result is `{status, runtime_errors[], status_bar, viewport}` plus the image as a multimodal part.
- **`retrieve_option`** is already content-agnostic, so it returns `App.jsx`.
- **`extract_assets`** URLs are already absolute (`{scheme}://{host}/local-assets/asset_<sha>.<ext>`); the RN description tells the model to use them as `Image` URIs.
- **Input images** are cropped server-side, one Python implementation shared with evals. This happens before prompt building **and** before asset extraction, so crop boxes and the preview share one coordinate space.
- **Element edits.** The frontend sends the nearest ancestor's `data-testid`, the chain of ancestor testIDs and a text snippet. The RN prompt's targeted-edit section locates the element by `testID` (unique by rule 10).
- **Recorder and evals.** RN writes `final.jsx` plus a URL-mode preview HTML. The eval runner writes `.jsx`, the rendered `.png` and a URL-mode `.html`, so the existing eval pages keep working through iframes.

### 11.4 As built (Phase 2)

- **Stack registration.** The backend accepts `react_native` and rejects video input for it. The frontend's stack option comes with the phone preview (3.1), so the UI never offers a stack it can't render.
- **Prompts.**
  - `get_system_prompt(stack)` lives in `prompts/stack_prompts.py`. `SYSTEM_PROMPT` is now built from named sections with the same bytes; a test pins its SHA-256.
  - The React Native prompt is in `prompts/react_native.py`, with a committed snapshot (`backend/tests/snapshots/`), so every wording change shows in review.
  - A runtime test holds its import list to the runtime's module registry.
  - The screen facts give sizes in pt or dp relative to the screenshot's width, not "1 pt = N px": providers resize images before the model sees them.
- **Device profiles** (`react_native/profiles.py`, `react_native/inputs.py`).
  - Matching goes: exact pixel size, then a downscaled screenshot of a known shape (only when every device of that shape is on one platform), then a guess from the width with no crop.
  - `reactNativeProfile` in the request overrides the platform, width and insets.
  - The crop happens before uploaded-asset IDs, prompt building and `extract_assets`.
  - Updates take the screen from the history's first screenshot. Images attached to an update are references.
- **`screenshot_preview`.**
  - It returns `{status, runtime_errors, status_bar, viewport}` plus one screenshot. A render with errors is still an ok result; only a failed capture isn't.
  - `capture_react_native` is an optional `ScreenshotBackend` method. The tool is offered only when the backend has it, Chromium launched and the runtime is built.
- **Outputs.**
  - An eval output keeps its `<name>_<n>.html` name, but the file is now a preview page loading the runtime from the backend. It sits next to `.jsx`, `.png` (the cropped input's pixel size) and `.json` (status and runtime errors).
  - The run recorder writes `final.jsx`, `final_selfcontained.jsx` and a preview-page `final.html`.
- **Gate 2.9: passed** ([`evidence/phase2-gate.json`](evidence/phase2-gate.json)).
  - **Setup:** five screenshots (four iOS Simulator apps, including dark-mode Settings, and the Pixel 8 fixture capture), run on the app's first create model for OpenAI + Anthropic keys.
  - **Renders:** all five came back `ok`, with no fatal errors and no warnings, for $0.98.
  - **Tool loop:** a recorded create shows `create_file` → `screenshot_preview` → two edits → `screenshot_preview`.
  - **Injected crash:** the agent, starting from a generated screen with a crash, made the requested change, saw the crash (`Cannot read properties of undefined (reading 'map')`, line 70) in `runtime_errors`, fixed it and re-checked.
- **Quality finding for Phase 5.** The outputs are scaled up about 1.3–1.6×. Contacts names use fontSize 26 (iOS uses 17) and rows are 56–66 pt tall (about 44 on iOS). The renders use the right profile, so the model oversizes. This is the first prompt item for Phase 5, to be measured with the eval metrics rather than guessed.
- **Not fixed (pre-existing).** `run_image_evals` reduces absolute `input_files` paths to file names and then looks in `evals_data/inputs/`. Eval sets work.

---

## 12. Frontend design (Phase 3)

- **Stack option.** When selected: video input is disabled, a single image is allowed, and text mode uses the default profile.
- **Device controls.** A platform and device selector, auto-detected from image dimensions using `device-profiles.json` from the backend. A crop overlay draws the top and bottom inset strips on the uploaded image with draggable handles. The profile is stored on the commit and sent as `reactNativeProfile`.
- **Preview.** A phone frame with one viewport; the desktop and mobile toggles are hidden for RN. The template is fetched and cached from `/rn-runtime/`. The iframe loads once and then hot-swaps code by `postMessage`, with the streaming placeholder (§5.5). Variant thumbnails use the same component at thumbnail scale.
- **Code view.** Shows `App.jsx` with `@codemirror/lang-javascript` (`jsx: true`), a new pinned dependency. CodePen is hidden for RN.
- **Selection mode.** Walks up to `[data-testid]`; the overlay rings stay as they are.
- **Agent activity.** The screenshot card gets an RN branch (one phone image and a `runtime_errors` list), and the `create_file` preview is highlighted as `jsx`.
- **Export menu.** "Download Expo project" (zip from the backend), "Open in Snack" (flagged, §13.4) and "Download preview HTML" (inline mode).

### 12.1 As built (Phase 3)

Every change is gated on the stack: `isReactNativeStack(settings.generatedCodeConfig)` (the stack only changes on the start screen), passed as a prop where settings don't reach. Other stacks take the code paths they took before.

- **Stack option.**
  - "React Native (Expo)" (React and Expo logos, beta) is disabled with a build hint when `/api/capabilities` reports `react_native_preview: false`.
  - The upload tab takes one screenshot (a new drop replaces it), refuses video and hides the screen recorder.
- **The target phone** (`lib/react-native/devices.ts`, `appRuntime.ts`).
  - `devices.ts` ports `react_native/profiles.py` to TypeScript, including Python's half-to-even rounding. `rn-runtime/test-vectors/device-detection.json` holds Python's decisions for 35 cases, and both suites run them.
  - A create resolves the phone first, from the device table and the screenshot's pixel size, or the platform's default phone in text mode. The commit keeps `reactNative: {device, overrides}`; edits and retries reuse it.
  - Requests send only the user's overrides as `reactNativeProfile`. The backend then picks the same phone by construction.
  - Checked in the browser: `screenshot_preview`'s viewport equals the preview's size for an iPhone 13 screenshot overridden to an iPhone 15, a Pixel 8 screenshot, and Android text mode (`evidence/phase3-gate.json`).
  - Display only: `withChosenName` names the phone the user picked. The backend ignores names.
- **Device controls** (`ReactNativeDeviceControls`). The uploaded screenshot shows its crop: the status bar and home indicator strips, with draggable handles. Beside it: platform, phone (auto or a table row), logical width, and how the phone was found. Text mode offers the platform only, because the backend's default phone can't take a width override without changing its content height.
- **Phone preview** (`PhonePreview`, `ReactNativeFrame`, `HotSwapChannel`).
  - One Phone tab replaces Desktop and Mobile; "Open in new tab" and the desktop scale controls are hidden.
  - The phone frame draws the cropped status bar and home indicator as blank system bands (a notch, Dynamic Island or punch hole by platform and inset) and scales to fit the pane.
  - A status line gives the device, the content size and the render status. Its expandable list shows `runtime_errors` with `App.jsx` line numbers.
  - The frame loads the runtime once and posts `rn-preview:update` for every change.
  - The channel (unit-tested) waits for the frame's first status and keeps one update in flight, always sending the newest. It treats `renderId` 1 as a freshly booted document, so reloads by anyone recover. It resends after a lost status once 10 s pass.
  - **Streaming mode** applies only while a `create_file` event is running, or before any code arrives. Between tool calls the file is complete, so real errors show.
  - Refresh rebuilds each document with its current code: an app-store nonce, since copying `srcdoc` would replay stale code.
- **Thumbnails.** They use the same frame: lazy (IntersectionObserver), showing the top of the screen. Code is throttled to 300 ms for the selected option and 2 s for the others. A thumbnail whose code hasn't caught up renders in streaming mode, so a half-written file never flashes an error. Until a file is complete, a thumbnail stays blank.
- **Code view.** `@codemirror/lang-javascript` 6.2.5 with `jsx: true`, pinned to the version `lang-html` already resolved. An `App.jsx` label replaces Open in CodePen.
- **Selection.**
  - Select-and-edit walks up to the nearest `[data-testid]`.
  - The rings, sidebar and history name it `testID="…"`, stored as the display-only `selectedElementLabel`.
  - The instruction gives the testID, the testID path from the screen down, and the rendered text (`innerText`, so sibling `Text` blocks stay apart).
  - PreviewComponent's select wiring moved unchanged into `useSelectAndEditFrame`, which takes a target resolver and a ring label.
- **Agent activity and evals.**
  - `screenshot_preview` shows one phone screenshot with its size, status and `runtime_errors`, in the sidebar and in recorded runs.
  - `create_file` previews of `.jsx` are highlighted as JavaScript.
  - Preview pages detected by their `rn-preview-config` (eval outputs, recorded runs) show at the phone's size in Best of N, Agent Runs and Compare.
- **Download preview HTML** (the only React Native download until Phase 4's menu).
  - Babel and the runtime are inlined. Each quoted URL in `App.jsx` whose response is an image becomes a `data:` URI; other URLs stay, and a toast names images that couldn't be embedded.
  - Image fetches use `cache: "no-store"`. The preview's `<img>` loaded the same URL without an `Origin` header, the backend sends no `Vary: Origin`, and the cached response then fails the fetch's CORS check.
  - In a window wider than the phone, the page frames itself at the phone's size.
- **Gates RNW-2 and RNW-3: passed** (`backend/tests/test_rn_frontend_gates.py`; `evidence/phase3-gate.json`, `phase3-*.png`).
  - **Setup.** The real app runs on the Vite dev server against a backend where only the model is scripted (`tests/rn_ui_harness.py`, which also runs as a manual-testing backend).
  - **What it checks.** The phone preview and its parity with `screenshot_preview`; the document booting once and hot-swapping from streaming to final; four thumbnails; the code view; the offline download with zero network requests; a targeted edit by testID.
  - **Stability.** 3/3 tests passed in 4 consecutive runs of about 25 s.
  - **Browser.** The sandbox's Chromium 141 (Playwright 1.61 pins 149, whose download is blocked here).
- **Not done or untested.**
  - The export menu (Phase 4) and "Open in new tab" for React Native.
  - Dark mode was only glanced at.
  - A JPEG screenshot with an EXIF rotation would decode rotated in the browser and not in PIL (**Assumed**, not tested).
  - A hanging `App.jsx` would freeze the app too, as for every stack: the preview iframe is same-origin (R7).
  - Pre-existing and unrelated: in the default same-origin setup the Vite proxy doesn't forward `/agent-runs` or `/evals`, so those pages need `VITE_HTTP_BACKEND_URL`.

---

## 13. Export design (Phase 4)

### 13.1 Expo project zip

| File | Content |
| --- | --- |
| `package.json` | Pins as written by `npx expo install` in a fresh SDK 57 probe, where `npx expo install --check` reports "Dependencies are up to date": `expo ~57.0.24`, `expo-status-bar ~57.0.1`, `react 19.2.3`, `react-dom 19.2.3`, `react-native 0.86.3`, `react-native-web ^0.21.2` (SDK range `~0.21.0`; task 4.1 decides whether to pin exactly 0.21.2 to match the runtime), `react-native-svg 15.15.4`, `react-native-safe-area-context ~5.7.0`, `lucide-react-native 1.48.0`. Scripts: `start`, `ios`, `android`, `web`. |
| `app.json` | name, slug, `userInterfaceStyle`, from the blank SDK 57 template |
| `index.js` | `registerRootComponent(Root)`, where `Root` wraps `App` in `SafeAreaProvider` (§10) |
| `App.jsx` | unchanged except asset URL literals (§13.2) |
| `assets.js` | only when there are local assets |
| `README.md` | how to run with Expo Go or `npx expo start` |

RNW-5 (version parity) compares `rn-runtime/dist/manifest.json` with the template's pins in a unit test.

### 13.2 Assets (Untested beyond data URIs rendering natively)

Local `/local-assets/` URLs are unreachable from a phone. The exporter proceeds in three steps:

1. Download each referenced local asset.
2. Write `assets.js` exporting `ASSETS = { asset_<sha>: 'data:image/png;base64,…' }`.
3. Replace each *quoted URL literal* in `App.jsx` with `ASSETS.asset_<sha>`, and add one import.

This keeps `App.jsx` readable while `{ uri: … }` still works on both platforms (Verified). Public URLs (for example Replicate outputs) stay as they are, but Replicate delivery URLs expire, so the exporter embeds those too. Bundled-file `require()` is a later option.

### 13.3 Native bundling gate (RNW-6)

`npx expo export --platform ios --platform android` against the zip, run in a cached template workspace. On macOS it is **Verified** at about 22 s per project. On **Linux** it is **Verified in Phase 4** (§13.5); Docker wasn't needed, only Node and npm.

### 13.4 Snack

- `snack-sdk@6.6.2` and `snack-content@3.6.2`, the newest on npm (2026-04-01), know SDKs **50–54** (default 54).
- The `expo/snack` main branch (last commit 2026-09-12) has `newestSdkVersion = '55.0.0'`, with a TODO to make 55 the default.
- **Snack trails our export SDK by two releases.**

Plan:

- Implement "Open in Snack" with Snack's documented URL parameters (`files`, `dependencies`, `sdkVersion`, `platform=web`), with no `snack-sdk` dependency.
- Pin `sdkVersion=55.0.0`, and label the menu item "Opens in Snack (Expo SDK 55)".
- Send `App.js` (a `SafeAreaProvider` wrapper) plus `Screen.js` (the model's code).
- Hide it behind a flag.

Known limits:

- Local assets are unreachable from Snack.
- Very long files may exceed URL limits.
- Store Expo Go runs SDK 57, so Snack's "My device" won't open SDK 55 on iOS; the web and Appetize players still work.

A Phase 4 go/no-go check decides whether it ships enabled.

---

### 13.5 As built (Phase 4)

- **The zip** (`POST /api/export/expo`, `react_native/expo_project.py`).
  - It is modelled on Expo's own `expo-template-blank@sdk-57` (fetched from npm): `main: index.js`, the same scripts, and `app.json` without the template's icons (Expo falls back to defaults).
  - `package.json` takes its dependencies from `expo-sdk.json`, the runtime's source of truth, so RNW-5 now covers the export too. `react-native-web` is pinned exactly to 0.21.2, the runtime's version, which satisfies SDK 57's `~0.21.0`.
  - `index.js` wraps `App` in `SafeAreaProvider`. The files sit under one `screenshot-to-code-app/` folder.
- **Assets** (`react_native/export_assets.py`, §13.2 as planned).
  - Each quoted URL literal that turns out to be a raster image (checked with PIL; `Image` can't show SVG natively) becomes `ASSETS.asset_<sha256 prefix>` in `assets.js`. `App.jsx` imports it after its last import.
  - `/local-assets/` files are read from disk, with a path-traversal guard.
  - Remote URLs are fetched only when they look like images or come from `replicate.delivery`, through the HTML export's fetcher, which refuses private addresses.
  - A literal that is a JSX attribute string gets braces.
  - The README lists what wasn't embedded.
- **RNW-6** (`react_native/bundle_check.py`).
  - Setup: one workspace per set of pins (under `~/.cache/screenshot-to-code`, or `RN_BUNDLE_WORKSPACE`), `npm install` once (402 MB, 34 s), and a file lock so one bundle runs at a time.
  - Timing: a cold bundle takes about 60 s; warm runs about 10 s.
  - Output: failures come back as Metro's error lines.
  - Commands: `python -m react_native.bundle_check` takes `.jsx` files or export zips. With `RN_BUNDLE_CHECK=1`, eval reports gain `native_bundle`.
  - **Verified on Linux** without Docker. The fixture bundles to 2,573 and 2,571 modules, as on macOS.
  - Over all 14 fixtures, only the unresolvable import and the syntax error fail. Unknown icons, DOM elements, throws and hangs all bundle. So RNW-6 complements the preview's runtime checks; it doesn't replace them (`evidence/phase4-gate.json`).
- **Export menu.**
  - The React Native download button opens a menu: Expo project, preview HTML, and Open in Snack when `VITE_SNACK_EXPORT=true`.
  - Snack (§13.4): `App.js` (the provider) plus `Screen.js`, with the SDK from `expo-sdk.json`'s `snack.sdkVersion`. Over 60,000 URL characters the app sends users to the zip instead.
  - **Assumed, not verified:** the URL format. `snack.expo.dev` is unreachable from the sandbox.
- **Tests.**
  - The gate tests now download the Expo zip through the app. With `RN_BUNDLE_CHECK=1`, that zip bundles for iOS and Android: passed.
  - They also check the Snack URL the app builds.
- **Not done here.**
  - RNW-6 on live-model eval outputs: `api.openai.com` is blocked by the sandbox's network policy, and the Phase 2 outputs aren't in the repo.
  - The Expo Go check: no simulator, emulator or KVM. `scripts/expo-go-check.sh` automates it for a machine that has one (untested).
  - The Snack go/no-go.

---

## 14. Evaluation design (Phase 5)

- **Eval set.** An eval set under the existing (gitignored) `backend/evals_data/sets/<name>/inputs/`, with 25–30 phone screenshots:
  - iOS and Android, light and dark;
  - lists and feeds, forms, settings, onboarding, tab bars, chat, cards;
  - at least 3 long stitched screenshots.

  A committed manifest records each image's source, licence and tags. The images themselves stay out of git.
- **Harness.** Extend `backend/evals/`. RN outputs are the `.jsx`, the rendered PNG at the profile, and a metrics JSON.
- **Metrics.**
  - SSIM and mean absolute pixel difference on the size-matched, inset-cropped pair (pure NumPy, to avoid heavy dependencies).
  - CLIP similarity, optional because it pulls in torch.
  - Runtime-error, unknown-import and unknown-icon rates.
  - Native-compat lint counts.
  - A fake-status-bar detector: a time pattern or battery/wifi/signal icons in the top 60 pt.
  - Native-bundle pass rate.
  - Refinement iterations, latency and token cost, from the existing run recorder.
- **Protocol.** Baseline first, then before-and-after numbers per prompt change in `EVALS.md`.

---

## 15. Deviations from the brief (consolidated)

1. **Expo SDK 57**, not 56: same web-side pins; SDK 57 is current and what Expo Go runs. SDK 58 (React 19.3) is in RC, so a bump procedure is planned (§16, R2).
2. **The system prompt is composed per stack**, not extended in place (§11.2), so existing stacks' prompts stay byte-identical.
3. **The template has a scripts placeholder** instead of a runtime-URL placeholder, and the boot logic lives in the runtime bundle (§5.1).
4. **Playwright loads the runtime by route interception**, not a backend self-URL (§6).
5. **The host provides `SafeAreaProvider`**; `App.jsx` does not (§10).
6. **Docs live in `design-docs/react-native/`** because of the root `plan.md` clash.
7. **Snack is pinned to SDK 55 behind a flag** (§13.4).
8. **ai-app-cloner's computed-date rule is not adopted**; dates are transcribed (rule 14).

---

## 16. Risk register

| # | Risk | Likelihood | Impact | Mitigation | Phase |
| --- | --- | --- | --- | --- | --- |
| R1 | The preview diverges from devices (fonts, `includeFontPadding`, shadow semantics) and the agent "fixes" correct code toward the web | High | Medium | Metric calibration (§8.3); the `boxShadow`-only convention; the prompt names known gaps; Phase 6 emulator fidelity pass | 1, 5, 6 |
| R2 | Expo SDK cadence (56 → 57 in 6 weeks; 58 in RC with React 19.3): store Expo Go drops old SDKs | High | Medium | Pins in one manifest; RNW-5 parity test; documented bump procedure (runtime + template + table); CI check against `expo install --check` | 1, 4 |
| R3 | Snack lags (max SDK 55) and can't reach local assets | Certain | Low | Flagged, labelled SDK 55, go/no-go check; the zip is the primary export | 4 |
| R4 | Web-only code slips through (DOM tags, unit strings, CSS shorthands, `Platform.OS`) and passes the web preview | High | High | Babel native-compat lint (fatal for host tags); prompt rules; RNW-6 Metro gate catches imports only | 1, 2 |
| R5 | Performance: four variants plus the main preview, each parsing about 4.6 MB of JS on every streamed update | High | Medium | `postMessage` hot-swap with the iframe loaded once; placeholder while streaming; lazy thumbnails. **Built in Phase 3** (§12.1): each frame boots once, and streamed updates are coalesced to one in flight | 1, 3 |
| R6 | Hosted or external screenshot backends can't render RN | Medium | Medium | Optional `capture_react_native` capability; the tool is not offered without it; hosted-branch support scoped separately | 2 |
| R7 | Generated code runs same-origin in the app iframe (keys live in `localStorage`) | Pre-existing | Medium | Unchanged from existing stacks; a future option is a sandbox without `allow-same-origin` plus `postMessage` selection | Later |
| R8 | Wrong insets or platform detection for unknown or Android devices | Medium | Medium | Known-device table, user-adjustable crop overlay, fallbacks; measure Android insets with `dumpsys`. **The crop overlay was built in Phase 3** (§12.1), and its detection runs on vectors shared with the backend | 2, 3 |
| R9 | Non-Latin or emoji glyph fallback differs by host | Medium | Low | Noto fonts in the Docker image; the eval set notes locale | 1 |
| R10 | Bundle growth past budget (lucide, fonts) | Low | Low | Build-time budget; fonts as separate files if needed | 1 |
| R11 | pnpm resolution of the `react-native` npm alias differs from npm (the spike used npm) | Medium | Low | Phase 1 ports to pnpm; esbuild alias plus one-copy assertion; fall back to a committed `package-lock.json` | 1 |
| R12 | Live-model gates need API keys and manual Expo Go checks need devices | Certain | Blocks gates | Needs the user (keys; iOS and Android devices). The scripted-provider harness covers non-LLM legs meanwhile | 2, 4, 5 |
| R13 | Linux Metro bundling untested | Medium | Medium | Run RNW-6 in Docker or CI in Phase 4. **Verified on Linux in Phase 4** (§13.5) | 4 |
| R14 | Runtime errors in event handlers only surface on interaction | Medium | Low | Out of v1 scope (static screen); flows are Phase 6 | 6 |

---

## 17. Open questions for review

1. Approve **Expo SDK 57** over the brief's SDK 56? **Approved.**
2. Approve the **per-stack composed system prompt** instead of editing the shared one? **Approved; built in Phase 2 (§11.4).**
3. **Build artifacts:** build in Docker/CI and don't commit `rn-runtime/dist` (recommended), or commit it for Node-free backend setups? **Build it; `dist/` isn't committed.**
4. **Development React build** in the runtime (+58 KB gzip, full error text)? **Approved.**
5. **Snack:** ship pinned to SDK 55 behind a flag, or drop it from v1?
6. **API keys and devices:** Phase 2's gate (5 live generations) and Phase 4's Expo Go check need model API keys on this machine and one physical iOS and one Android device. Simulators worked for Phase 0; is that acceptable for the Phase 4 manual check? **Keys: OpenAI and Anthropic are set (no Gemini, so no `extract_assets`). Devices: still open.**
7. **Linux text rendering (new in Phase 3).** Chromium on Linux fails the text-width calibration unless it runs with `--font-render-hinting=none` (§8.3). Options:
   - Launch the backend's Chromium with that flag. It changes every stack's screenshots slightly.
   - Launch a second browser for React Native captures only.

   Either way, re-run the calibration in the Docker image, whose Chromium 149 is untested.

---

## Appendix A: reproducing Phase 0

The Phase 0 spike and its gate runner (55/55 checks) are preserved in commit `87f852f`
(`git show 87f852f --stat`). Phase 1 promoted the spike to `rn-runtime/`, whose gates run in the
backend test suite:

```bash
cd rn-runtime && pnpm install && pnpm build
cd ../backend && poetry run pytest tests/test_rn_runtime.py
```

Native probe (not committed; about 5 minutes):

1. `npx create-expo-app@latest probe --template blank@sdk-57`
2. `npx expo install react-native-svg react-native-safe-area-context react-native-web react-dom`
3. `npm i -E lucide-react-native@1.48.0`
4. Copy `fixtures/App.jsx`, with the avatar URL replaced by a data URI.
5. Wrap `App` in `SafeAreaProvider` in `index.js`.
6. `npx expo install --check`
7. `npx expo export --platform ios --platform android`
8. `npx expo start --ios` and `npx expo start --android`

Environment: macOS 26.4.1 on an Apple M2 Max; Python 3.12.14; Playwright 1.61.0 with Chromium 149.0.7827.55 (headless); Node 22.22.1; esbuild 0.28.2; Xcode iOS 26.4 Simulator (iPhone 17e); Android emulator with a temporary Pixel 8 AVD (API 36, arm64; deleted afterwards).

Evidence in [`evidence/`](evidence/):

| File | What it shows |
| --- | --- |
| `gate-report.json` | full gate output |
| `fixture-web-vs-native.png` | web preview vs native iOS vs native Android, same fixture |
| `shadows-web-vs-native.png` | RNW-8 shadow comparison |
| `broken-syntax.png` | the error panel as it appears in screenshots |
| `broken-icon.png` | the unknown-icon placeholder |
| `phase2-gate.json` | the Phase 2 gate: five live generations and the injected-crash fix (§11.4) |
| `phase3-gate.json` | the Phase 3 gates RNW-2 and RNW-3, device parity checks, and the Linux text calibration numbers (§12.1, §8.3) |
| `phase3-phone-preview.png` | the phone preview after a scripted generation: four option thumbnails and a testID selection |
| `phase3-device-controls.png` | the upload tab's crop overlay and device controls |
| `phase4-gate.json` | the Phase 4 gate status: RNW-6 on the fixtures and on an export downloaded through the app; what couldn't run here (§13.5) |
| `phase3-download-offline.png` | the downloaded preview HTML opened from `file://` offline, framed in a wide window |
