"""Which phone a screenshot came from, and how to line the preview up with it.

The known-device table is rn-runtime/device-profiles.json (served from the
runtime's dist/). DESIGN.md §7 has the maths: scale = pixel width / logical
width; the status bar and home indicator (the safe-area insets) are cropped
off before the model or the asset extractor sees the screenshot; and the
preview renders the remaining content area at the same scale, so a preview
screenshot has the cropped input's pixel size.
"""

import base64
import io
import re
from dataclasses import dataclass, replace
from typing import Any, Literal, Mapping, Optional, cast

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
    platform = (overrides or {}).get("platform")
    device = detect_device(image.width, image.height, table, platform if platform in ("ios", "android") else None)
    device = apply_overrides(device, overrides or {}, table)
    style = None
    if device.crop_top_px > 0:
        style = infer_status_bar_style(image.crop((0, 0, image.width, device.crop_top_px)))
    return crop_to_content(image, device), ReactNativeScreen(device=device, status_bar_style=style)
