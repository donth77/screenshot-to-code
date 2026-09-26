# React Native (Expo) evals

Results for the React Native stack (PLAN.md 5.4 and 5.5). The metrics are described in DESIGN.md §14.1.

**Status: interim.** A baseline and two prompt rounds ran on a 5-screenshot interim set (below). The full set (5.1: 25–30 screenshots) is still to choose, and every number here should be re-run on it.

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

## Setup for the interim runs

- **Set:** `rn-gate`, the five Phase 2 gate screenshots (in the gitignored `evals_data/sets/rn-gate/inputs/`). They are four iPhone 17e Simulator screens (Contacts, Files, the Reminders welcome screen, Settings in dark mode) and the Pixel 8 capture of this repo's test fixture. That's too few to tell differences under about ±0.02 SSIM from noise: the Phase 2 run of the same prompt scored 0.694, the baseline below 0.681.
- **Model:** `claude-opus-4-8 (medium effort)`, the app's first create model for OpenAI + Anthropic keys. One output per screenshot.
- **Renderer:** Playwright's Chromium on macOS, whose text passes the calibration (no hinting flag needed).
- **Recording:** `PROMPT_REPORTS_ENABLED=1`, with `LOGS_PATH` under `evals_data` so the run logs stay gitignored.
- **Date:** 2026-09-26.

## Baseline (5.4, interim)

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

## Prompt rounds (5.5)

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
