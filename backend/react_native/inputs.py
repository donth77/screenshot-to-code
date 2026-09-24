"""Prepare a React Native request's screenshot before prompts are built.

Shared by the websocket route and the eval runner, so both crop the same way,
before prompt building and before asset extraction (which reads its images
from the built prompt).
"""

from typing import Any, Mapping, Optional

from prompts.prompt_types import PromptHistoryMessage, UserTurnInput
from react_native.profiles import (
    Platform,
    ReactNativeScreen,
    apply_overrides,
    decode_image,
    default_device,
    encode_png,
    read_screenshot,
)


def _screenshot_url(
    prompt: UserTurnInput, history: list[PromptHistoryMessage], generation_type: str
) -> Optional[str]:
    """The screenshot the project is built from.

    An update's history starts with it; a create request carries it. Images
    attached to an update (a logo, say) are references, not the screen.
    """
    if history:
        first_user = next((item for item in history if item["role"] == "user"), None)
        return first_user["images"][0] if first_user and first_user.get("images") else None
    if generation_type == "create":
        images = prompt.get("images", [])
        return images[0] if images else None
    return None


def prepare_react_native_inputs(
    prompt: UserTurnInput,
    history: list[PromptHistoryMessage],
    table: Mapping[str, Any],
    overrides: Optional[Mapping[str, Any]] = None,
    generation_type: str = "create",
) -> tuple[UserTurnInput, list[PromptHistoryMessage], ReactNativeScreen]:
    """Crop the screenshot to its content (wherever it appears) and describe its screen."""
    overrides = overrides or {}
    source_url = _screenshot_url(prompt, history, generation_type)
    image = decode_image(source_url) if source_url else None
    if source_url is None or image is None:
        platform: Platform = "android" if overrides.get("platform") == "android" else "ios"
        device = apply_overrides(default_device(table, platform), overrides, table)
        return prompt, history, ReactNativeScreen(device=device, status_bar_style=None)

    cropped, screen = read_screenshot(image, table, overrides)
    cropped_url = encode_png(cropped)

    def swap(urls: list[str]) -> list[str]:
        return [cropped_url if url == source_url else url for url in urls]

    prompt = {**prompt, "images": swap(prompt.get("images", []))}
    history = [{**item, "images": swap(item.get("images", []))} for item in history]
    return prompt, history, screen
