"""Per-stack system prompts: React Native gets its own, the web stacks don't change."""

import hashlib
from pathlib import Path
from typing import get_args

import pytest

from prompts.create import build_create_prompt_from_input
from prompts.prompt_types import PromptHistoryMessage, Stack
from prompts.react_native import REACT_NATIVE_SYSTEM_PROMPT
from prompts.stack_prompts import get_system_prompt
from prompts.system_prompt import IMAGE_MANIPULATION, SYSTEM_PROMPT, TONE_AND_STYLE
from prompts.update import build_update_prompt_from_file_snapshot, build_update_prompt_from_history

# SHA-256 of SYSTEM_PROMPT before per-stack prompts existed. The web stacks'
# prompt must stay byte-identical; change this only with a deliberate edit.
WEB_SYSTEM_PROMPT_SHA256 = "8c46fed340cd5754c31322eb93e9b5de876097abeead46e468f5eacaabe914bd"
SNAPSHOT = Path(__file__).parent / "snapshots" / "react_native_system_prompt.txt"
WEB_STACKS = [stack for stack in get_args(Stack) if stack != "react_native"]


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
    prompts = [
        build_create_prompt_from_input("image", stack, {"text": "", "images": ["data:image/png;base64,AA=="], "videos": []}, False),
        build_create_prompt_from_input("text", stack, {"text": "a settings screen", "images": [], "videos": []}, False),
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
