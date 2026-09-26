"""Per-stack system prompts: React Native gets its own, the web stacks don't change."""

import hashlib
import json
from pathlib import Path
from typing import Any, get_args

import pytest

from prompts.create import build_create_prompt_from_input
from prompts.prompt_types import PromptHistoryMessage, Stack
from prompts.react_native import REACT_NATIVE_SYSTEM_PROMPT
from prompts.stack_prompts import get_system_prompt
from prompts.system_prompt import IMAGE_MANIPULATION, SYSTEM_PROMPT, TONE_AND_STYLE
from prompts.update import build_update_prompt_from_file_snapshot, build_update_prompt_from_history
from react_native.profiles import ReactNativeScreen, default_device

# SHA-256 of SYSTEM_PROMPT before per-stack prompts existed. The web stacks'
# prompt must stay byte-identical; change this only with a deliberate edit.
WEB_SYSTEM_PROMPT_SHA256 = "8c46fed340cd5754c31322eb93e9b5de876097abeead46e468f5eacaabe914bd"
SNAPSHOT = Path(__file__).parent / "snapshots" / "react_native_system_prompt.txt"
WEB_STACKS = [stack for stack in get_args(Stack) if stack != "react_native"]
TABLE = json.loads((Path(__file__).resolve().parents[2] / "rn-runtime" / "device-profiles.json").read_text())
SCREEN = ReactNativeScreen(device=default_device(TABLE, "ios"), status_bar_style="dark")


def test_the_web_prompt_is_unchanged() -> None:
    assert hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest() == WEB_SYSTEM_PROMPT_SHA256


@pytest.mark.parametrize("stack", WEB_STACKS)
def test_web_stacks_share_the_web_prompt(stack: Stack) -> None:
    assert get_system_prompt(stack) is SYSTEM_PROMPT


def test_react_native_prompt_matches_its_snapshot() -> None:
    # After an intended change: regenerate tests/snapshots/react_native_system_prompt.txt
    # from prompts.react_native.REACT_NATIVE_SYSTEM_PROMPT and review the diff.
    assert get_system_prompt("react_native") == REACT_NATIVE_SYSTEM_PROMPT == SNAPSHOT.read_text()


def test_react_native_prompt_shares_the_tone_and_image_sections() -> None:
    assert TONE_AND_STYLE in REACT_NATIVE_SYSTEM_PROMPT
    assert IMAGE_MANIPULATION in REACT_NATIVE_SYSTEM_PROMPT
    for web_only in ("index.html", "cdn.tailwindcss.com", "outerHTML", "## Vue"):
        assert web_only not in REACT_NATIVE_SYSTEM_PROMPT


@pytest.mark.parametrize("stack", ["html_tailwind", "react_native"])
def test_every_builder_sends_the_stacks_prompt(stack: Stack) -> None:
    history_turns: list[PromptHistoryMessage] = [
        {"role": "user", "text": "Build it.", "images": [], "videos": []},
        {"role": "assistant", "text": "code", "images": [], "videos": []},
    ]
    screen = SCREEN if stack == "react_native" else None
    prompts = [
        build_create_prompt_from_input("image", stack, {"text": "", "images": ["data:image/png;base64,AA=="], "videos": []}, False, None, screen),
        build_create_prompt_from_input("text", stack, {"text": "a settings screen", "images": [], "videos": []}, False, None, screen),
        build_update_prompt_from_history(stack=stack, history=history_turns, image_generation_enabled=False),
        build_update_prompt_from_file_snapshot(
            stack=stack,
            prompt={"text": "Make it blue.", "images": [], "videos": []},
            file_state={"content": "code"},
            image_generation_enabled=False,
        ),
    ]
    for messages in prompts:
        assert messages[0].get("content") == get_system_prompt(stack)


def user_text(messages: list[Any]) -> str:
    content = messages[1].get("content")
    if isinstance(content, str):
        return content
    return str(content[-1]["text"])


def test_the_screenshot_turn_states_the_screen() -> None:
    screen = ReactNativeScreen(device=default_device(TABLE, "ios"), status_bar_style="light")
    messages = build_create_prompt_from_input(
        "image", "react_native", {"text": "Use a blue accent.", "images": ["data:image/png;base64,AA=="], "videos": []}, False, None, screen
    )

    text = user_text(messages)
    assert "Target: an iPhone, with a content area 390 pt wide and 763 pt tall." in text
    assert "cropped off the screenshot" in text
    assert '<StatusBar style="light" />' in text
    assert "placehold.co" in text  # image generation is off
    assert "flat colors" not in text  # none were read
    assert text.endswith("Additional instructions: Use a blue accent.")


def test_the_screenshot_turn_lists_its_flat_colors() -> None:
    screen = ReactNativeScreen(
        device=default_device(TABLE, "ios"), status_bar_style="light", colors=(("#1C1B1F", 0.62), ("#E6E1E5", 0.04), ("#D0BCFF", 0.006))
    )
    messages = build_create_prompt_from_input(
        "image", "react_native", {"text": "", "images": ["data:image/png;base64,AA=="], "videos": []}, False, None, screen
    )

    assert (
        "- The screenshot's main flat colors, by share of the screen: #1C1B1F (62%), #E6E1E5 (4%), #D0BCFF (under 1%). "
        "Use these exact values for the backgrounds, surfaces, text and accents they match."
    ) in user_text(messages)


def test_the_text_turn_targets_the_default_phone() -> None:
    screen = ReactNativeScreen(device=default_device(TABLE, "android"), status_bar_style=None)
    messages = build_create_prompt_from_input(
        "text", "react_native", {"text": "a wallet home screen", "images": [], "videos": []}, True, None, screen
    )

    text = user_text(messages)
    assert text.startswith("\nBuild a React Native screen for: a wallet home screen")
    assert "an Android phone, with a content area 412 dp wide and 841 dp tall" in text
    assert '<StatusBar style="dark" /> over a light header' in text


def test_update_turns_name_the_target() -> None:
    screen = ReactNativeScreen(device=default_device(TABLE, "ios"), status_bar_style=None)
    history: list[PromptHistoryMessage] = [
        {"role": "user", "text": "Build it.", "images": [], "videos": []},
        {"role": "assistant", "text": "code", "images": [], "videos": []},
    ]
    messages = build_update_prompt_from_history(
        stack="react_native", history=history, image_generation_enabled=False, react_native_screen=screen
    )

    assert "- Target: an iPhone, with a content area 390 pt wide and 763 pt tall." in str(messages[1].get("content"))
