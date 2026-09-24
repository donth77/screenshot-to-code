"""A scripted React Native agent run with real preview renders.

The model is scripted; everything else is real: the engine, the tool
runtime, the Playwright backend and the preview runtime. The agent writes
an App.jsx that crashes, sees the crash in screenshot_preview's
runtime_errors, fixes it, and sees a clean render. Skipped when rn-runtime
isn't built or Chromium is missing.
"""

import io
from typing import Any, AsyncIterator, cast

import pytest
from openai.types.chat import ChatCompletionMessageParam
from PIL import Image

from agent.engine import AgentEngine
from agent.providers.base import EventSink, ExecutedToolCall, ProviderTurn
from agent.tools.types import ToolCall
from llm import Llm
from preview_screenshot import PlaywrightBackend
from react_native.runtime_files import load_runtime

pytestmark = pytest.mark.skipif(load_runtime() is None, reason="rn-runtime is not built (cd rn-runtime && pnpm build)")

PROFILE: dict[str, Any] = {"platform": "ios", "width": 390, "height": 763, "scale": 3.0, "insets": {"top": 0, "right": 0, "bottom": 0, "left": 0}}
BROKEN = """import React from 'react';
import { Text } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

const folders = undefined;

export default function App() {
  return (
    <SafeAreaView testID="screen" style={{ flex: 1, backgroundColor: '#FFFFFF' }}>
      {folders.map((name) => <Text key={name}>{name}</Text>)}
    </SafeAreaView>
  );
}
"""
FIX = {"old_text": "const folders = undefined;", "new_text": "const folders = ['Inbox', 'Sent'];"}


class ScriptedSession:
    """Plays back turns and keeps the tool results the engine returns."""

    def __init__(self, turns: list[ProviderTurn]) -> None:
        self.turns = turns
        self.results: list[ExecutedToolCall] = []

    async def stream_turn(self, on_event: EventSink) -> ProviderTurn:
        return self.turns.pop(0)

    async def append_tool_results(self, turn: ProviderTurn, executed_tool_calls: list[ExecutedToolCall]) -> None:
        self.results.extend(executed_tool_calls)

    def total_cost_usd(self) -> None:
        return None

    async def close(self) -> None:
        pass


@pytest.fixture
async def backend(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[PlaywrightBackend]:
    # A backend of the test's own, so its browser lives on this test's event loop.
    backend = PlaywrightBackend()
    if not await backend.available():
        pytest.skip("Chromium unavailable")
    monkeypatch.setattr("preview_screenshot.registry._backend", backend)
    yield backend
    browser = await backend._get_browser()  # pyright: ignore[reportPrivateUsage]
    await browser.close()


async def test_the_agent_sees_a_crash_and_fixes_it(monkeypatch: pytest.MonkeyPatch, backend: PlaywrightBackend) -> None:
    def call(call_id: str, name: str, arguments: dict[str, Any]) -> ToolCall:
        return ToolCall(id=call_id, name=name, arguments=arguments)

    session = ScriptedSession(
        [
            ProviderTurn(assistant_text="", tool_calls=[call("1", "create_file", {"content": BROKEN}), call("2", "screenshot_preview", {})]),
            ProviderTurn(assistant_text="", tool_calls=[call("3", "edit_file", FIX), call("4", "screenshot_preview", {})]),
            ProviderTurn(assistant_text="Built the folder list.", tool_calls=[]),
        ]
    )
    monkeypatch.setattr("agent.engine.create_provider_session", lambda **_: session)

    async def send(*_: Any) -> None:
        pass

    engine = AgentEngine(
        send_message=send,
        variant_index=0,
        openai_api_key=None,
        openai_base_url=None,
        anthropic_api_key=None,
        gemini_api_key=None,
        replicate_api_key=None,
        should_generate_images=False,
        main_path="App.jsx",
        react_native_profile=PROFILE,
    )
    prompt = cast(list[ChatCompletionMessageParam], [{"role": "system", "content": "System"}, {"role": "user", "content": "Build it."}])
    final = await engine.run(list(Llm)[0], prompt)

    first, second = [executed.result for executed in session.results if executed.tool_call.name == "screenshot_preview"]
    assert first.ok and first.result["details"]["status"] == "error"
    crash = first.result["details"]["runtime_errors"][0]
    assert crash["kind"] == "runtime" and crash["line"] == 10  # the folders.map line
    assert second.result["details"] == {**second.result["details"], "status": "ok", "runtime_errors": []}
    assert second.multimodal_parts is not None and second.multimodal_parts[0].data is not None
    assert Image.open(io.BytesIO(second.multimodal_parts[0].data)).size == (1170, 2289)
    assert final == BROKEN.replace(FIX["old_text"], FIX["new_text"])
