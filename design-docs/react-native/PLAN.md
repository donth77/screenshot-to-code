# React Native (Expo) output stack: plan

Companion to [`DESIGN.md`](DESIGN.md), which holds section references (§) and evidence.

- **Estimates** are focused engineer-days. They exclude model run time and time spent waiting for the inputs listed in "Needs from you".
- **Tests** at the end of every phase: `cd backend && poetry run pytest`; `poetry run pyright` (no new warnings in changed files); `cd frontend && pnpm lint` (no new problems over the 19-error/6-warning baseline); `pnpm test`.
  - The browser tests (`test_rn_runtime.py`, `test_rn_vite_preview.py`, `test_rn_frontend_gates.py`) skip without Chromium, the built runtime or the frontend's `node_modules`.
- **Existing stacks:** every task is gated on `stack == "react_native"`. The existing-stack tests (and new byte-identity tests) must stay green.

## Phase 0: reconnaissance and spike (done)

| Done | Evidence |
| --- | --- |
| Read the required docs and code in both repos; re-verified the prior findings | DESIGN §2 |
| Ran the existing React stack end to end (scripted provider, real engine, Playwright, export) and the test suites | DESIGN §2 |
| Audited every place that renders, stores or exports code, and every `index.html` assumption | DESIGN §3.1 |
| Built a throwaway runtime and fixtures (the spike, preserved in commit `87f852f`; promoted to `rn-runtime/` in Phase 1) | DESIGN §4–5 |
| **RNW-1, RNW-4, RNW-7 pass in real Chromium** (55/55 checks, including iframe, offline, fonts, safe-area and shadow checks) | `evidence/gate-report.json` |
| Ran the same fixture natively (iOS Simulator, Android emulator); Metro bundling; `expo install --check` | DESIGN §9, §10, §13 |

## Phase 1: runtime and wrapper (≈ 6 days; done)

| # | Task | Deliverable and tests | Est. |
| --- | --- | --- | --- |
| 1.1 | Promote the spike to `rn-runtime/` | pnpm package with exact pins and lockfile; `build` script with the §4.3 assertions and the §4.4 budget (fail over 700 KB gzip); `device-profiles.json`; `dist/` with hashed files and `manifest.json`. If pnpm resolves the npm alias badly, fall back to npm (R11). | 0.5 |
| 1.2 | Template renderer, Python and TypeScript | `backend/react_native/preview_html.py` (url/route/inline modes, escaping, single-pass substitution) and `frontend/src/lib/react-native/previewHtml.ts`, sharing a JSON test-vector file that both test suites run | 0.75 |
| 1.3 | Harden the error and ready contract | Normalise Babel columns (1-based everywhere); image-settle cap; `timeout` status; caps and dedupe; printf console formatting; unit tests in the fixture suite | 0.5 |
| 1.4 | Hot-swap and streaming mode | `postMessage({type: 'rn-preview:update'})` remount without reloading scripts; keep the last good render while streaming, with a "Writing App.jsx…" badge; measure re-render time (target < 150 ms) | 0.75 |
| 1.5 | Native-compatibility lint | Babel visitor inside the transform, reporting `native_compat`: fatal for DOM host tags and `onClick`; warnings for `Platform.*`, web-only styles, CSS shorthands, unit strings, `shadow*`/`elevation` and `className`; one fixture per rule | 0.75 |
| 1.6 | Font calibration | A text-grid fixture rendered in the preview and on the iOS Simulator and Android emulator. Target: median width error ≤ 1.5%, line height ≤ 0.5 pt. Record the numbers in DESIGN §8. *Done differently than planned:* the measurements ruled out `size-adjust`, so the preview applies per-platform text rules (fitted iOS tracking; Android's pixel-rounded font size, line spacing and `includeFontPadding`). See DESIGN §8.3. | 1.0 |
| 1.7 | Fixture test suite | `backend/tests/test_rn_runtime.py`, running through the Python renderer and Playwright, skipped when `dist/` or Chromium is missing. Covers the full fixture plus the unknown-import, unknown-icon, runtime-throw, syntax-error, no-default-export and lint fixtures. | 0.75 |
| 1.8 | Version-parity check (RNW-5) | Unit test: `manifest.json` versions equal the export template's pins | 0.25 |
| 1.9 | Serving and packaging | `/rn-runtime` StaticFiles mount with immutable caching for hashed files; `react_native_preview` in `/api/capabilities`; a Node stage in `backend/Dockerfile`. Also the `/rn-runtime` Vite proxy, pulled forward from 3.2. *Noto fonts deferred* (DESIGN §8.1). | 0.5 |

**Gates.**

- **RNW-1, RNW-4, RNW-5 and RNW-7** run in the suite from task 1.7.
- **RNW-2** at library level: the TypeScript renderer feeds an iframe on a page served by the Vite dev server, tested with Playwright. It is re-verified through the real UI in Phase 3.
- **RNW-3** at library level: the inline renderer's file loads from `file://` offline. It is re-verified through the real download in Phase 3.

**Commits.**

1. `rn-runtime` package
2. Template renderers and vectors
3. Error contract
4. Hot-swap
5. Lint
6. Font calibration
7. Test suite and parity test
8. Serving and Docker

## Phase 2: backend stack (≈ 6 days; done, gate passed; see DESIGN §11.4)

| # | Task | Deliverable and tests | Est. |
| --- | --- | --- | --- |
| 2.1 | Register the stack | `react_native` in `prompt_types.py` and `stacks.ts` (plus `StackLabel` logos, `inBeta`); fix the stale `prompts/types.py` comment. *The frontend option moved to 3.1, so the UI never offers a stack it can't preview.* | 0.25 |
| 2.2 | Main-path plumbing | `main_path` through `AgentEngine`, `AgentToolRuntime`, `state`, `message_builder`, `from_file_snapshot` and `generate_code`; RN extraction (`<file>`/fence stripping, never HTML extraction). Tests: RN uses `App.jsx`; all other stacks unchanged. | 0.75 |
| 2.3 | Prompts | Shared prompt constants; `get_system_prompt(stack)`; the RN system prompt (rules in DESIGN §11.2); RN image, text and update user turns with profile facts. Tests: `SYSTEM_PROMPT` byte-identical for existing stacks; RN prompt snapshot. | 1.0 |
| 2.4 | Device profiles | `backend/react_native/profiles.py`: detection from `device-profiles.json`, overrides, content-height maths, PIL crop applied to input images before prompt building and asset extraction, and status-bar style inference. Tests with synthetic images. Measure Android insets on emulators with `dumpsys`. | 1.0 |
| 2.5 | React Native capture | Optional `capture_react_native(html, profile, routes)` on `ScreenshotBackend`, implemented in `PlaywrightBackend`: route interception, readiness wait with timeout, `pageerror`/console/`__RN_PREVIEW_ERRORS__` collection, viewport-only screenshot | 0.75 |
| 2.6 | `screenshot_preview` for RN | Stack-aware tool definitions and descriptions; the RN result schema `{status, runtime_errors, status_bar, viewport}`; UI summary; tool offered only when the capability exists | 0.5 |
| 2.7 | Scripted-provider integration tests | Extend the Phase 0 harness into tests: create `App.jsx`, screenshot, inject a runtime error, see `runtime_errors`, edit, confirm clean status | 0.5 |
| 2.8 | Evals and recorder output | Eval runner writes `.jsx`, the rendered `.png` and URL-mode `.html`; the recorder writes `final.jsx` | 0.5 |
| 2.9 | **Gate run** | One generation on each of 5 eval screenshots with **zero unhandled runtime errors**, plus a transcript where the agent fixes an injected error from `runtime_errors` | 0.5 + model time |

**Commits.**

1. Stack registration
2. Main-path plumbing
3. Prompt composition
4. RN prompt
5. Device profiles and cropping
6. RN capture
7. `screenshot_preview` for RN
8. Integration tests
9. Eval output

## Phase 3: frontend (≈ 6 days; done, gates passed; see DESIGN §12.1)

| # | Task | Deliverable and tests | Est. |
| --- | --- | --- | --- |
| 3.1 | Stack option and gating | "React Native (Expo)" option; video disabled; single image; `reactNativeProfile` in requests; `fileState.path = "App.jsx"` | 0.5 |
| 3.2 | Runtime client | Fetch and cache `manifest.json` and the template; `/rn-runtime` Vite proxy entry | 0.25 |
| 3.3 | Phone preview | Phone frame, single viewport, hot-swap iframe, streaming badge, refresh; `PreviewPane` hides desktop/mobile for RN | 1.25 |
| 3.4 | Variant thumbnails | RN thumbnails through the same component (lazy, hot-swap) | 0.5 |
| 3.5 | Device controls | Platform and device selector (auto-detected, overridable); crop overlay with draggable inset handles | 1.0 |
| 3.6 | Code view | `App.jsx` shown with `@codemirror/lang-javascript` (`jsx`); CodePen hidden for RN | 0.25 |
| 3.7 | testID selection | Walk up to `[data-testid]`; RN edit instruction with the testID chain and a text snippet; update `select-and-edit` tests | 0.5 |
| 3.8 | Agent activity and eval views | RN screenshot card with `runtime_errors`; `jsx` highlighting; eval previews | 0.5 |
| 3.9 | Download preview HTML | Inline mode with assets as data URIs | 0.25 |
| 3.10 | **Gates** | **RNW-2**: Playwright test against the Vite dev server running a real RN generation (scripted backend). **RNW-3**: the downloaded file renders from `file://` offline. | 0.75 |

**Gates: passed.** `backend/tests/test_rn_frontend_gates.py` runs the app on the Vite dev server against a backend where only the model is scripted (`tests/rn_ui_harness.py`). 3/3 tests passed in 4 consecutive runs. See `evidence/phase3-gate.json`.

- **RNW-2 checks:**
  - the phone preview matches the viewport `screenshot_preview` used;
  - the preview boots once and hot-swaps from streaming to final;
  - four thumbnails render;
  - the code view shows `App.jsx`.
- **RNW-3:** the downloaded file renders from `file://` in an offline context with zero network requests.
- **Targeted edit:** a testID edit is checked end to end too.
- **Caveat:** the gates ran on Linux with the sandbox's Chromium 141, not the Chromium 149 that Playwright 1.61 pins.

**Also done in Phase 3:**

- Device detection ported to TypeScript, with vectors shared with the backend (`rn-runtime/test-vectors/device-detection.json`).
- Evidence screenshots in `evidence/phase3-*.png`.
- The Linux text-calibration measurement (DESIGN §8.3; open question §17.7).
- The `rn-runtime` Docker stage built (DESIGN §6).

**Commits.** One per row, plus the device-detection port and the scripted UI harness. 3.2 came first, because 3.1 needs the device table.

## Phase 4: export (≈ 4 days)

| # | Task | Deliverable and tests | Est. |
| --- | --- | --- | --- |
| 4.1 | Expo template and zip | SDK 57 `package.json`, `app.json`, `index.js` (with `SafeAreaProvider`), `README.md`; `POST /api/export/expo`. Tests for zip contents and pins. | 0.75 |
| 4.2 | Asset rewriting | `assets.js` with data URIs and literal replacement in `App.jsx`; expiring Replicate URLs embedded too. Tests. | 0.75 |
| 4.3 | Native bundling check (**RNW-6**) | Script running `npx expo export --platform ios --platform android` in a cached workspace; a Linux run in Docker or CI; wired into evals as the pass rate | 1.0 |
| 4.4 | Snack | URL-parameter export pinned to SDK 55, behind a flag; go/no-go on 3 outputs (URL length, rendering) | 0.5 |
| 4.5 | **Expo Go check** | Manual: one iOS and one Android device. An automated simulator/emulator script (the Phase 0 method) as a supplement. | 0.5 |
| 4.6 | README section | Running the RN stack locally, rebuilding the runtime, and the SDK bump procedure (runtime pins, template pins, parity test) | 0.25 |

**Gate.** RNW-6 passes on every eval output, and the manual Expo Go check passes.

## Phase 5: evals and prompt iteration (≈ 5 days plus model time)

| # | Task | Deliverable | Est. |
| --- | --- | --- | --- |
| 5.1 | Eval set | 25–30 screenshots, per DESIGN §14; a committed manifest (source, licence, tags, insets); images in gitignored `evals_data/sets/` | 1.0 |
| 5.2 | Harness | `react_native` in `run_image_evals`; per-output PNG and metrics JSON | 0.75 |
| 5.3 | Metrics | SSIM and pixel difference (NumPy); optional CLIP; error, lint and unknown-import/icon rates; fake-status-bar detector; bundle pass rate; iterations, latency and cost from the recorder; aggregate report | 1.25 |
| 5.4 | Baseline | Baseline run; create `EVALS.md` | 0.5 |
| 5.5 | Prompt iteration | 3–5 rounds with before-and-after numbers in `EVALS.md` | 1.5 |

## Phase 6: stretch (separate proposals, not estimated)

- Multiple screens and navigation (Expo Router from inferred navigation bars).
- A twrnc variant.
- TypeScript output.
- An emulator fidelity pass via `adb exec-out screencap`, reusing the Phase 0 method.
- Interaction flows (ai-app-cloner's `flows.mjs`).

## Totals

About **26 engineer-days** across Phases 1–5. The row estimates sum to 5.75 + 5.75 + 5.75 + 3.75 + 5.0 = 26.0, or about 5–6 weeks for one engineer. The critical path is 1.1 → 1.2 → 2.5 → 2.6 → 2.9 → 3.3 → 3.10 → 4.3 → 5.4.

## Needs from you

1. **Review decisions:** DESIGN §17.
2. **Model API keys** in `backend/.env`: OpenAI and Anthropic are set. Gemini would enable `extract_assets`; Replicate is optional.
3. **Eval screenshots**, or approval of permissively licensed sources (5.1).
4. **Devices** for 4.5 (one iOS, one Android), or approval to use the simulator and emulator method from Phase 0.
5. **Docker running**, or CI access, for the Linux RNW-6 run (4.3).
