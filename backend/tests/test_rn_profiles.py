"""Device detection, cropping and status-bar inference for React Native screenshots."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from PIL import Image, ImageDraw

from prompts.prompt_types import PromptHistoryMessage, UserTurnInput
from react_native.inputs import prepare_react_native_inputs
from routes.generate_code import ParameterExtractionStage
from react_native.profiles import (
    apply_overrides,
    decode_image,
    default_device,
    detect_device,
    encode_png,
    infer_status_bar_style,
    read_screenshot,
)

TABLE: dict[str, Any] = json.loads((Path(__file__).resolve().parents[2] / "rn-runtime" / "device-profiles.json").read_text())
CONTENT = "#F2F2F7"


def phone(width: int, height: int, top: int, bottom: int, bar: str, glyphs: str) -> Image.Image:
    """A screenshot: status bar with a clock and icons, content, home indicator."""
    image = Image.new("RGB", (width, height), CONTENT)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width, top - 1), fill=bar)
    draw.rectangle((width * 0.08, top * 0.35, width * 0.2, top * 0.65), fill=glyphs)
    draw.rectangle((width * 0.75, top * 0.4, width * 0.92, top * 0.6), fill=glyphs)
    draw.rectangle((width * 0.35, height - bottom * 0.4, width * 0.65, height - bottom * 0.3), fill="#000000")
    return image


def test_an_iphone_screenshot_is_cropped_to_its_content() -> None:
    cropped, screen = read_screenshot(phone(1170, 2532, 141, 102, "#FFFFFF", "#000000"), TABLE)

    assert screen.device.match == "exact"
    assert screen.device.platform == "ios"
    assert (screen.device.crop_top_px, screen.device.crop_bottom_px) == (141, 102)
    assert cropped.size == (1170, 2289)
    assert cropped.getpixel((0, 0)) == cropped.getpixel((0, cropped.height - 1)) == (242, 242, 247)
    assert screen.device.preview_profile() == {
        "platform": "ios", "width": 390, "height": 763, "scale": 3.0, "insets": {"top": 0, "right": 0, "bottom": 0, "left": 0},
    }
    assert screen.status_bar_style == "dark"


def test_a_pixel_8_screenshot_uses_the_verified_insets() -> None:
    cropped, screen = read_screenshot(phone(1080, 2400, 132, 63, "#1C1B1F", "#FFFFFF"), TABLE)

    assert screen.device.platform == "android"
    assert (screen.device.crop_top_px, screen.device.crop_bottom_px) == (132, 63)
    assert cropped.size == (1080, 2205)
    # The preview renders 412 x 841 at 1080/412: 2205 px tall, like the crop.
    assert screen.device.content_height == 841
    assert round(841 * screen.device.scale) == 2205
    assert screen.status_bar_style == "light"


def test_a_downscaled_screenshot_matches_by_shape() -> None:
    device = detect_device(585, 1266, TABLE)

    assert (device.match, device.platform, device.logical_width, device.scale) == ("scaled", "ios", 390, 1.5)
    assert device.crop_top_px == round(47 * 1.5)


def test_an_unknown_size_is_guessed_and_not_cropped() -> None:
    android = detect_device(1000, 1800, TABLE)
    ios = detect_device(1206, 2400, TABLE)

    assert (android.match, android.platform, android.crop_top_px, android.crop_bottom_px) == ("guessed", "android", 0, 0)
    assert (ios.match, ios.platform, ios.logical_width) == ("guessed", "ios", 390)


def test_overrides_change_platform_width_and_insets() -> None:
    iphone_mini = detect_device(1080, 2340, TABLE)
    as_android = apply_overrides(iphone_mini, {"platform": "android", "insetTop": 40, "insetBottom": 20}, TABLE)

    assert iphone_mini.platform == "ios"
    assert (as_android.platform, as_android.logical_width, as_android.inset_top, as_android.match) == ("android", 412, 40, "override")
    # Out-of-range or malformed values are ignored.
    assert apply_overrides(iphone_mini, {"insetTop": -5, "logicalWidth": "wide"}, TABLE) == iphone_mini


def test_a_blank_status_bar_has_no_style() -> None:
    assert infer_status_bar_style(Image.new("RGB", (1170, 141), "#FFFFFF")) is None


def test_the_request_screenshot_is_cropped_in_the_prompt_and_history() -> None:
    screenshot = encode_png(phone(1170, 2532, 141, 102, "#FFFFFF", "#000000"))
    reference = encode_png(Image.new("RGB", (64, 64), "#FF0000"))
    history: list[PromptHistoryMessage] = [
        {"role": "user", "text": "Build this.", "images": [screenshot], "videos": []},
        {"role": "assistant", "text": "code", "images": [], "videos": []},
    ]
    prompt: UserTurnInput = {"text": "Match the logo.", "images": [reference], "videos": []}

    new_prompt, new_history, screen = prepare_react_native_inputs(prompt, history, TABLE, generation_type="update")

    cropped = decode_image(new_history[0]["images"][0])
    assert cropped is not None and cropped.size == (1170, 2289)
    assert new_prompt["images"] == [reference]  # only the device screenshot is cropped
    assert screen.device.logical_width == 390


@pytest.mark.parametrize(("platform", "size"), [("ios", (390, 763)), ("android", (412, 841))])
def test_a_request_without_a_screenshot_targets_the_default_phone(platform: str, size: tuple[int, int]) -> None:
    prompt: UserTurnInput = {"text": "A settings screen", "images": [], "videos": []}

    _, _, screen = prepare_react_native_inputs(prompt, [], TABLE, {"platform": platform})

    profile = screen.device.preview_profile()
    assert (profile["platform"], profile["width"], profile["height"]) == (platform, *size)
    assert screen.device.match == "default"
    assert default_device(TABLE, "ios").name == TABLE["devices"][0]["name"]


def test_images_attached_to_a_snapshot_update_are_references() -> None:
    phone_sized = encode_png(phone(1170, 2532, 141, 102, "#FFFFFF", "#000000"))
    prompt: UserTurnInput = {"text": "Make it look like this.", "images": [phone_sized], "videos": []}

    new_prompt, _, screen = prepare_react_native_inputs(prompt, [], TABLE, generation_type="update")

    assert new_prompt["images"] == [phone_sized]
    assert screen.device.match == "default"


async def test_the_route_crops_the_screenshot_with_the_users_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("routes.generate_code.load_device_table", lambda: TABLE)
    screenshot = encode_png(phone(1170, 2532, 141, 102, "#FFFFFF", "#000000"))

    extracted = await ParameterExtractionStage(AsyncMock()).extract_and_validate(
        {
            "generatedCodeConfig": "react_native",
            "inputMode": "image",
            "prompt": {"text": "", "images": [screenshot]},
            "reactNativeProfile": {"insetTop": 50},
        }
    )

    cropped = decode_image(extracted.prompt["images"][0])
    assert cropped is not None and cropped.size == (1170, 2532 - 150 - 102)
    assert extracted.react_native_screen is not None
    assert extracted.react_native_screen.device.match == "override"


async def test_react_native_without_a_runtime_build_fails_clearly(monkeypatch: pytest.MonkeyPatch) -> None:
    def not_built() -> dict[str, Any]:
        raise RuntimeError("rn-runtime is not built")

    monkeypatch.setattr("routes.generate_code.load_device_table", not_built)
    throw_error = AsyncMock()

    with pytest.raises(RuntimeError):
        await ParameterExtractionStage(throw_error).extract_and_validate(
            {"generatedCodeConfig": "react_native", "inputMode": "text", "prompt": {"text": "a login screen"}}
        )

    assert throw_error.await_args is not None
    assert "pnpm build" in throw_error.await_args.args[0]


def test_flat_colors_are_the_screenshots_repeated_exact_colors() -> None:
    from react_native.profiles import flat_colors

    image = Image.new("RGB", (400, 800), "#1C1B1F")  # background
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 400, 399, 599), fill="#2B2930")  # a surface: a quarter
    draw.rectangle((20, 40, 379, 79), fill="#E6E1E5")  # text: 4.5%
    draw.rectangle((0, 700, 399, 709), fill="#1E1D21")  # too close to the background to list
    for x in range(400):  # a gradient "photo": no colour repeats much
        draw.line((x, 610, x, 690), fill=(x % 256, (x * 3) % 256, 128))

    colors = flat_colors(image)

    assert [color for color, _ in colors] == ["#1C1B1F", "#2B2930", "#E6E1E5"]
    assert colors[1][1] == pytest.approx(0.25, abs=0.01)
    assert colors[2][1] == pytest.approx(0.045, abs=0.005)
