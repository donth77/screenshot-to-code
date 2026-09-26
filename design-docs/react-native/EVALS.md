# React Native (Expo) evals

Results for the React Native stack (PLAN.md 5.4 and 5.5). The metrics are described in DESIGN.md §14.1.

**Status:** the full-set baseline (5.4) is done: mean SSIM 0.644 across 30 screenshots, and every output renders cleanly and bundles for iOS and Android. Two prompt rounds ran earlier on a 5-screenshot interim set (at the end); the next rounds run on the full set.

## The eval set (5.1)

`react-native`: 30 screenshots, listed with their source and licence in `backend/evals/react_native_set.json`. The images live in the gitignored `evals_data/sets/react-native/inputs/`.

- **Own captures (16).**
  - 9 iPhone 17e Simulator screens (iOS 26.4, status bar pinned to 9:41): Settings (light and dark), Contacts, Files, Photos, Shortcuts, the Reminders and Health welcome screens, and a Messages compose sheet.
  - 7 Pixel 8 emulator screens (Android 16, demo-mode status bar): Settings (dark), Clock, a Messages chat and the Create contact form, plus three long screens (Settings, the apps list, the contact form).
  - The long screens were laid out on a 1080 x 4200 display (`adb shell wm size`), not stitched.
  - Licence: Apple's and Google's app UIs, for internal evaluation only and not redistributed. Android Settings is AOSP (Apache-2.0).
- **Open-source apps' published screenshots (14).** From their F-Droid listings under each app's licence: Tusky, Feeder, Catima, Breezy Weather, Loop Habit Tracker, NewPipe, Fossify Contacts and Notes, KeePassDX and Conversations (GPL-3.0 and LGPL-3.0).
  - Marketing images (framed devices with captions) were left out. Four device mockups without captions got in (Feeder's two and Tusky's two); the baseline run exposed them, and they're now cropped to their screens.
  - Eight had their system bars cropped off by hand, the four mockups among them: at their screen size, the device table would take them for a different phone or crop bars of a different height. The manifest's notes say how each was cropped. The rest keep their bars and exercise the unknown-device path.
- **Coverage:** 9 iOS and 21 Android; 18 light and 12 dark; every category (lists and feeds 10, forms 5, tab bars 5, settings 5, cards 4, onboarding 3, chat 2); 3 long.
- **Detection:** the platform is right for all 30. The 16 exact-device captures are cropped by the table's insets, which the manifest records and the checker verifies. Everything else is a guessed Android phone with no crop.
- **Found while sourcing:** detection took 16:9 Android screenshots (1080 x 1920) for scaled iPhone SEs; fixed in `a33f3a4`.

## How to run

1. **Add the screenshots.**
   - Put them in `backend/evals_data/sets/react-native/inputs/`.
   - List them in `backend/evals/react_native_set.json`.
   - Then run:

     ```bash
     cd backend
     poetry run python -m evals.react_native_set --write-hashes --strict
     ```
2. **Generate.** Run from the evals UI (stack `react_native`, set `react-native`) or call `run_image_evals(stack="react_native", model=…, eval_set="react-native")`.
   - Set `PROMPT_REPORTS_ENABLED=true` for iterations, latency and cost.
   - Set `RN_BUNDLE_CHECK=1` for the RNW-6 bundle rate. It adds about 10–40 s per output.
   - Each output gets `<name>_<n>.metrics.json`.
3. **Report.**

   ```bash
   poetry run python -m evals.react_native_metrics "evals_data/results/<run folder>" --inputs evals_data/sets/react-native/inputs
   ```

   This writes `report.md` into the folder. Paste its table below with the model, date, commit and prompt change.

Record the renderer's font hinting with each run. The Linux default fails the text-width calibration (DESIGN §8.3, §17.7), and that shifts SSIM.

## Baseline (5.4)

- **Set:** `react-native`, all 30 screenshots.
- **Model:** `claude-opus-4-8 (medium effort)`, the app's first create model for OpenAI + Anthropic keys. One output per screenshot.
- **Prompt:** as of interim round 2 (`04f37d9`); run at `19ea88c`.
- **Renderer:** Playwright's Chromium on macOS, whose text passes the calibration (no hinting flag needed).
- **Bundling (RNW-6):** each output bundled after the run with `python -m react_native.bundle_check`, on macOS: 12 s median.
- **Recording:** `PROMPT_REPORTS_ENABLED=1`, with `LOGS_PATH` under `evals_data`.
- **Load:** 6 screenshots at a time. `run_image_evals` starts them all at once, which risks rate limits with 30 agents.
- **Date:** 2026-09-26. Spend: $8.93, including four outputs replaced after their inputs were cropped (below).

| Metric | Value |
| --- | --- |
| SSIM (higher is better) | 0.644 mean, 0.643 median (0.414–0.870) |
| Mean abs. pixel diff (lower is better) | 0.106 mean |
| Clean render (ok, no errors) | 100% (30/30) |
| Fake status bar | 0% (0/30) |
| Unknown imports, icons or react-native exports | 0% (0/30) |
| Native-compat lint findings | 0% (0/30) |
| Bundles for iOS and Android (RNW-6) | 100% (30/30) |
| screenshot_preview iterations | 1.6 mean (1–3) |
| LLM calls | 4.9 mean (3–8) |
| Latency | 56 s mean, 49 s median (26–128 s) |
| Cost | $7.95 total, $0.27 mean |

Mean SSIM by group (a screenshot can be in more than one category):

| Group | Screenshots | SSIM |
| --- | --- | --- |
| iOS | 9 | 0.654 |
| Android | 21 | 0.641 |
| Light | 18 | 0.673 |
| Dark | 12 | 0.602 |
| Own captures | 16 | 0.691 |
| F-Droid screenshots | 14 | 0.591 |
| Long screens | 3 | 0.732 |
| Tab bars | 5 | 0.715 |
| Forms | 5 | 0.714 |
| Onboarding | 3 | 0.659 |
| Chat | 2 | 0.657 |
| Settings | 5 | 0.647 |
| Cards | 4 | 0.606 |
| Lists and feeds | 10 | 0.590 |

- **Everything runs.** All 30 outputs render without errors, draw no status bar of their own, use only known imports and icons, and bundle for iOS and Android. That is RNW-6 on live-model output.
- **Oversizing is still the main failure.** Text, rows and icons come out larger than the input on most of the low scorers: Catima's form (0.444), Tusky's timeline (0.451), iOS Settings in dark mode (0.474), the Health welcome screen (0.515). Round 2's side-by-side check reduced it on the interim set but hasn't removed it.
- **Photos become drawings.** Evals run without image generation, so photos (Feeder's article images, Tusky's photo, NewPipe's thumbnails, the Photos grid) come out as shapes or flat colour. That caps SSIM on feeds and cards, and is most of why the F-Droid screenshots, which have more photos, score below the own captures. It affects every round equally.
- **Dark screens score lower** (0.602 against 0.673). Not looked into yet.
- **Single screens are noisy.** Four iOS screenshots are the same files as in the interim set, run with the same prompt. Three scored within 0.03 of interim round 2; Settings in dark mode fell from 0.615 to 0.474. Judge rounds on the set's mean, not on single screens.
- **Four inputs were device mockups.** Feeder's and Tusky's F-Droid screenshots are pictures of a phone: the screen sits inside a bezel, shrunk and shifted, so correct edge-to-edge output scored badly. Cropped to the screen and re-run: Feeder light 0.285 → 0.414, Feeder dark 0.235 → 0.482, Tusky login 0.714 → 0.831, Tusky timeline 0.414 → 0.451. The mean went from 0.627 to 0.644. The first outputs are kept in the results folder's `replaced/`.

<details>
<summary>SSIM per screenshot</summary>

| Screenshot | SSIM | Pixel diff | Iterations |
| --- | --- | --- | --- |
| android-clock-dark | 0.870 | 0.055 | 1 |
| ios-files-recents-light | 0.870 | 0.042 | 1 |
| android-tusky-login-dark | 0.831 | 0.062 | 2 |
| ios-contacts-light | 0.826 | 0.030 | 2 |
| android-contacts-create-long-light | 0.798 | 0.047 | 1 |
| android-fossify-notes-settings-light | 0.786 | 0.060 | 1 |
| ios-messages-compose-light | 0.786 | 0.074 | 1 |
| android-messages-chat-light | 0.767 | 0.054 | 1 |
| android-contacts-create-light | 0.713 | 0.050 | 2 |
| android-fossify-contacts-tabs-light | 0.709 | 0.122 | 1 |
| android-apps-long-dark | 0.706 | 0.104 | 1 |
| android-breezy-weather-light | 0.694 | 0.097 | 2 |
| android-settings-long-light | 0.690 | 0.074 | 1 |
| android-keepassdx-list-dark | 0.658 | 0.066 | 3 |
| ios-settings-light | 0.655 | 0.072 | 2 |
| android-settings-dark | 0.631 | 0.087 | 2 |
| ios-reminders-welcome-light | 0.631 | 0.077 | 2 |
| android-catima-cards-light | 0.600 | 0.171 | 2 |
| android-loop-habits-light | 0.600 | 0.104 | 1 |
| android-breezy-weather-dark | 0.586 | 0.137 | 2 |
| ios-photos-light | 0.580 | 0.154 | 1 |
| android-conversations-chat-light | 0.547 | 0.166 | 2 |
| ios-shortcuts-dark | 0.544 | 0.074 | 1 |
| ios-health-welcome-dark | 0.515 | 0.123 | 1 |
| android-feeder-list-dark | 0.482 | 0.200 | 2 |
| android-newpipe-feed-dark | 0.475 | 0.140 | 2 |
| ios-settings-dark | 0.474 | 0.092 | 2 |
| android-tusky-timeline-dark | 0.451 | 0.169 | 2 |
| android-catima-add-card-light | 0.444 | 0.212 | 2 |
| android-feeder-list-light | 0.414 | 0.271 | 2 |

</details>

## Prompt rounds (5.5)

| Round | Change | Commit | SSIM (mean) | Pixel diff | Clean render | Fake status bar | Bundles | Iterations | Latency | Cost |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | Baseline: interim round 2's prompt | `19ea88c` | 0.644 | 0.106 | 30/30 | 0/30 | 30/30 | 1.6 | 56 s | $7.95 |
| 3 | Guide lines every 50 pt across the comparison, a measuring step, and no space left for system bars | `5361a6a` | 0.653 | 0.102 | 30/30 | 0/30 | 30/30 | 1.9 | 65 s | $9.08 |

Rounds are compared screen by screen: the change in each screen's SSIM, averaged, with its standard error.

- **Round 3** added guide lines to the comparison image, and asked the model to measure where the title, the first row, the last fully visible element and any bottom bar start in both, fixing anything more than about 8 off. Over all 30 screens, SSIM rose 0.009 ± 0.008: within noise.
  - On the 24 screens from phones in the device table or with their bars cropped, it rose 0.014 ± 0.009 (12 better, 5 worse). The screens whose problem was position improved most: the Health welcome screen +0.165, Shortcuts +0.064, iOS Settings in dark mode +0.056. Their titles and rows now start where the input's do.
  - The six unknown phones that keep their system bars lost 0.012 (below).
  - The other losses look like run-to-run variation: different placeholder drawings for photos, and rows drifting a few points.
  - The model checks more (1.9 screenshots, 5.6 LLM calls), so each screen costs 14% more and takes 16% longer.
  - Kept: it fixes the failure it targets, and leaving the system bars to SafeAreaView is right regardless.
- **Found: unknown phones render shifted.** A screenshot from a phone that isn't in the device table keeps its system bars, but renders with zero insets, so the app starts where the status bar is and everything sits one status bar too high. At baseline the six such screens averaged 0.567 SSIM against 0.664 for the rest, and in round 3 the comparison showed the model an offset it was told to ignore. Fix: detect the bars on unknown phones and crop them as for known phones.

## Interim runs (5 screenshots)

These ran before the full set was chosen. They found the oversizing and tried two fixes.

### Setup

- **Set:** `rn-gate`, the five Phase 2 gate screenshots (in the gitignored `evals_data/sets/rn-gate/inputs/`). They are four iPhone 17e Simulator screens (Contacts, Files, the Reminders welcome screen, Settings in dark mode) and the Pixel 8 capture of this repo's test fixture. That's too few to tell differences under about ±0.02 SSIM from noise: the Phase 2 run of the same prompt scored 0.694, the baseline below 0.681.
- **Model:** `claude-opus-4-8 (medium effort)`, the app's first create model for OpenAI + Anthropic keys. One output per screenshot.
- **Renderer:** Playwright's Chromium on macOS, whose text passes the calibration (no hinting flag needed).
- **Recording:** `PROMPT_REPORTS_ENABLED=1`, with `LOGS_PATH` under `evals_data` so the run logs stay gitignored.
- **Date:** 2026-09-26.

### Baseline (5.4)

Run at `138f064`; the React Native prompt was unchanged since Phase 2.

| Metric | Value |
| --- | --- |
| SSIM (higher is better) | 0.681 mean, 0.689 median (0.553–0.839) |
| Mean abs. pixel diff (lower is better) | 0.072 mean |
| Clean render (ok, no errors) | 100% (5/5) |
| Fake status bar | 0% (0/5) |
| screenshot_preview iterations | 1.6 mean (1–3) |
| LLM calls | 4.6 mean (3–8) |
| Latency | 43 s mean |
| Cost | $1.12 total, $0.22 mean |

The main failure is size: text, rows and icons are drawn about 1.3–1.6x too large (Contacts names at fontSize 26 where iOS uses 17). The renders use the right profile, so the model oversizes. Where it knows a platform standard it gets close (Settings: 18 for 17, 36 for 34).

### Prompt rounds (5.5)

| Round | Change | Commit | SSIM (mean) | Pixel diff | Clean render | Fake status bar | Bundles | Iterations | Latency | Cost |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | Baseline | `138f064` | 0.681 | 0.072 | 5/5 | 0/5 | not checked | 1.6 | 43 s | $1.12 |
| 1 | Sizing by comparison with iOS and Android standard sizes; a same-size check in the screenshot step | `fbf29e3` | 0.689 | 0.069 | 5/5 | 0/5 | not checked | 1.2 | 40 s | $0.99 |
| 2 | `screenshot_preview` also returns the input and the render side by side at the same scale | `04f37d9` | **0.724** | **0.054** | 5/5 | 0/5 | not checked | 1.8 | 62 s | $1.49 |

SSIM per screenshot:

| Input | Round 0 | Round 1 | Round 2 |
| --- | --- | --- | --- |
| android-pixel8-fixture | 0.689 | 0.697 | 0.711 |
| ios-contacts | 0.764 | 0.751 | 0.801 |
| ios-files-recents | 0.839 | 0.878 | 0.884 |
| ios-reminders-welcome | 0.559 | 0.559 | 0.609 |
| ios-settings-dark | 0.553 | 0.561 | 0.615 |

- **Round 1** moved the sizes the model knows toward the standards (large titles from 40 to 34 on Files and Settings; Contacts body text to 17–18). Rows, avatars and spacing stayed large, and SSIM moved within noise. Kept: it points the right way and cost a little less.
- **Round 2** fixed most of the oversizing. Every screenshot improved on the baseline, the mean by 0.043 SSIM, and the pixel difference fell by a quarter. Contacts now shows all seven contacts, as the input does; Settings uses 17 and 34, the Android fixture 15–16 and 22 (the fixture's own 15 and 22). The model iterates more (1.8 screenshots, 5.4 LLM calls), so each screen costs 33% more and takes 45% longer.
- **Still open:** Android and the Reminders body text are still a little large. The next rounds belong on the full set, where differences this size can be told from noise.
