import uuid
from datetime import datetime

from codegen.utils import main_file_path
from custom_types import InputMode
from prompts.create import build_create_prompt_from_input
from prompts.prompt_types import UserTurnInput
from react_native.inputs import prepare_react_native_inputs
from react_native.profiles import load_device_table
from config import (
    ANTHROPIC_API_KEY,
    GEMINI_API_KEY,
    LOCAL_ASSET_BASE_URL,
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    REPLICATE_API_KEY,
)
from llm import Llm, OPENAI_MODELS, ANTHROPIC_MODELS, GEMINI_MODELS
from agent.runner import Agent
from fs_logging.agent_runs import AgentRunRecorder
from prompts.create.image import build_image_prompt_messages
from prompts.create.text import build_text_prompt_messages
from prompts.prompt_types import Stack
from openai.types.chat import ChatCompletionMessageParam
from typing import Any, List


async def _run_eval_agent(
    prompt_messages: List[ChatCompletionMessageParam],
    stack: Stack,
    model: Llm,
    input_mode: str,
    eval_set: str | None,
    eval_session_id: str | None,
    input_file: str | None,
    react_native_profile: dict[str, Any] | None = None,
    run_dirs: List[str] | None = None,
) -> str:
    async def send_message(
        _: str,
        __: str | None,
        ___: int,
        ____: dict[str, Any] | None = None,
        _____: str | None = None,
    ) -> None:
        # Evals do not stream tool/assistant messages to a frontend.
        return None

    if model in ANTHROPIC_MODELS and not ANTHROPIC_API_KEY:
        raise Exception("Anthropic API key not found")
    if model in GEMINI_MODELS and not GEMINI_API_KEY:
        raise Exception("Gemini API key not found")
    if model in OPENAI_MODELS and not OPENAI_API_KEY:
        raise Exception("OpenAI API key not found")

    print(f"[EVALS] Using agent runner for model: {model.value}")

    recorder = AgentRunRecorder(
        generation_id=(
            f"gen_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        ),
        variant_index=0,
        entry_point="eval",
        stack=str(stack),
        input_mode=input_mode,
        generation_type="create",
        eval_session=eval_session_id,
        eval_set=eval_set,
        input_file=input_file,
    )
    if run_dirs is not None:
        # React Native evals read the run's iterations and cost from here.
        run_dirs.append(recorder.run_dir)
    runner = Agent(
        send_message=send_message,
        variant_index=0,
        openai_api_key=OPENAI_API_KEY,
        openai_base_url=OPENAI_BASE_URL,
        anthropic_api_key=ANTHROPIC_API_KEY,
        gemini_api_key=GEMINI_API_KEY,
        replicate_api_key=REPLICATE_API_KEY,
        should_generate_images=True,
        # No websocket to infer the host from, so use the configured base URL;
        # otherwise extracted/saved assets get hostless /local-assets/ URLs.
        asset_base_url=LOCAL_ASSET_BASE_URL,
        initial_file_state=None,
        option_codes=None,
        recorder=recorder,
        main_path=main_file_path(stack),
        react_native_profile=react_native_profile,
    )
    return await runner.run(model, prompt_messages)


def _react_native_create_prompt(
    input_mode: InputMode, text: str, images: List[str]
) -> tuple[List[ChatCompletionMessageParam], dict[str, Any]]:
    """The app's React Native create prompt (same cropping and screen facts),
    and the profile the agent's screenshots render at."""
    prompt: UserTurnInput = {"text": text, "images": images, "videos": []}
    prompt, _, screen = prepare_react_native_inputs(prompt, [], load_device_table())
    messages = build_create_prompt_from_input(input_mode, "react_native", prompt, True, None, screen)
    return messages, screen.device.preview_profile()


def react_native_eval_profile(image_url: str | None) -> dict[str, Any]:
    """The device profile an eval input's React Native screen renders at."""
    prompt: UserTurnInput = {"text": "", "images": [image_url] if image_url else [], "videos": []}
    _, _, screen = prepare_react_native_inputs(prompt, [], load_device_table())
    return screen.device.preview_profile()


async def generate_code_for_image(
    image_url: str,
    stack: Stack,
    model: Llm,
    *,
    eval_set: str | None = None,
    eval_session_id: str | None = None,
    input_file: str | None = None,
    run_dirs: List[str] | None = None,
) -> str:
    react_native_profile = None
    if stack == "react_native":
        prompt_messages, react_native_profile = _react_native_create_prompt("image", "", [image_url])
    else:
        prompt_messages = build_image_prompt_messages(
            image_data_urls=[image_url],
            stack=stack,
            text_prompt="",
            image_generation_enabled=True,
        )
    return await _run_eval_agent(
        prompt_messages,
        stack,
        model,
        input_mode="image",
        eval_set=eval_set,
        eval_session_id=eval_session_id,
        input_file=input_file,
        react_native_profile=react_native_profile,
        run_dirs=run_dirs,
    )


async def generate_code_for_text(
    text_prompt: str,
    stack: Stack,
    model: Llm,
    *,
    eval_set: str | None = None,
    eval_session_id: str | None = None,
    input_file: str | None = None,
    run_dirs: List[str] | None = None,
) -> str:
    """Text-create eval: same prompt construction as the app's text flow."""
    react_native_profile = None
    if stack == "react_native":
        prompt_messages, react_native_profile = _react_native_create_prompt("text", text_prompt, [])
    else:
        prompt_messages = build_text_prompt_messages(
            text_prompt=text_prompt,
            stack=stack,
            image_generation_enabled=True,
        )
    return await _run_eval_agent(
        prompt_messages,
        stack,
        model,
        input_mode="text",
        eval_set=eval_set,
        eval_session_id=eval_session_id,
        input_file=input_file,
        react_native_profile=react_native_profile,
        run_dirs=run_dirs,
    )
