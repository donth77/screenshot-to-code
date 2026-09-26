"""System bars read off screenshots from phones that aren't in the device table.

rn-runtime/test-vectors/system-bars.json records what
react_native/profiles.py's detect_system_bars finds in synthetic screens:
rectangles of luminance standing in for the clock, status icons, a gesture
pill, navigation buttons and app content. frontend/src/lib/react-native/
systemBars.test.ts draws the same screens and runs the TypeScript port, so the
crop the UI shows is the crop the backend makes.

Regenerate the vectors after a deliberate change to the detection rules:
    cd backend && poetry run python tests/test_rn_system_bars.py --write
"""

import json
import random
import sys
from pathlib import Path
from typing import Any, Mapping

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from react_native.profiles import (  # noqa: E402
    SystemBars,
    detect_device,
    detect_system_bars,
    read_screenshot,
)

ROOT = Path(__file__).resolve().parents[2]
TABLE_PATH = ROOT / "rn-runtime" / "device-profiles.json"
VECTORS_PATH = ROOT / "rn-runtime" / "test-vectors" / "system-bars.json"

W, H = 1080, 2280  # a size no phone in the table has
SCALE = W / 412  # the table's Android fallback width
LIGHT, DARK, INK = 245, 24, 60

# The bars' parts, as [x, y, width, height, luminance] rectangles.
CLOCK = [60, 44, 110, 34, INK]  # a status bar 44 + 77 + 1 = 122 px tall
ICONS = [[870, 46, 40, 30, INK], [930, 46, 40, 30, INK], [990, 44, 40, 34, INK]]
PILL = [405, H - 34, 270, 10, INK]  # a gesture bar 2 x 29 = 58 px tall
BUTTONS = [[250, H - 86, 40, 40, INK], [520, H - 86, 40, 40, INK], [790, H - 86, 40, 40, INK]]  # 2 x 66 = 132 px
APP_BAR = [[40, 50, 64, 64, INK], [150, 62, 320, 40, INK], [976, 50, 64, 64, INK]]  # icons 24 dp tall
CONTENT = [[40, 300, 1000, 120, 200], [40, 460, 1000, 120, 200], [40, 620, 700, 40, INK]]
TO_THE_BOTTOM = [[40, 1800, 1000, H - 1800, 200], [80, H - 56, 600, 14, INK]]  # a card with text, under the pill


def on(background: int, *parts: Any) -> list[list[int]]:
    rects: list[list[int]] = []
    for part in parts:
        rects.extend(part if isinstance(part[0], list) else [part])
    return [[background, 0, 0, 0, 0]] + rects  # the first entry is the fill


def dark(rects: list[list[int]]) -> list[list[int]]:
    return [[DARK, *rects[0][1:]]] + [[x, y, w, h, 255 - lum] for x, y, w, h, lum in rects[1:]]


# (name, width, height, scale, [fill, rects...]). Expected values come from Python.
SCENES: list[tuple[str, int, int, float, list[list[int]]]] = [
    ("status bar and gesture pill", W, H, SCALE, on(LIGHT, CLOCK, ICONS, PILL, CONTENT)),
    ("status bar and three buttons", W, H, SCALE, on(LIGHT, CLOCK, ICONS, BUTTONS, CONTENT)),
    ("dark status bar and gesture pill", W, H, SCALE, dark(on(LIGHT, CLOCK, ICONS, PILL, CONTENT))),
    ("status bar only", W, H, SCALE, on(LIGHT, CLOCK, ICONS, CONTENT)),
    ("app bar at the top is not a status bar", W, H, SCALE, on(LIGHT, APP_BAR, CONTENT)),
    ("clock without icons is not a status bar", W, H, SCALE, on(LIGHT, CLOCK, PILL, CONTENT)),
    ("pill over content is left alone", W, H, SCALE, on(LIGHT, CLOCK, ICONS, CONTENT, TO_THE_BOTTOM, PILL)),
    ("status bar glyphs at the very top are not a status bar", W, H, SCALE, on(LIGHT, [60, 0, 110, 34, INK], [990, 0, 40, 34, INK], CONTENT)),
    ("no bars in a short image", W, 400, SCALE, on(LIGHT, CLOCK, ICONS, [405, 366, 270, 10, INK])),
    ("blank screen", W, H, SCALE, on(LIGHT)),
    ("status bar at another scale", 720, 1560, 720 / 412, on(LIGHT, [40, 29, 73, 23, INK], [660, 30, 27, 21, INK], [285, 1537, 150, 7, INK])),
]

# Pillow's RGB to L, which the TypeScript port reproduces.
random.seed(7)
RGB_SAMPLES: list[tuple[int, int, int]] = [(0, 0, 0), (255, 255, 255), (255, 0, 0), (0, 255, 0), (0, 0, 255), (128, 128, 128)] + [
    (random.randrange(256), random.randrange(256), random.randrange(256)) for _ in range(24)
]


def draw(width: int, height: int, spec: list[list[int]]) -> Image.Image:
    image = Image.new("L", (width, height), spec[0][0])
    pen = ImageDraw.Draw(image)
    for x, y, w, h, lum in spec[1:]:
        pen.rectangle((x, y, x + w - 1, y + h - 1), fill=lum)
    return image


def luminance_samples() -> list[list[int]]:
    image = Image.frombytes("RGB", (len(RGB_SAMPLES), 1), bytes(value for rgb in RGB_SAMPLES for value in rgb))
    return [[*rgb, level] for rgb, level in zip(RGB_SAMPLES, image.convert("L").tobytes())]


def vectors() -> dict[str, Any]:
    cases = []
    for name, width, height, scale, spec in SCENES:
        bars = detect_system_bars(draw(width, height, spec), scale)
        cases.append(
            {
                "name": name,
                "width": width,
                "height": height,
                "scale": scale,
                "fill": spec[0][0],
                "rects": spec[1:],
                "expected": {"topPx": bars.top_px, "bottomPx": bars.bottom_px},
            }
        )
    return {
        "$comment": (
            "Shared by backend/tests/test_rn_system_bars.py and frontend/src/lib/react-native/systemBars.test.ts. "
            "Each case is a screen of luminance: `fill`, then `rects` ([x, y, width, height, luminance]) drawn in order. "
            "Expected values come from backend/react_native/profiles.py; regenerate with: "
            "cd backend && poetry run python tests/test_rn_system_bars.py --write"
        ),
        "luminance": luminance_samples(),
        "cases": cases,
    }


def test_vectors_match_the_detector() -> None:
    assert json.loads(VECTORS_PATH.read_text()) == vectors()


def test_the_scenes_find_what_they_were_drawn_with() -> None:
    found = {case["name"]: case["expected"] for case in vectors()["cases"]}
    assert found["status bar and gesture pill"] == {"topPx": 122, "bottomPx": 58}
    assert found["status bar and three buttons"] == {"topPx": 122, "bottomPx": 132}
    assert found["dark status bar and gesture pill"] == {"topPx": 122, "bottomPx": 58}
    assert found["status bar only"] == {"topPx": 122, "bottomPx": 0}
    for name in (
        "app bar at the top is not a status bar",
        "clock without icons is not a status bar",
        "status bar glyphs at the very top are not a status bar",
        "no bars in a short image",
        "blank screen",
    ):
        assert found[name]["topPx"] == 0, name
    assert found["clock without icons is not a status bar"]["bottomPx"] == 58
    assert found["pill over content is left alone"] == {"topPx": 122, "bottomPx": 0}
    assert found["no bars in a short image"] == {"topPx": 0, "bottomPx": 0}
    assert found["status bar at another scale"]["topPx"] == 29 + 51 + 1


def table() -> Mapping[str, Any]:
    return json.loads(TABLE_PATH.read_text())


def scene(name: str) -> Image.Image:
    _, width, height, _, spec = next(s for s in SCENES if s[0] == name)
    return draw(width, height, spec).convert("RGB")


def test_an_unknown_android_phone_is_cropped_at_its_bars() -> None:
    image = scene("status bar and three buttons")
    assert detect_device(W, H, table()).match == "guessed"
    cropped, screen = read_screenshot(image, table())
    device = screen.device
    assert (device.inset_top, device.inset_bottom) == (round(122 / SCALE * 10) / 10, round(132 / SCALE * 10) / 10)
    assert (device.crop_top_px, device.crop_bottom_px) == (122, 132)
    assert cropped.size == (W, H - 122 - 132)
    assert screen.status_bar_style == "dark"  # dark glyphs on a light bar
    assert device.preview_profile()["height"] == device.content_height


def test_the_users_insets_win() -> None:
    _, screen = read_screenshot(scene("status bar and three buttons"), table(), {"insetTop": 0})
    assert (screen.device.inset_top, screen.device.crop_bottom_px) == (0, 132)


def test_known_phones_and_iphones_keep_their_insets() -> None:
    # The Pixel 8's size takes the table's insets, bars or not.
    pixel = Image.new("RGB", (1080, 2400), (LIGHT, LIGHT, LIGHT))
    _, screen = read_screenshot(pixel, table())
    assert screen.device.match == "exact" and screen.device.inset_top == 50.3
    # Told it's an iPhone, an unknown size isn't read for Android bars.
    _, screen = read_screenshot(scene("status bar and three buttons"), table(), {"platform": "ios"})
    assert (screen.device.platform, screen.device.inset_top, screen.device.inset_bottom) == ("ios", 0, 0)


def test_no_bars_keeps_the_whole_screenshot() -> None:
    cropped, screen = read_screenshot(scene("app bar at the top is not a status bar"), table())
    assert cropped.size == (W, H)
    assert detect_system_bars(scene("blank screen"), SCALE) == SystemBars(0, 0)


if __name__ == "__main__" and "--write" in sys.argv:
    VECTORS_PATH.write_text(json.dumps(vectors(), indent=2) + "\n")
    print(f"wrote {len(SCENES)} cases to {VECTORS_PATH}")
