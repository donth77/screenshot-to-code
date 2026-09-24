"""Measure TextGrid.jsx in the preview, with or without the text-metric corrections.

Run from backend/ (it uses the backend's renderer and Playwright):

    poetry run python ../rn-runtime/calibration/measure_web.py --uncalibrated   # inputs for fit.py
    poetry run python ../rn-runtime/calibration/measure_web.py                  # check the rules

Uncalibrated runs write measurements/web-<platform>-uncalibrated.json. Every run
prints how far the preview is from the native measurements, per category of
sample: "grid" is what fit.py fits to; the rest were held out.
"""

import argparse
import asyncio
import json
import statistics
import sys
from pathlib import Path
from typing import Any, cast

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "backend"))
sys.path.insert(0, str(HERE))

from fit import parse  # noqa: E402  # pyright: ignore[reportMissingImports, reportUnknownVariableType] (a sibling script; sys.path above)
from preview_screenshot.playwright_backend import PlaywrightBackend  # noqa: E402
from react_native.render import render_preview  # noqa: E402
from react_native.runtime_files import load_runtime  # noqa: E402

NO_INSETS = {"top": 0, "right": 0, "bottom": 0, "left": 0}
# The densities the native measurements were taken at (iPhone 17e, Pixel 8).
PROFILES: dict[str, dict[str, Any]] = {
    "ios": {"platform": "ios", "width": 390, "height": 844, "scale": 3, "insets": NO_INSETS},
    "android": {"platform": "android", "width": 411, "height": 914, "scale": 2.625, "insets": NO_INSETS},
}
CATEGORIES = ["grid", "sizes", "weights", "letterSpacing", "lineHeight", "paragraphs", "default"]

# react-native-web's onLayout reports offsetWidth/offsetHeight, which are whole CSS
# pixels; read the exact box from the DOM instead (native onLayout is fractional).
READ_GRID_JS = """async () => {
  await document.fonts.ready;
  return Object.fromEntries(
    Array.from(document.querySelectorAll('[data-testid^="cal-"]')).map((el) => {
      const rect = el.getBoundingClientRect();
      return [el.getAttribute('data-testid').slice(4), [Math.round(rect.width * 100) / 100, Math.round(rect.height * 100) / 100]];
    })
  );
}"""


async def read_grid(page: Any) -> dict[str, Any]:
    return await page.evaluate(READ_GRID_JS)


def category(sample_id: str) -> str:
    sample = cast(dict[str, Any], parse(sample_id))
    if sample["grid"]:
        return "grid"
    if sample_id.startswith("default"):
        return "default"
    if sample["lines"] > 1 or not sample["fontPadding"]:
        return "paragraphs"
    if sample["lineHeight"] is not None:
        return "lineHeight"
    if sample["letterSpacing"] is not None:
        return "letterSpacing"
    return "weights" if sample["weight"] not in ("400", "600", "700") else "sizes"


def compare(web: dict[str, list[float]], native: dict[str, list[float]]) -> dict[str, dict[str, float]]:
    """Width error (%) and height error (pt / dp) per category of sample."""
    missing = sorted(set(native) - set(web))
    if missing:
        raise ValueError(f"the preview didn't render {missing}")
    stats: dict[str, dict[str, float]] = {}
    for name in CATEGORIES:
        keys = [key for key in native if category(key) == name]
        width = [abs(web[key][0] / native[key][0] - 1) * 100 for key in keys]
        height = [abs(web[key][1] - native[key][1]) for key in keys]
        stats[name] = {
            "samples": len(keys),
            "width_median_pct": round(statistics.median(width), 2),
            "width_max_pct": round(max(width), 2),
            "height_median": round(statistics.median(height), 2),
            "height_max": round(max(height), 2),
        }
    return stats


async def measure(calibrated: bool) -> dict[str, dict[str, list[float]]]:
    bundle = load_runtime()
    if bundle is None:
        raise SystemExit("rn-runtime is not built (cd rn-runtime && pnpm build)")
    source = (HERE / "TextGrid.jsx").read_text()
    backend = PlaywrightBackend()
    browser = await backend._get_browser()  # pyright: ignore[reportPrivateUsage]
    results: dict[str, dict[str, list[float]]] = {}
    try:
        for platform, profile in PROFILES.items():
            render = await render_preview(browser, bundle, source, {**profile, "textMetrics": calibrated}, inspect=read_grid)
            results[platform] = render.extra
    finally:
        await browser.close()
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--uncalibrated", action="store_true", help="measure with corrections off and save for fit.py")
    args = parser.parse_args()
    results = asyncio.run(measure(calibrated=not args.uncalibrated))
    for platform, web in results.items():
        native = json.loads((HERE / "measurements" / f"native-{platform}.json").read_text())
        print(f"{platform} {'uncalibrated' if args.uncalibrated else 'calibrated'}")
        print(f"  {'category':14}{'n':>4}{'width med %':>13}{'max %':>8}{'height med':>12}{'max':>7}")
        for name, row in compare(web, native).items():
            print(
                f"  {name:14}{row['samples']:>4}{row['width_median_pct']:>13.2f}{row['width_max_pct']:>8.2f}"
                f"{row['height_median']:>12.2f}{row['height_max']:>7.2f}"
            )
        if args.uncalibrated:
            path = HERE / "measurements" / f"web-{platform}-uncalibrated.json"
            path.write_text(json.dumps(web) + "\n")


if __name__ == "__main__":
    main()
