"""A React Native generation with a scripted model, for UI tests of the phone preview.

Everything but the model is real: the websocket route, the prompts, the agent
engine, the tool runtime and screenshot_preview's Chromium renders. The model:

- create: streams App.jsx in with create_file, in chunks, the way providers
  stream tool arguments; calls screenshot_preview; then finishes. Each variant
  gets its own greeting ("Option 1" to "Option 4", in the order the variants
  ask).
- update ("... greeting to <text>"): edit_file on App.jsx, screenshot_preview,
  finish.

The screen is rn-runtime/fixtures/App.jsx with its avatar served from the
backend's /local-assets, as extracted assets are.

Run it as a backend for manual testing (Vite proxies to port 7001):
    cd backend && poetry run python -m tests.rn_ui_harness --port 7001
"""

import argparse
import asyncio
import base64
import itertools
import os
import re
from pathlib import Path
from typing import Any, Iterator, Optional, cast

from agent.providers.base import EventSink, ExecutedToolCall, ProviderTurn, StreamEvent
from agent.tools.types import ToolCall

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "rn-runtime" / "fixtures" / "App.jsx"
AVATAR_NAME = "rn-ui-harness-avatar.png"
# A 4 x 4 violet PNG.
AVATAR_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAQAAAAECAIAAAAmkwkpAAAAEklEQVR4nGNoW/0fjhjI5AAA0Ss2wexJrdgAAAAASUVORK5CYII="
)
GREETING = "Good morning, Ada"
EDIT_REQUEST = re.compile(r"greeting to (?P<text>[^\n.]+)", re.IGNORECASE)
CURRENT_GREETING = re.compile(r'testID="greeting" style=\{styles\.title\}>(?P<text>[^<]+)</Text>')
STREAM_CHUNKS = 12
STREAM_DELAY_S = 0.05


def screen_source(asset_base_url: str, greeting: str) -> str:
    source = FIXTURE.read_text(encoding="utf-8")
    source = source.replace("__ASSET_BASE__/local-assets/avatar.png", f"{asset_base_url}/local-assets/{AVATAR_NAME}")
    return source.replace(GREETING, greeting)


def write_avatar(local_asset_dir: str) -> None:
    os.makedirs(local_asset_dir, exist_ok=True)
    Path(local_asset_dir, AVATAR_NAME).write_bytes(AVATAR_PNG)


def _text_of(message: Any) -> str:
    """The text of a chat message, whether its content is a string or parts."""
    if not isinstance(message, dict):
        return ""
    content: Any = cast(dict[str, Any], message).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [cast(dict[str, Any], part) for part in cast(list[Any], content) if isinstance(part, dict)]
        return "\n".join(str(part.get("text", "")) for part in parts)
    return ""


class ScriptedReactNativeModel:
    """A provider session that plays one React Native agent run."""

    def __init__(self, prompt_messages: list[Any], asset_base_url: str, option_number: int) -> None:
        user_texts = [_text_of(message) for message in prompt_messages if isinstance(message, dict) and message.get("role") == "user"]
        edit = EDIT_REQUEST.search(user_texts[-1]) if user_texts else None
        call = itertools.count(1)
        current = CURRENT_GREETING.search("\n".join(_text_of(message) for message in prompt_messages))
        if edit and current:
            # The update prompt carries the current App.jsx; swap its greeting.
            new_text = edit.group("text").strip().strip("'\"")
            self.turns = [
                ProviderTurn(
                    assistant_text="",
                    tool_calls=[
                        ToolCall(
                            id=f"edit-{next(call)}",
                            name="edit_file",
                            arguments={
                                "path": "App.jsx",
                                "old_text": f">{current.group('text')}</Text>",
                                "new_text": f">{new_text}</Text>",
                            },
                        ),
                        ToolCall(id=f"shot-{next(call)}", name="screenshot_preview", arguments={}),
                    ],
                ),
                ProviderTurn(assistant_text=f"Changed the greeting to {new_text}.", tool_calls=[]),
            ]
        else:
            source = screen_source(asset_base_url, f"Option {option_number}")
            self.turns = [
                ProviderTurn(
                    assistant_text="",
                    tool_calls=[
                        ToolCall(id=f"create-{next(call)}", name="create_file", arguments={"path": "App.jsx", "content": source}),
                        ToolCall(id=f"shot-{next(call)}", name="screenshot_preview", arguments={}),
                    ],
                ),
                ProviderTurn(assistant_text="Built the settings screen.", tool_calls=[]),
            ]
        self.results: list[ExecutedToolCall] = []

    async def stream_turn(self, on_event: EventSink) -> ProviderTurn:
        turn = self.turns.pop(0)
        for tool_call in turn.tool_calls:
            if tool_call.name != "create_file":
                continue
            content = str(tool_call.arguments["content"])
            step = max(1, len(content) // STREAM_CHUNKS)
            for end in range(step, len(content), step):
                await on_event(
                    StreamEvent(
                        type="tool_call_delta",
                        tool_call_id=tool_call.id,
                        tool_name="create_file",
                        tool_arguments={"path": "App.jsx", "content": content[:end]},
                    )
                )
                await asyncio.sleep(STREAM_DELAY_S)
        return turn

    async def append_tool_results(self, turn: ProviderTurn, executed_tool_calls: list[ExecutedToolCall]) -> None:
        self.results.extend(executed_tool_calls)

    def total_cost_usd(self) -> Optional[float]:
        return None

    async def close(self) -> None:
        pass


class ScriptedModels:
    """Stands in for agent.engine.create_provider_session."""

    def __init__(self, asset_base_url: str) -> None:
        self.asset_base_url = asset_base_url
        self.sessions: list[ScriptedReactNativeModel] = []
        self._options: Iterator[int] = itertools.cycle(range(1, 5))

    def __call__(self, **kwargs: Any) -> ScriptedReactNativeModel:
        session = ScriptedReactNativeModel(list(kwargs["prompt_messages"]), self.asset_base_url, next(self._options))
        self.sessions.append(session)
        return session


def install(asset_base_url: str) -> ScriptedModels:
    """Replace the model for every agent run in this process."""
    import agent.engine

    models = ScriptedModels(asset_base_url)
    agent.engine.create_provider_session = models  # type: ignore[assignment]
    return models


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=7001)
    args = parser.parse_args()

    import uvicorn

    from config import LOCAL_ASSET_DIR

    base_url = f"http://127.0.0.1:{args.port}"
    write_avatar(LOCAL_ASSET_DIR)
    install(base_url)
    from main import app

    uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
