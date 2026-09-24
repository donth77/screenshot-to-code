"""Device detection shared with the frontend.

rn-runtime/test-vectors/device-detection.json records what
react_native/profiles.py decides for a set of screenshot sizes and overrides.
frontend/src/lib/react-native/devices.test.ts runs the same vectors against
the TypeScript port, so the phone the UI previews is the phone the backend
prompts for and screenshots.

Regenerate the vectors after a deliberate change to the detection rules or the
device table:
    cd backend && poetry run python tests/test_rn_device_detection.py --write
"""

import json
import sys
from pathlib import Path
from typing import Any, Mapping, Optional, cast

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from react_native.profiles import DeviceProfile, Platform, apply_overrides, default_device, detect_device  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
TABLE_PATH = ROOT / "rn-runtime" / "device-profiles.json"
VECTORS_PATH = ROOT / "rn-runtime" / "test-vectors" / "device-detection.json"

# (name, pixel width, pixel height, overrides). A size of None is a
# generation without a screenshot (text mode). The platform override is also
# the detection hint, as in the backend. Expected values come from Python.
CASES: list[tuple[str, Optional[int], Optional[int], Optional[dict[str, Any]]]] = [
    ("iPhone 13 exact", 1170, 2532, None),
    ("iPhone 15 exact", 1179, 2556, None),
    ("iPhone 17 exact", 1206, 2622, None),
    ("iPhone 14 Plus exact", 1284, 2778, None),
    ("iPhone 15 Pro Max exact", 1290, 2796, None),
    ("iPhone 17 Pro Max exact", 1320, 2868, None),
    ("iPhone 11 Pro exact", 1125, 2436, None),
    ("iPhone 13 mini exact", 1080, 2340, None),
    ("iPhone 11 exact", 828, 1792, None),
    ("iPhone SE exact", 750, 1334, None),
    ("Pixel 8 exact", 1080, 2400, None),
    ("Pixel 8 Pro exact (insets unknown)", 1344, 2992, None),
    ("iPhone 15 at half size", 590, 1278, None),
    ("iPhone 15 at 1x", 393, 852, None),
    ("Pixel 8 at half size", 540, 1200, None),
    ("unknown iPhone shape (XS Max)", 1242, 2688, None),
    ("unknown tall Android", 1000, 2000, None),
    ("unknown width that is an iPhone at 3x", 1125, 2000, None),
    ("landscape iPhone is guessed", 2532, 1170, None),
    ("tiny image", 40, 90, None),
    ("Pixel 8 size, told it is an iPhone", 1080, 2400, {"platform": "ios"}),
    ("iPhone size, told it is an Android phone", 1170, 2532, {"platform": "android"}),
        ("logical width override", 1170, 2532, {"logicalWidth": 393}),
    ("inset overrides", 1080, 2400, {"insetTop": 40, "insetBottom": 0}),
    ("fractional inset overrides", 1080, 2400, {"insetTop": 24.5, "insetBottom": 15.75}),
    ("all overrides", 1179, 2556, {"platform": "ios", "logicalWidth": 402, "insetTop": 62, "insetBottom": 34}),
    ("inset rounding half to even (2.5 px)", 750, 1334, {"insetTop": 1.25}),
    ("inset rounding half to even (3.5 px)", 750, 1334, {"insetTop": 1.75}),
    ("content height rounding half to even", 750, 1334, {"insetTop": 0.5}),
    ("out-of-range overrides are ignored", 1170, 2532, {"logicalWidth": 50, "insetTop": 500, "insetBottom": -1}),
    ("non-numeric overrides are ignored", 1170, 2532, {"logicalWidth": "393", "insetTop": True, "platform": "web"}),
    ("text mode, iOS", None, None, None),
    ("text mode, Android", None, None, {"platform": "android"}),
    ("text mode, unknown platform falls back to iOS", None, None, {"platform": "windows"}),
    ("text mode with inset overrides", None, None, {"platform": "android", "insetTop": 30}),
]


def load_table() -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(TABLE_PATH.read_text(encoding="utf-8")))


def resolve(
    table: Mapping[str, Any],
    pixel_width: Optional[int],
    pixel_height: Optional[int],
    overrides: Optional[Mapping[str, Any]],
) -> DeviceProfile:
    """What the backend does for a request (react_native/inputs.py and profiles.read_screenshot)."""
    overrides = overrides or {}
    platform = overrides.get("platform")
    if pixel_width is None or pixel_height is None:
        text_platform: Platform = "android" if platform == "android" else "ios"
        return apply_overrides(default_device(table, text_platform), overrides, table)
    device = detect_device(pixel_width, pixel_height, table, cast(Platform, platform) if platform in ("ios", "android") else None)
    return apply_overrides(device, overrides, table)


def describe(device: DeviceProfile) -> dict[str, Any]:
    return {
        "platform": device.platform,
        "name": device.name,
        "logicalWidth": device.logical_width,
        "scale": device.scale,
        "insetTop": device.inset_top,
        "insetBottom": device.inset_bottom,
        "pixelWidth": device.pixel_width,
        "pixelHeight": device.pixel_height,
        "match": device.match,
        "cropTopPx": device.crop_top_px,
        "cropBottomPx": device.crop_bottom_px,
        "contentHeight": device.content_height,
        "previewProfile": device.preview_profile(),
    }


def build_vectors(table: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "$comment": (
            "Shared by backend/tests/test_rn_device_detection.py and "
            "frontend/src/lib/react-native/devices.test.ts. Expected values come from "
            "backend/react_native/profiles.py and rn-runtime/device-profiles.json; "
            "regenerate with: cd backend && poetry run python tests/test_rn_device_detection.py --write"
        ),
        "cases": [
            {
                "name": name,
                "pixelWidth": width,
                "pixelHeight": height,
                "overrides": overrides,
                "expected": describe(resolve(table, width, height, overrides)),
            }
            for name, width, height, overrides in CASES
        ],
    }


VECTORS: dict[str, Any] = json.loads(VECTORS_PATH.read_text(encoding="utf-8")) if VECTORS_PATH.exists() else {"cases": []}


def test_the_vectors_are_current() -> None:
    assert VECTORS == build_vectors(load_table()), "regenerate: poetry run python tests/test_rn_device_detection.py --write"


@pytest.mark.parametrize("case", VECTORS["cases"], ids=[str(case["name"]) for case in VECTORS["cases"]])
def test_detection_matches_the_shared_vectors(case: dict[str, Any]) -> None:
    device = resolve(load_table(), case["pixelWidth"], case["pixelHeight"], case["overrides"])
    assert describe(device) == case["expected"]


if __name__ == "__main__":
    if "--write" not in sys.argv:
        sys.exit("usage: python tests/test_rn_device_detection.py --write")
    VECTORS_PATH.write_text(json.dumps(build_vectors(load_table()), indent=2) + "\n", encoding="utf-8")
    print(f"wrote {VECTORS_PATH}")
