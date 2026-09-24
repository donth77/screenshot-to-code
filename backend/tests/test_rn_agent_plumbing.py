"""React Native's main file: App.jsx through the agent, history and requests.

The web stacks keep index.html; their existing tests cover that.
"""

from typing import Any, cast
from unittest.mock import AsyncMock

import json
from pathlib import Path

import pytest
from openai.types.chat import ChatCompletionMessageParam

from agent.engine import AgentEngine, EmptyOutputError
from agent.providers.base import EventSink, ExecutedToolCall, ProviderTurn
from agent.tools.types import ToolCall
from llm import Llm
from prompts.update import build_update_prompt_from_file_snapshot, build_update_prompt_from_history
from routes.generate_code import ParameterExtractionStage

APP = """import React from 'react';
import { Text } from 'react-native';

export default function App() {
  return <Text>{'<html> is not involved'}</Text>;
}"""

PROMPT = cast(list[ChatCompletionMessageParam], [{"role": "system", "content": "System"}, {"role": "user", "content": "Build it."}])


class ScriptedSession:
    """Plays back provider turns."""

    def __init__(self, turns: list[ProviderTurn]) -> None:
        self.turns = turns

    async def stream_turn(self, on_event: EventSink) -> ProviderTurn:
        return self.turns.pop(0)

    async def append_tool_results(self, turn: ProviderTurn, executed_tool_calls: list[ExecutedToolCall]) -> None:
        pass

    def total_cost_usd(self) -> None:
        return None

    async def close(self) -> None:
        pass


async def run_engine(
    monkeypatch: pytest.MonkeyPatch, turns: list[ProviderTurn], main_path: str
) -> tuple[AgentEngine, str, list[tuple[str, Any]]]:
    monkeypatch.setattr("agent.engine.create_provider_session", lambda **_: ScriptedSession(turns))
    events: list[tuple[str, Any]] = []

    async def send(msg_type: str, value: str | None, variant_index: int, data: dict[str, Any] | None, event_id: str | None) -> None:
        events.append((msg_type, data if data is not None else value))

    engine = AgentEngine(
        send_message=send,
        variant_index=0,
        openai_api_key=None,
        openai_base_url=None,
        anthropic_api_key=None,
        gemini_api_key=None,
        replicate_api_key=None,
        should_generate_images=False,
        main_path=main_path,
    )
    result = await engine.run(list(Llm)[0], PROMPT)
    return engine, result, events


async def test_react_native_always_writes_app_jsx(monkeypatch: pytest.MonkeyPatch) -> None:
    create = ToolCall(id="call-1", name="create_file", arguments={"path": "index.html", "content": APP})
    turns = [ProviderTurn(assistant_text="", tool_calls=[create]), ProviderTurn(assistant_text="Done.", tool_calls=[])]

    engine, result, events = await run_engine(monkeypatch, turns, "App.jsx")

    assert result == APP  # untouched by HTML extraction
    assert engine.file_state.path == "App.jsx"
    tool_starts = [data for kind, data in events if kind == "toolStart"]
    assert tool_starts[0]["input"]["path"] == "App.jsx"


async def test_web_stacks_keep_the_path_the_model_names(monkeypatch: pytest.MonkeyPatch) -> None:
    create = ToolCall(id="call-1", name="create_file", arguments={"path": "page.html", "content": "<html><body>Hi</body></html>"})
    turns = [ProviderTurn(assistant_text="", tool_calls=[create]), ProviderTurn(assistant_text="Done.", tool_calls=[])]

    engine, _, events = await run_engine(monkeypatch, turns, "index.html")

    assert engine.file_state.path == "page.html"
    assert [data for kind, data in events if kind == "toolStart"][0]["input"]["path"] == "page.html"


async def test_a_fenced_reply_without_tools_still_becomes_the_file(monkeypatch: pytest.MonkeyPatch) -> None:
    turns = [ProviderTurn(assistant_text=f"```jsx\n{APP}\n```", tool_calls=[])]

    _, result, _ = await run_engine(monkeypatch, turns, "App.jsx")

    assert result == APP


async def test_a_prose_reply_without_tools_fails_instead_of_saving_prose(monkeypatch: pytest.MonkeyPatch) -> None:
    turns = [ProviderTurn(assistant_text="I built a settings screen.", tool_calls=[])]

    with pytest.raises(EmptyOutputError):
        await run_engine(monkeypatch, turns, "App.jsx")


def test_update_history_wraps_the_previous_code_as_app_jsx() -> None:
    messages = build_update_prompt_from_history(
        stack="react_native",
        history=[
            {"role": "user", "text": "Build it.", "images": [], "videos": []},
            {"role": "assistant", "text": APP, "images": [], "videos": []},
            {"role": "user", "text": "Make the title bigger.", "images": [], "videos": []},
        ],
        image_generation_enabled=False,
    )

    assert messages[2].get("content") == f'<file path="App.jsx">\n{APP}\n</file>'


def test_file_snapshot_update_defaults_to_app_jsx() -> None:
    messages = build_update_prompt_from_file_snapshot(
        stack="react_native",
        prompt={"text": "Make the title bigger.", "images": [], "videos": []},
        file_state={"content": APP},
        image_generation_enabled=False,
    )

    assert '<current_file path="App.jsx">' in str(messages[1].get("content"))


async def test_request_file_state_defaults_to_app_jsx() -> None:
    extracted = await ParameterExtractionStage(AsyncMock()).extract_and_validate(
        {
            "generatedCodeConfig": "react_native",
            "inputMode": "text",
            "generationType": "update",
            "prompt": {"text": "Make the title bigger."},
            "fileState": {"content": APP},
        }
    )

    assert extracted.file_state == {"path": "App.jsx", "content": APP}


@pytest.fixture(autouse=True)
def _device_table_from_source(monkeypatch: pytest.MonkeyPatch) -> None:
    """React Native requests read the device table; use the source copy, not a build."""
    table = json.loads((Path(__file__).resolve().parents[2] / "rn-runtime" / "device-profiles.json").read_text())
    monkeypatch.setattr("routes.generate_code.load_device_table", lambda: table)
