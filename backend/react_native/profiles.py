"""Which phone a screenshot came from, and how to line the preview up with it.

The known-device table is rn-runtime/device-profiles.json (served from the
runtime's dist/). DESIGN.md §7 has the maths: scale = pixel width / logical
width; the status bar and home indicator (the safe-area insets) are cropped
off before the model or the asset extractor sees the screenshot; and the
preview renders the remaining content area at the same scale, so a preview
screenshot has the cropped input's pixel size. A phone that isn't in the
table has no known insets; on Android they're read off the screenshot's bars
(detect_system_bars).
"""

import base64
import io
import re
from dataclasses import dataclass, replace
from typing import Any, Literal, Mapping, Optional, Sequence, cast

import numpy as np
from PIL import Image

from react_native.runtime_files import load_runtime

Platform = Literal["ios", "android"]
StatusBarStyle = Literal["light", "dark"]
DeviceMatch = Literal["exact", "scaled", "guessed", "default", "override"]

NO_INSETS = {"top": 0, "right": 0, "bottom": 0, "left": 0}
# A downscaled screenshot keeps its shape: aspect ratios this close match.
_ASPECT_TOLERANCE = 0.004
_IOS_LOGICAL_WIDTHS = (375, 390, 393, 402, 414, 428, 430, 440)
# Status-bar glyphs differ from their background by at least this much
# luminance, and cover at least this share of the strip.
_GLYPH_CONTRAST = 64
_MIN_GLYPH_SHARE = 0.002
_DATA_URL = re.compile(r"^data:image/[\w.+-]+;base64,(.*)$", re.DOTALL)


@dataclass(frozen=True)
class DeviceProfile:
    platform: Platform
    name: Optional[str]  # None when the device was guessed
    logical_width: int
    scale: float  # screenshot pixels per pt (iOS) or dp (Android)
    inset_top: float  # pt / dp above the content: status bar, cutout
    inset_bottom: float  # pt / dp below it: home indicator, navigation bar
    pixel_width: int
    pixel_height: int
    match: DeviceMatch

    @property
    def crop_top_px(self) -> int:
        return round(self.inset_top * self.scale)

    @property
    def crop_bottom_px(self) -> int:
        return round(self.inset_bottom * self.scale)

    @property
    def content_height(self) -> int:
        """Logical height of the screenshot once the insets are cropped off."""
        return round((self.pixel_height - self.crop_top_px - self.crop_bottom_px) / self.scale)

    def preview_profile(self) -> dict[str, Any]:
        """The profile render_preview takes: the content area at the screenshot's scale."""
        return {
            "platform": self.platform,
            "width": self.logical_width,
            "height": self.content_height,
            "scale": self.scale,
            "insets": dict(NO_INSETS),
        }


@dataclass(frozen=True)
class ReactNativeScreen:
    """The screen a React Native generation targets."""

    device: DeviceProfile
    # From the cropped-off status bar; None without one or when it's unclear.
    status_bar_style: Optional[StatusBarStyle]


def load_device_table() -> dict[str, Any]:
    bundle = load_runtime()
    if bundle is None:
        raise RuntimeError("rn-runtime is not built (cd rn-runtime && pnpm build)")
    return cast(dict[str, Any], bundle.read_json(str(bundle.manifest["deviceProfiles"])))


def _from_entry(entry: Mapping[str, Any], pixel_width: int, pixel_height: int, match: DeviceMatch) -> DeviceProfile:
    logical_width = int(entry["logicalWidth"])
    return DeviceProfile(
        platform=cast(Platform, entry["platform"]),
        name=str(entry["name"]),
        logical_width=logical_width,
        # From the pixels, not the table's rounded scale: the render must be exactly as wide.
        scale=pixel_width / logical_width,
        inset_top=float(entry["insetTop"] or 0),
        inset_bottom=float(entry["insetBottom"] or 0),
        pixel_width=pixel_width,
        pixel_height=pixel_height,
        match=match,
    )


def _guess_platform(pixel_width: int) -> Platform:
    for scale in (3, 2):
        if pixel_width % scale == 0 and pixel_width // scale in _IOS_LOGICAL_WIDTHS:
            return "ios"
    return "android"


def _plausible_scale(pixel_width: int, entry: Mapping[str, Any]) -> bool:
    """Whether a screenshot this wide can be that device's screen: a downscaled
    copy of its screenshots, or the same logical size at a whole 2x or 3x (an
    iPhone XS Max has the XR's shape at 3x). A 1080 x 1920 Android screenshot
    is neither for an iPhone SE (375 pt at 2x)."""
    scale = pixel_width / entry["logicalWidth"]
    return scale <= entry["pixelWidth"] / entry["logicalWidth"] + 1e-9 or (
        round(scale) in (2, 3) and abs(scale - round(scale)) < 0.01
    )


def detect_device(
    pixel_width: int,
    pixel_height: int,
    table: Mapping[str, Any],
    platform: Optional[Platform] = None,
) -> DeviceProfile:
    """Exact size match, then a scaled screenshot of a known shape, then a guess."""
    devices = [entry for entry in table["devices"] if platform in (None, entry["platform"])]
    for entry in devices:
        if (entry["pixelWidth"], entry["pixelHeight"]) == (pixel_width, pixel_height):
            return _from_entry(entry, pixel_width, pixel_height, "exact")

    if pixel_height > pixel_width:
        aspect = pixel_height / pixel_width
        shaped = sorted(
            (abs(entry["pixelHeight"] / entry["pixelWidth"] - aspect), index, entry)
            for index, entry in enumerate(devices)
            if abs(entry["pixelHeight"] / entry["pixelWidth"] - aspect) <= _ASPECT_TOLERANCE * aspect
            and _plausible_scale(pixel_width, entry)
        )
        # Only when every device of that shape is on the same platform.
        if shaped and len({entry["platform"] for _, _, entry in shaped}) == 1:
            return _from_entry(shaped[0][2], pixel_width, pixel_height, "scaled")

    guessed = platform or _guess_platform(pixel_width)
    logical_width = int(table["fallbacks"][guessed]["logicalWidth"])
    return DeviceProfile(
        platform=guessed,
        name=None,
        logical_width=logical_width,
        scale=pixel_width / logical_width,
        inset_top=0,
        inset_bottom=0,
        pixel_width=pixel_width,
        pixel_height=pixel_height,
        match="guessed",
    )


def default_device(table: Mapping[str, Any], platform: Platform = "ios") -> DeviceProfile:
    """The phone for a generation with no screenshot: the platform's first known device."""
    entry = next(entry for entry in table["devices"] if entry["platform"] == platform)
    return _from_entry(entry, int(entry["pixelWidth"]), int(entry["pixelHeight"]), "default")


def _number(value: Any, low: float, high: float) -> Optional[float]:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and low <= value <= high:
        return float(value)
    return None


def apply_overrides(device: DeviceProfile, overrides: Mapping[str, Any], table: Mapping[str, Any]) -> DeviceProfile:
    """The user's corrections (the crop overlay): platform, logical width and insets."""
    platform = overrides.get("platform")
    if platform in ("ios", "android") and platform != device.platform:
        if device.match == "default":
            device = default_device(table, cast(Platform, platform))
        else:
            device = detect_device(device.pixel_width, device.pixel_height, table, cast(Platform, platform))
    changes: dict[str, Any] = {}
    logical_width = _number(overrides.get("logicalWidth"), 200, 1100)
    if logical_width is not None:
        changes["logical_width"] = int(logical_width)
        changes["scale"] = device.pixel_width / int(logical_width)
    for key, field in (("insetTop", "inset_top"), ("insetBottom", "inset_bottom")):
        inset = _number(overrides.get(key), 0, 200)
        if inset is not None:
            changes[field] = inset
    return replace(device, **changes, match="override") if changes else device


def infer_status_bar_style(strip: Image.Image) -> Optional[StatusBarStyle]:
    """Light or dark status-bar content, from the cropped-off strip.

    The most common luminance is the background; pixels far from it are the
    clock and icons. Light glyphs mean style "light", dark ones "dark".
    """
    histogram = strip.convert("L").histogram()
    total = sum(histogram)
    if total == 0:
        return None
    background = max(range(256), key=histogram.__getitem__)
    glyph_levels = [(level, count) for level, count in enumerate(histogram) if count and abs(level - background) > _GLYPH_CONTRAST]
    glyph_pixels = sum(count for _, count in glyph_levels)
    if glyph_pixels < total * _MIN_GLYPH_SHARE:
        return None
    glyph_level = sum(level * count for level, count in glyph_levels) / glyph_pixels
    return "light" if glyph_level > background else "dark"


# ------------------------------------------------------------------ system bars

# An Android screenshot shows its phone's bars. The status bar is a band at the
# top holding one thin row of small glyphs, the clock on the left and icons on
# the right; the navigation bar is a band at the bottom holding a gesture pill
# or three buttons. Glyphs sit in the middle of their band, so a band is twice
# as tall as its glyphs' centre is far from the edge. Only clear cases count:
# a pill drawn over content, or anything else, leaves that edge uncropped.
# frontend/src/lib/react-native/systemBars.ts is the TypeScript port; both run
# rn-runtime/test-vectors/system-bars.json.
_BAR_SEARCH_DP = 64  # how far in from each edge to look
_BAR_MIN_INK = 2  # glyph pixels (differing by _GLYPH_CONTRAST) a row needs
_BAR_MIN_CONTENT_DP = 100


@dataclass(frozen=True)
class SystemBars:
    top_px: int
    bottom_px: int


def _luminance(image: Image.Image) -> np.ndarray:
    # Pillow's RGB to L: (19595 R + 38470 G + 7471 B + 32768) >> 16.
    return np.asarray(image.convert("RGB").convert("L"), dtype=np.int16)


def _background(rows: np.ndarray) -> int:
    """The most common luminance (the lowest, on a tie)."""
    return int(np.bincount(rows.ravel(), minlength=256).argmax())


def _glyph_band(inked: Sequence[bool], order: Sequence[int], max_gap: int) -> Optional[tuple[int, int]]:
    """The first run of inked rows in `order`, bridging gaps of up to max_gap rows."""
    first: Optional[int] = None
    last = 0
    gap = 0
    for row in order:
        if inked[row]:
            if first is None:
                first = row
            last, gap = row, 0
        elif first is not None:
            gap += 1
            if gap > max_gap:
                break
    return None if first is None else (first, last)


def _status_bar_px(rows: np.ndarray, dp: float) -> int:
    """The status bar's height in a screenshot's top rows, or 0."""
    count, width = int(rows.shape[0]), int(rows.shape[1])
    ink = np.abs(rows - _background(rows[: max(1, round(2 * dp))])) > _GLYPH_CONTRAST
    inked = (ink.sum(axis=1) >= _BAR_MIN_INK).tolist()
    band = _glyph_band(inked, range(count), round(1.5 * dp))
    if band is None:
        return 0
    first, last = band
    height = first + last + 1
    left = ink[first : last + 1, : round(0.4 * width)].sum(axis=1)
    right = ink[first : last + 1, round(0.6 * width) :].sum(axis=1)
    if (
        round(2 * dp) <= first <= round(20 * dp)
        and round(6 * dp) <= last - first + 1 <= round(20 * dp)
        and round(20 * dp) <= height <= min(count, round(56 * dp))
        and not any(inked[last + 1 : height - round(dp)])
        and bool((left >= _BAR_MIN_INK).any())
        and bool((right >= _BAR_MIN_INK).any())
    ):
        return height
    return 0


def _navigation_bar_px(rows: np.ndarray, dp: float) -> int:
    """The navigation bar's height in a screenshot's bottom rows, or 0."""
    count, width = int(rows.shape[0]), int(rows.shape[1])
    ink = np.abs(rows - _background(rows[count - max(1, round(2 * dp)) :])) > _GLYPH_CONTRAST
    inked = (ink.sum(axis=1) >= _BAR_MIN_INK).tolist()
    band = _glyph_band(inked, range(count - 1, -1, -1), round(1.5 * dp))
    if band is None:
        return 0
    last, first = band  # found scanning up, so the bottom row comes first
    columns = np.flatnonzero(ink[first : last + 1].any(axis=0))
    low, high = int(columns[0]), int(columns[-1])
    tall = last - first + 1

    def inked_between(start: float, end: float) -> bool:
        return bool(((columns >= start * width) & (columns < end * width)).any())

    pill = (
        round(2 * dp) <= tall <= round(8 * dp)
        and abs((low + high) / 2 - width / 2) <= 0.05 * width
        and 0.15 * width <= high - low <= 0.5 * width
    )
    buttons = (
        round(8 * dp) <= tall <= round(24 * dp)
        and inked_between(0.15, 0.35)
        and inked_between(0.4, 0.6)
        and inked_between(0.65, 0.85)
        and low >= 0.1 * width
        and high < 0.9 * width
    )
    height = 2 * count - first - last - 1
    if (
        (pill or buttons)
        and count - 1 - last >= round(3 * dp)
        and round(16 * dp) <= height <= min(count, round(56 * dp))
        and not any(inked[count - height + round(dp) : first])
    ):
        return height
    return 0


def detect_system_bars(image: Image.Image, scale: float) -> SystemBars:
    """An Android screenshot's status and navigation bars, in pixels; 0 where
    there's no clear bar. `scale` is pixels per dp."""
    count = min(image.height // 2, round(_BAR_SEARCH_DP * scale))
    if count < 1:
        return SystemBars(0, 0)
    top = _status_bar_px(_luminance(image.crop((0, 0, image.width, count))), scale)
    bottom = _navigation_bar_px(_luminance(image.crop((0, image.height - count, image.width, image.height))), scale)
    if image.height - top - bottom < round(_BAR_MIN_CONTENT_DP * scale):
        return SystemBars(0, 0)
    return SystemBars(top, bottom)


def with_system_bars(device: DeviceProfile, image: Image.Image, overrides: Mapping[str, Any]) -> DeviceProfile:
    """A phone that isn't in the table gets the insets of the bars its Android
    screenshot shows, where the user hasn't set them."""
    if device.name is not None or device.platform != "android":
        return device
    bars = detect_system_bars(image, device.scale)
    changes: dict[str, Any] = {}
    for key, field, pixels in (("insetTop", "inset_top", bars.top_px), ("insetBottom", "inset_bottom", bars.bottom_px)):
        if pixels and _number(overrides.get(key), 0, 200) is None:
            # To a tenth of a dp, as the crop overlay sets them.
            changes[field] = round(pixels / device.scale * 10) / 10
    return replace(device, **changes) if changes else device


def decode_image(data_url: str) -> Optional[Image.Image]:
    match = _DATA_URL.match(data_url)
    if not match:
        return None
    try:
        image = Image.open(io.BytesIO(base64.b64decode(match.group(1))))
        image.load()
    except Exception:
        return None
    return image


def encode_png(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def crop_to_content(image: Image.Image, device: DeviceProfile) -> Image.Image:
    return image.crop((0, device.crop_top_px, image.width, image.height - device.crop_bottom_px))


def read_screenshot(
    image: Image.Image,
    table: Mapping[str, Any],
    overrides: Optional[Mapping[str, Any]] = None,
) -> tuple[Image.Image, ReactNativeScreen]:
    """Detect the device, crop the screenshot to its content, and read the status bar."""
    overrides = overrides or {}
    platform = overrides.get("platform")
    device = detect_device(image.width, image.height, table, platform if platform in ("ios", "android") else None)
    device = with_system_bars(apply_overrides(device, overrides, table), image, overrides)
    style = None
    if device.crop_top_px > 0:
        style = infer_status_bar_style(image.crop((0, 0, image.width, device.crop_top_px)))
    return crop_to_content(image, device), ReactNativeScreen(device=device, status_bar_style=style)
