"""Derive the preview's text-metric rules from native measurements.

Reads measurements/native-{ios,android}.json (TextGrid.jsx on a device) and
measurements/web-ios-uncalibrated.json (TextGrid.jsx in the preview with the
corrections off), checks the line model against every native sample, and
writes fit.json, which the runtime build bundles (src/text-metrics.js applies
it).

Only iOS tracking is fitted. The rest are platform rules whose constants come
from the fonts; this script fails if any native height disagrees with them:

* iOS: SF Pro tracks size-dependently and Inter doesn't, so tracking (em) per
  size and weight closes the width gap. A line is SF Pro's ascender + descender
  (1950 + 494 of 2048 units, as UIFont reports), and iOS rounds the whole text
  block up to a device pixel.
* Android: React Native renders at ceil(size * density) pixels, which alone
  closes the width gap (Roboto is the real font). Baselines are spaced by
  Roboto's hhea ascent + descent (1900 + 500), each rounded to a pixel;
  includeFontPadding pads the first line up to the bounding box top (yMax 2163)
  and the last line down to its bottom (yMin -555). An explicit lineHeight is
  rounded up to a pixel per line and gets no padding.

Usage (no dependencies): python3 rn-runtime/calibration/fit.py
"""

import json
import math
import re
import statistics
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
SIZES = [11, 13, 15, 17, 20, 22, 28, 34]
WEIGHTS = ["400", "600", "700"]
STRINGS = ["Good morning, Ada", "Hamburgefonstiv 0123"]
DENSITY = {"ios": 3.0, "android": 2.625}  # iPhone 17e, Pixel 8
DEFAULT_FONT_SIZE = 14
UNITS_PER_EM = 2048
SF_PRO = {"ascent": 1950 / UNITS_PER_EM, "descent": 494 / UNITS_PER_EM}
ROBOTO = {
    "ascent": 1900 / UNITS_PER_EM,
    "descent": 500 / UNITS_PER_EM,
    "top": 2163 / UNITS_PER_EM,
    "bottom": 555 / UNITS_PER_EM,
}
TOLERANCE = 0.011  # measurements are logged to 0.01
SAMPLE_ID = re.compile(
    r"^(?:(?P<size>\d+)-(?P<weight>\d+)|default)-(?P<text>\d)"
    r"(?:-ls(?P<letterSpacing>-?[\d.]+))?(?:-lines(?P<lines>\d+))?(?:-lh(?P<lineHeight>[\d.]+))?(?P<nopad>-nopad)?$"
)


def parse(sample_id: str) -> dict[str, Any]:
    """A TextGrid.jsx sample id, e.g. 17-400-0, 13-400-1-ls-0.5, 17-400-0-lines3-lh22, default-0."""
    match = SAMPLE_ID.match(sample_id)
    if not match:
        raise ValueError(f"unknown sample id {sample_id!r}")
    parts = match.groupdict()
    return {
        "size": int(parts["size"]) if parts["size"] else DEFAULT_FONT_SIZE,
        "weight": parts["weight"] or "400",
        "text": STRINGS[int(parts["text"])],
        "letterSpacing": float(parts["letterSpacing"]) if parts["letterSpacing"] else None,
        "lines": int(parts["lines"] or 1),
        "lineHeight": float(parts["lineHeight"]) if parts["lineHeight"] else None,
        "fontPadding": not parts["nopad"],
        "grid": bool(parts["size"]) and int(parts["size"]) in SIZES and parts["weight"] in WEIGHTS and match.end("text") == len(sample_id),
    }


def up(value: float) -> int:
    return math.ceil(value - 1e-9)


def half_up(value: float) -> int:
    """Skia's SkScalarRoundToInt (Python's round() rounds half to even)."""
    return math.floor(value + 0.5)


def native_height(platform: str, sample: dict[str, Any]) -> float:
    """The height the platform rules predict for a sample."""
    density = DENSITY[platform]
    size, lines, line_height = sample["size"], sample["lines"], sample["lineHeight"]
    if platform == "ios":
        line = line_height if line_height is not None else (SF_PRO["ascent"] + SF_PRO["descent"]) * size
        return up(lines * line * density) / density
    px = up(size * density)
    if line_height is not None:
        return lines * up(line_height * density) / density
    spacing = half_up(ROBOTO["ascent"] * px) + half_up(ROBOTO["descent"] * px)
    if not sample["fontPadding"]:
        return lines * spacing / density
    return (up(ROBOTO["top"] * px) + up(ROBOTO["bottom"] * px) + (lines - 1) * spacing) / density


def check_heights(platform: str, native: dict[str, list[float]]) -> None:
    misses = [
        f"{sample_id}: measured {measured[1]}, rules give {native_height(platform, parse(sample_id)):.2f}"
        for sample_id, measured in native.items()
        if abs(native_height(platform, parse(sample_id)) - measured[1]) > TOLERANCE
    ]
    if misses:
        raise SystemExit(f"{platform}: the line rules don't reproduce these heights:\n  " + "\n  ".join(misses))
    print(f"{platform}: line rules reproduce all {len(native)} measured heights")


def ios_tracking(native: dict[str, list[float]], web: dict[str, list[float]]) -> dict[str, Any]:
    """Letter-spacing (em) per size and weight that makes the preview's widths native."""

    def needed(size: int, weight: str) -> float:
        values = [
            (native[f"{size}-{weight}-{index}"][0] - web[f"{size}-{weight}-{index}"][0]) / (len(text) * size)
            for index, text in enumerate(STRINGS)
        ]
        return round(statistics.mean(values), 4)

    return {"sizes": SIZES, "byWeight": {weight: [needed(size, weight) for size in SIZES] for weight in WEIGHTS}}


def load(name: str) -> dict[str, list[float]]:
    return json.loads((HERE / "measurements" / name).read_text())


def main() -> None:
    native_ios, native_android = load("native-ios.json"), load("native-android.json")
    check_heights("ios", native_ios)
    check_heights("android", native_android)
    fit: dict[str, Any] = {
        "$comment": "Generated by fit.py from measurements/; bundled into the runtime by build.mjs. See README.md.",
        "ios": {**SF_PRO, "tracking": ios_tracking(native_ios, load("web-ios-uncalibrated.json"))},
        "android": ROBOTO,
    }
    (HERE / "fit.json").write_text(json.dumps(fit, indent=2) + "\n")
    print(json.dumps(fit["ios"]["tracking"]["byWeight"]), file=sys.stderr)


if __name__ == "__main__":
    main()
