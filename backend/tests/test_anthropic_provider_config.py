from agent.providers.anthropic.provider import (
    ADAPTIVE_THINKING_MODELS,
    _get_anthropic_api_model_name,
    _get_anthropic_effort,
    serialize_anthropic_tools,
)
from agent.tools.types import CanonicalToolDefinition
from llm import Llm


def test_only_create_file_streams_its_input_eagerly() -> None:
    # Eager streaming skips the API's JSON validation; only create_file's
    # arguments are read mid-stream (the live preview).
    tools = [
        CanonicalToolDefinition(name=name, description=name, parameters={"type": "object", "properties": {}})
        for name in ("create_file", "edit_file", "extract_assets", "screenshot_preview")
    ]
    serialized = {tool["name"]: tool for tool in serialize_anthropic_tools(tools)}
    assert serialized["create_file"]["eager_input_streaming"] is True
    assert all("eager_input_streaming" not in serialized[name] for name in ("edit_file", "extract_assets", "screenshot_preview"))


def test_claude_opus_5_effort_variants_map_to_same_api_model() -> None:
    expected_efforts = {
        Llm.CLAUDE_OPUS_5_LOW: "low",
        Llm.CLAUDE_OPUS_5_MEDIUM: "medium",
        Llm.CLAUDE_OPUS_5_HIGH: "high",
        Llm.CLAUDE_OPUS_5_XHIGH: "xhigh",
        Llm.CLAUDE_OPUS_5_MAX: "max",
    }

    for model, effort in expected_efforts.items():
        assert _get_anthropic_api_model_name(model) == "claude-opus-5"
        assert _get_anthropic_effort(model) == effort
        assert model.value in ADAPTIVE_THINKING_MODELS


def test_claude_opus_4_8_effort_variants_map_to_same_api_model() -> None:
    expected_efforts = {
        Llm.CLAUDE_OPUS_4_8_LOW: "low",
        Llm.CLAUDE_OPUS_4_8_MEDIUM: "medium",
        Llm.CLAUDE_OPUS_4_8_HIGH: "high",
        Llm.CLAUDE_OPUS_4_8_XHIGH: "xhigh",
        Llm.CLAUDE_OPUS_4_8_MAX: "max",
    }

    for model, effort in expected_efforts.items():
        assert _get_anthropic_api_model_name(model) == "claude-opus-4-8"
        assert _get_anthropic_effort(model) == effort


def test_claude_fable_5_effort_variants_map_to_same_api_model() -> None:
    expected_efforts = {
        Llm.CLAUDE_FABLE_5_LOW: "low",
        Llm.CLAUDE_FABLE_5_MEDIUM: "medium",
        Llm.CLAUDE_FABLE_5_HIGH: "high",
        Llm.CLAUDE_FABLE_5_XHIGH: "xhigh",
        Llm.CLAUDE_FABLE_5_MAX: "max",
    }

    for model, effort in expected_efforts.items():
        assert _get_anthropic_api_model_name(model) == "claude-fable-5"
        assert _get_anthropic_effort(model) == effort
        assert model.value in ADAPTIVE_THINKING_MODELS
