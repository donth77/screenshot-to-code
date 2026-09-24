from custom_types import InputMode
from prompts.create.image import build_image_prompt_messages
from prompts.create.text import build_text_prompt_messages
from prompts.create.video import build_video_prompt_messages
from prompts.prompt_types import Stack, UserTurnInput
from prompts.message_builder import Prompt
from prompts.react_native import build_react_native_create_messages
from react_native.profiles import ReactNativeScreen


def build_create_prompt_from_input(
    input_mode: InputMode,
    stack: Stack,
    prompt: UserTurnInput,
    image_generation_enabled: bool,
    design_system: str | None = None,
    react_native_screen: ReactNativeScreen | None = None,
) -> Prompt:
    if stack == "react_native":
        if react_native_screen is None:
            raise ValueError("React Native prompts need the target screen")
        if input_mode not in ("image", "text"):
            raise ValueError(f"React Native doesn't support {input_mode} input")
        return build_react_native_create_messages(
            input_mode=input_mode,
            text_prompt=prompt.get("text", ""),
            image_data_urls=prompt.get("images", []),
            image_generation_enabled=image_generation_enabled,
            design_system=design_system,
            screen=react_native_screen,
        )
    if input_mode == "image":
        image_urls = prompt.get("images", [])
        text_prompt = prompt.get("text", "")
        return build_image_prompt_messages(
            image_data_urls=image_urls,
            stack=stack,
            text_prompt=text_prompt,
            image_generation_enabled=image_generation_enabled,
            design_system=design_system,
        )
    if input_mode == "text":
        return build_text_prompt_messages(
            text_prompt=prompt["text"],
            stack=stack,
            image_generation_enabled=image_generation_enabled,
            design_system=design_system,
        )
    if input_mode == "video":
        video_urls = prompt.get("videos", [])
        if not video_urls:
            raise ValueError("Video mode requires a video to be provided")
        video_url = video_urls[0]
        return build_video_prompt_messages(
            video_data_url=video_url,
            stack=stack,
            text_prompt=prompt.get("text", ""),
            image_generation_enabled=image_generation_enabled,
            design_system=design_system,
        )
    raise ValueError(f"Unsupported input mode: {input_mode}")


__all__ = ["build_create_prompt_from_input"]
