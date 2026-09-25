# React Native (Expo) evals

Results for the React Native stack (PLAN.md 5.4 and 5.5). The metrics are described in DESIGN.md §14.1.

**Status: no runs yet.** The harness is built and tested. The screenshots (5.1) and the model runs (5.4 and 5.5) are still to do.

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

Not run.

## Prompt rounds (5.5)

Planned first round: generated screens are about 1.3–1.6x too large (seen in Phase 2). Each round records the change, then the before-and-after tables.

| Round | Prompt change | Commit | SSIM (mean) | Clean render | Fake status bar | Bundles | Cost |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | Baseline | | | | | | |
