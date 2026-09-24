# rn-runtime spike (Phase 0, throwaway)

Proof that a single-file React Native screen (`App.jsx`) can be previewed with
react-native-web in real Chromium through the backend's own Playwright backend.
Phase 1 replaces this directory with the real `rn-runtime/` package. See
[`design-docs/react-native/DESIGN.md`](../../design-docs/react-native/DESIGN.md).

## Layout

| Path | What it is |
| --- | --- |
| `build.mjs` | esbuild build: one IIFE (React, ReactDOM, react-native-web, svg, safe-area, lucide, expo-status-bar shim), content-hashed, plus a pinned copy of `@babel/standalone@7.25.6` and `manifest.json` |
| `src/runtime-entry.js` | module registry (`window.__RN_MODULES__`), lucide/unknown-export proxies |
| `src/preview.js` | transform (Babel classic runtime + CommonJS), execute (`new Function`), mount (`AppRegistry` + `SafeAreaProvider` + error boundary), error and ready reporting |
| `src/preview-template.html` | the one template; `__RN_PREVIEW_CONFIG__` and `<!--RN_PREVIEW_SCRIPTS-->` placeholders |
| `src/shims/` | `expo-status-bar` stand-in; profile-driven `NativeSafeAreaProvider` |
| `fixtures/` | `App.jsx` (every required primitive) and deliberately broken fixtures |
| `gates/run_gates.py` | gate runner (RNW-1, RNW-4, RNW-7, plus fonts, safe area, shadows, iframe and offline precursors) |
| `measure-sizes.mjs` | builds size variants and prints the size table |

## Run

```bash
cd spikes/rn-runtime
npm ci
npm run build                      # -> dist/ (gitignored)
node measure-sizes.mjs /tmp/sizes  # optional size table

cd ../../backend
poetry run python ../spikes/rn-runtime/gates/run_gates.py   # -> gates/out/ (gitignored)
```

The gate runner needs Playwright's Chromium (`poetry run playwright install chromium`)
but no network access: the runtime, fixtures and images are served locally.
