# rn-runtime

The browser runtime behind the React Native (Expo) stack's preview. The model writes one file,
`App.jsx`; this package turns it into a phone screen rendered with react-native-web, in the app's
preview iframe, in the backend's Playwright screenshots, and in the downloadable preview HTML.
Design: [`design-docs/react-native/DESIGN.md`](../design-docs/react-native/DESIGN.md).

## Build

```bash
cd rn-runtime
pnpm install
pnpm build          # -> dist/ (gitignored)
pnpm sizes          # optional: size table for build variants
```

The backend serves `dist/` at `/rn-runtime/` (override the location with `RN_RUNTIME_DIST`).
Without a build, the backend reports `react_native_preview: false` from `/api/capabilities`.
Rebuild after changing anything in this directory.

## What's in `dist/`

| File | What it is |
| --- | --- |
| `rn-runtime.<hash>.js` | One IIFE: React, ReactDOM, react-native-web, react-native-svg, react-native-safe-area-context, lucide-react-native, an expo-status-bar shim, and the preview boot code |
| `babel-standalone-<version>.<hash>.js` | A pinned copy of `@babel/standalone` 7.x (classic JSX runtime) |
| `preview-template.html` | The one template the backend and frontend both fill |
| `manifest.json` | File names, package versions and sizes |
| `expo-sdk.json`, `device-profiles.json` | The Expo SDK pins and the known-device table |

The build fails if the react-native-web font patch or the safe-area patch stops matching, if a
core package is bundled twice, if a version drifts from `expo-sdk.json`, or if the runtime grows
past 1,900 KB raw / 700 KB gzip.

## Source layout

| Path | Purpose |
| --- | --- |
| `src/runtime-entry.js` | Module registry (`window.__RN_MODULES__`) and the lucide / react-native proxies |
| `src/preview.js` | Transform (Babel), execute, mount, error and readiness reporting |
| `src/preview-template.html` | Template with the `__RN_PREVIEW_CONFIG__` and `<!--RN_PREVIEW_SCRIPTS-->` placeholders |
| `src/shims/` | expo-status-bar stand-in; profile-driven safe-area provider |
| `fixtures/` | Test screens, including deliberately broken ones |
| `expo-sdk.json` | Single source of truth for the Expo SDK pins |
| `device-profiles.json` | Known screenshot sizes, logical sizes, scales and insets |

## Bumping the Expo SDK

1. Read the new SDK's `bundledNativeModules.json` (`npm pack expo@<version>`) for `react`,
   `react-dom`, `react-native`, `react-native-web`, `react-native-svg` and
   `react-native-safe-area-context`.
2. Update `expo-sdk.json`, then `package.json` to the same versions
   (`@react-native/assets-registry` follows `react-native`).
3. `pnpm install && pnpm build`. The build refuses mismatched versions.
4. Run the backend suite (`cd backend && poetry run pytest tests/test_rn_runtime.py`) and check
   the Snack SDK in `expo-sdk.json` against Snack's newest supported version.
