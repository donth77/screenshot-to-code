# Text calibration

The preview draws iOS text with Inter (SF Pro can't be redistributed) and Android text with Roboto. Without corrections, preview text is 4–12% wider than on an iPhone, and on Android every `Text` is about 3 dp shorter per line. The agent compares the preview with the input screenshot, so it would "fix" those gaps by changing font sizes that were already right.

`src/text-metrics.js` wraps the `Text` that generated code imports and applies the rules below. `fit.json` holds their constants and the one fitted table.

## The rules

| | iOS (SF Pro → Inter) | Android (Roboto) |
| --- | --- | --- |
| Font size | As written | Rounded up to a whole device pixel: React Native renders at `ceil(size × density)` px (`TextAttributeProps.setFontSize`) |
| Width | Tracking per size and weight, fitted: SF Pro tracks size-dependently (looser below ~13 pt, tighter above) and Inter doesn't | Nothing else: the rounded size alone matches |
| `letterSpacing` | Added on top of the tracking. `letterSpacing: 0` turns pair kerning off (CoreText's kern 0), so the preview sets `fontKerning: 'none'` | As written |
| Line (no `lineHeight`) | SF Pro ascender + descender = (1950 + 494) / 2048 em. iOS rounds the whole text block up to a device pixel; CSS can't, so the preview is up to 1 device pixel short | Baselines spaced by Roboto's hhea ascent + descent (1900 + 500) / 2048, each rounded to a pixel. `includeFontPadding` adds space above the first line up to the bounding box top (yMax 2163) and below the last down to its bottom (yMin −555), each rounded up |
| Explicit `lineHeight` | As written | Rounded up to a pixel per line; no font padding |
| Nested `Text` | Inherits, like native; its own size or weight recomputes the tracking | Inherits; its own size is rounded; padding only on the outermost `Text` |

Where the constants come from:

- **SF Pro.** `UIFont.systemFont(ofSize:weight:)` on the iOS 26.4 Simulator reports `lineHeight` = 1.193359 em, ascender 0.952148 and descender 0.241211, at every size and weight. macOS's SFNS.ttf has different line metrics, so it can't stand in.
- **Roboto.** Read from the bundled `@fontsource/roboto` files: head yMax 2163, yMin −555; hhea 1900 / −500; 2048 units per em.

`fit.py` checks the line rules against every native measurement. It exits with an error if any height is off by more than the 0.01 logging precision, and all 97 samples per platform pass.

## Results

Preview against the device, from `measure_web.py`. Width error is in %, height error in pt (iOS) or dp (Android), each as median / max. `grid` is what the tracking was fitted to; every other category was held out.

| Category | Samples | iOS width, before → after | iOS height, after | Android width, before → after | Android height, before → after |
| --- | --- | --- | --- | --- | --- |
| grid (8 sizes × 3 weights × 2 strings) | 48 | 4.04 / 11.57 → 0.63 / 1.31 | 0.11 / 0.25 | 0.90 / 2.73 → 0.11 / 0.37 | 3.14 / 6.10 → 0.02 / 0.02 |
| sizes 12, 14, 16, 18, 24, 32 | 12 | 4.83 / 11.23 → 0.73 / 1.53 | 0.17 / 0.30 | 0.45 / 1.88 → 0.10 / 0.32 | 3.60 / 4.67 → 0.01 / 0.02 |
| weights 500, 800 | 6 | 2.06 / 6.78 → 0.99 / 1.67 | 0.09 / 0.12 | 1.07 / 1.64 → 0.13 / 0.14 | 3.05 / 3.24 → 0.02 / 0.02 |
| `letterSpacing` −0.5, 0, 1 | 18 | 5.15 / 11.86 → 0.57 / 1.82 | 0.09 / 0.15 | 1.05 / 3.96 → 0.29 / 1.31 | 3.24 / 6.10 → 0.02 / 0.02 |
| explicit `lineHeight` | 3 | 5.90 / 10.91 → 0.67 / 1.30 | 0.00 / 0.17 | 0.59 / 2.03 → 0.26 / 0.53 | 0.29 / 0.36 → 0.00 / 0.01 |
| paragraphs (2–3 lines, padding off) | 9 | 5.90 / 10.12 → 0.58 / 0.99 | 0.16 / 0.30 | 0.56 / 3.24 → 0.26 / 0.78 | 3.52 / 6.52 → 0.01 / 0.03 |
| default size (14) | 1 | 2.78 → 0.42 | 0.30 | 0.12 → 0.53 | 3.43 → 0.02 |

`backend/tests/test_rn_runtime.py::test_text_lays_out_like_the_device` fails if any category drifts past its limit:

- **iOS.** Width median ≤ 1.25% and max ≤ 2.5%; height ≤ 0.34 pt.
- **Android.** Width median ≤ 0.75% and max ≤ 1.5%; height ≤ 0.05 dp.

Known residuals:

- **iOS width, string to string.** Inter's and SF Pro's glyphs differ individually, so the two sample strings disagree by about 1% at 34 pt. Tracking can only match their average. Predicting one string from the other's fit gives a median error of 1.3% (max 2.6%).
- **Android `letterSpacing`.** Android spaces n − 1 gaps, while CSS (and iOS) add spacing after every character, so the preview is one `letterSpacing` wider.
- **Android text with no `fontWeight`.** It measures up to 3 px (1.1 dp) different from `fontWeight: '400'` at the same size, in either direction, with identical heights. The two presumably resolve to different typeface objects (`Typeface.DEFAULT` vs `Typeface.create(…, 400, false)`); the cause isn't verified. The preview can't tell them apart. The grid sets explicit weights; the `letterSpacing` and default-size samples don't. iOS shows no such difference.
- **iOS block rounding.** The preview is up to 1 device pixel (0.33 pt) shorter per `Text`, not per line.

## Measured on

Measured on 2026-09-24 with Expo Go 57.0.9 (Expo SDK 57, React Native 0.86.3):

- **iOS.** iPhone 17e Simulator, iOS 26.4, 390 × 844 pt at 3×.
- **Android.** Pixel 8 emulator image (`android-36;google_apis_playstore;arm64-v8a`), 1080 × 2400 at 420 dpi (2.625).

Both platforms reproduced the earlier grid run exactly (48 of 48 samples identical).

**Not verified:**

- **Linux Chromium.** Production renders in the backend's Docker image (Linux); the numbers above are from Playwright's Chromium on macOS. Run the test in the image.
- **Real phones and OEM fonts.** Samsung's One UI, for example, doesn't use Roboto.
- **Font scaling.** Dynamic Type and Android font size other than 100%.
- **Other densities.** The rules take the density from the profile, but only 3× and 2.625 were measured.
- **Scripts outside Latin, and emoji.** These fall back to host fonts.

## Re-measuring

1. **Native.** Copy `TextGrid.jsx` to `App.jsx` in an Expo project of the SDK in `../expo-sdk.json`. Its `index.js` should wrap the app in `SafeAreaProvider`, as the export will.
   1. Open it in Expo Go on the Simulator and on the emulator (`npx expo start --ios`, then `--android`).
   2. Metro prints one line per device: `LOG RNCAL {...}`. Save its JSON as `measurements/native-ios.json` or `measurements/native-android.json`.
   3. Metro in CI mode doesn't reload on edits, so restart it after changing the file.
2. **Uncalibrated preview.** From `backend/`, run `poetry run python ../rn-runtime/calibration/measure_web.py --uncalibrated`. This writes `measurements/web-*-uncalibrated.json`.
3. **Fit.** Run `python3 rn-runtime/calibration/fit.py`. It checks the line rules, fits the iOS tracking and writes `fit.json`.
4. **Rebuild and check.** Run `cd rn-runtime && pnpm build`, then `measure_web.py` without flags, then `poetry run pytest tests/test_rn_runtime.py -k text`.

If `fit.py` rejects a height, a platform rule has changed; don't widen the tolerance. Add samples to `TextGrid.jsx` to isolate the change. The Android paragraph and padding rules were found that way.
