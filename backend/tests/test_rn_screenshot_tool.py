"""screenshot_preview for React Native: wording, availability and results."""

import io
from typing import Any, Mapping, Optional

import pytest
from PIL import Image

from agent.providers.factory import create_provider_session
from agent.state import AgentFileState
from agent.tools.definitions import canonical_tool_definitions
from agent.tools.runtime import AgentToolRuntime
from agent.tools.screenshot_preview import run_react_native_screenshot_preview
from agent.tools.types import ToolCall, ToolExecutionResult
from llm import ANTHROPIC_MODELS
from react_native.profiles import encode_png
from react_native.render import PreviewRender

PROFILE: dict[str, Any] = {"platform": "ios", "width": 390, "height": 763, "scale": 3.0, "insets": {"top": 0, "right": 0, "bottom": 0, "left": 0}}
PNG = b"\x89PNG\r\n\x1a\nfake"


def tool_text(react_native: bool) -> str:
    return " ".join(f"{tool.description} {tool.parameters}" for tool in canonical_tool_definitions(react_native=react_native))


def test_react_native_tools_describe_app_jsx() -> None:
    react_native = tool_text(True)
    assert "App.jsx" in react_native
    assert "HTML" not in react_native and "desktop" not in react_native
    assert "App.jsx" not in tool_text(False)


async def test_the_result_reports_runtime_errors_with_the_screenshot(monkeypatch: pytest.MonkeyPatch) -> None:
    async def capture(source: str, profile: Mapping[str, Any]) -> PreviewRender:
        return PreviewRender(
            png=PNG,
            status="error",
            runtime_errors=[{"kind": "runtime", "message": "Cannot read properties of undefined", "fatal": True, "line": 7}],
            meta={"statusBar": "dark"},
            ready_ms=120,
        )

    monkeypatch.setattr("agent.tools.screenshot_preview.capture_react_native_preview", capture)

    result = await run_react_native_screenshot_preview(
        {}, file_state=AgentFileState(path="App.jsx", content="export default function App() {}"), profile=PROFILE
    )

    assert result.ok  # reporting errors is the tool working
    assert result.result["content"] == (
        "App.jsx failed to render. Fix runtime_errors first. A screenshot of the 390 x 763 pt screen is attached."
    )
    details = result.result["details"]
    assert details["runtime_errors"][0]["line"] == 7
    assert details["status_bar"] == "dark"
    assert details["viewport"] == {"platform": "ios", "width": 390, "height": 763, "scale": 3.0}
    assert result.multimodal_parts is not None and result.multimodal_parts[0].data == PNG
    assert result.summary["screenshots"][0]["image_url"].startswith("data:image/png;base64,")


async def test_a_failed_capture_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def capture(source: str, profile: Mapping[str, Any]) -> PreviewRender:
        raise RuntimeError("browser crashed")

    monkeypatch.setattr("agent.tools.screenshot_preview.capture_react_native_preview", capture)

    result = await run_react_native_screenshot_preview({}, file_state=AgentFileState(path="App.jsx", content="x"), profile=PROFILE)

    assert not result.ok
    assert "browser crashed" in result.result["error"]


async def test_the_runtime_sends_screenshots_to_the_react_native_renderer(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[Mapping[str, Any], Optional[str]]] = []

    async def fake(
        args: dict[str, Any], *, file_state: AgentFileState, profile: Mapping[str, Any], reference_url: Optional[str] = None
    ) -> ToolExecutionResult:
        seen.append((profile, reference_url))
        return ToolExecutionResult(ok=True, result={}, summary={})

    monkeypatch.setattr("agent.tools.runtime.run_react_native_screenshot_preview", fake)
    runtime = AgentToolRuntime(
        file_state=AgentFileState(path="App.jsx", content="x"),
        should_generate_images=False,
        openai_api_key=None,
        openai_base_url=None,
        main_path="App.jsx",
        react_native_profile=PROFILE,
    )
    runtime.input_images = ["data:image/png;base64,SCREENSHOT"]

    await runtime.execute(ToolCall(id="call-1", name="screenshot_preview", arguments={}))

    assert seen == [(PROFILE, "data:image/png;base64,SCREENSHOT")]


@pytest.mark.parametrize("available", [True, False])
def test_react_native_screenshots_are_offered_only_when_they_can_run(monkeypatch: pytest.MonkeyPatch, available: bool) -> None:
    captured: dict[str, Any] = {}

    def definitions(**kwargs: Any) -> list[Any]:
        captured.update(kwargs)
        return []

    monkeypatch.setattr("agent.providers.factory.canonical_tool_definitions", definitions)
    monkeypatch.setattr("agent.providers.factory.is_react_native_capture_available", lambda: available)
    monkeypatch.setattr("agent.providers.factory.is_screenshot_preview_available", lambda: True)

    create_provider_session(
        model=sorted(ANTHROPIC_MODELS, key=lambda model: model.value)[0],
        prompt_messages=[{"role": "system", "content": "System"}, {"role": "user", "content": "Build it."}],
        should_generate_images=False,
        openai_api_key=None,
        openai_base_url=None,
        anthropic_api_key="test-key",
        gemini_api_key=None,
        replicate_api_key=None,
        react_native=True,
    )

    assert captured["react_native"] is True
    assert captured["screenshot_enabled"] is available


def png(size: tuple[int, int], color: str) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, "PNG")
    return buffer.getvalue()


@pytest.mark.parametrize(("reference_size", "compared"), [((1170, 2289), True), ((1169, 2290), True), ((640, 640), False)])
async def test_the_input_screenshot_is_shown_next_to_the_render(
    monkeypatch: pytest.MonkeyPatch, reference_size: tuple[int, int], compared: bool
) -> None:
    async def capture(source: str, profile: Mapping[str, Any]) -> PreviewRender:
        return PreviewRender(png=png((1170, 2289), "#FFFFFF"), status="ok", runtime_errors=[], meta={}, ready_ms=90)

    monkeypatch.setattr("agent.tools.screenshot_preview.capture_react_native_preview", capture)
    reference = encode_png(Image.new("RGB", reference_size, "#000000"))

    result = await run_react_native_screenshot_preview(
        {}, file_state=AgentFileState(path="App.jsx", content="x"), profile=PROFILE, reference_url=reference
    )

    parts = result.multimodal_parts or []
    assert len(parts) == (2 if compared else 1)
    assert ("side by side" in result.result["content"] or "next to your render" in result.result["content"]) is compared
    if compared:
        assert parts[1].data is not None
        comparison = Image.open(io.BytesIO(parts[1].data))
        assert comparison.size == (390 * 2 + 12, 763 + 30)  # both at the screen's logical size, labelled
        assert result.result["details"]["comparison"]["image_part_index"] == 1
