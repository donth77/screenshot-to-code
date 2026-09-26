"""React Native eval metrics (evals/react_native_metrics.py).

Browser tests skip when rn-runtime isn't built or Chromium is missing.
"""

import io
import json
from pathlib import Path
from typing import Any, AsyncIterator

import numpy as np
import pytest
from PIL import Image, ImageDraw

from evals.core import react_native_eval_profile
from evals.react_native_metrics import (
    FloatArray,
    aggregate,
    compare_images,
    error_metrics,
    fake_status_bar,
    format_markdown,
    report_folder,
    run_metrics,
    ssim,
)
from evals.react_native_outputs import write_react_native_outputs
from preview_screenshot import PlaywrightBackend
from react_native.profiles import encode_png, load_device_table, read_screenshot
from react_native.runtime_files import load_runtime

BUILT = load_runtime() is not None
needs_runtime = pytest.mark.skipif(not BUILT, reason="rn-runtime is not built (cd rn-runtime && pnpm build)")


# ------------------------------------------------------------------------- SSIM


def _pattern() -> tuple[FloatArray, FloatArray, FloatArray]:
    y, x = np.mgrid[0:48, 0:32].astype(np.float64)
    a = (x * 7 + y * 3) % 256
    inverted = a.copy()
    inverted[10:30, 5:20] = 255 - inverted[10:30, 5:20]
    dimmed = np.clip(a * 0.5 + 60, 0, 255)
    return a, inverted, dimmed


def test_ssim_matches_the_reference_implementation() -> None:
    a, inverted, dimmed = _pattern()

    # Reference values: scikit-image 0.24.0 structural_similarity with
    # gaussian_weights=True, sigma=1.5, use_sample_covariance=False, data_range=255.
    assert ssim(a, a) == pytest.approx(1.0)
    assert ssim(a, inverted) == pytest.approx(0.472573982970723, abs=1e-9)
    assert ssim(a, dimmed) == pytest.approx(0.8165626070239967, abs=1e-9)


def test_ssim_rejects_mismatched_or_tiny_images() -> None:
    with pytest.raises(ValueError, match="shape"):
        ssim(np.zeros((20, 20)), np.zeros((20, 21)))
    with pytest.raises(ValueError, match="at least"):
        ssim(np.zeros((10, 20)), np.zeros((10, 20)))


def _screen(size: tuple[int, int], box: tuple[int, int, int, int] | None = None) -> Image.Image:
    image = Image.new("RGB", size, "#F2F2F7")
    if box:
        ImageDraw.Draw(image).rectangle(box, fill="#007AFF")
    return image


def test_screens_within_two_pixels_are_cropped_to_a_common_size_and_compared_in_points() -> None:
    reference = _screen((1170, 2289), (60, 300, 1110, 450))
    render = _screen((1170, 2291), (60, 300, 1110, 450))

    result = compare_images(reference, render, 3)

    assert result["compared_pt"] == [390, 763]
    assert result["ssim"] == 1.0 and result["mean_abs_diff"] == 0.0


def test_a_moved_block_scores_lower_than_an_identical_screen() -> None:
    reference = _screen((1170, 2289), (60, 300, 1110, 450))
    moved = _screen((1170, 2289), (60, 600, 1110, 750))

    result = compare_images(reference, moved, 3)

    assert 0.5 < result["ssim"] < 1.0
    assert 0 < result["mean_abs_diff"] < 0.1


def test_screens_of_different_sizes_are_not_compared() -> None:
    result = compare_images(_screen((1170, 2289)), _screen((1170, 2532)), 3)

    assert result["error"] == "size mismatch of 0 x 243 px"
    assert "ssim" not in result


def test_transparent_screenshots_are_compared_over_white() -> None:
    reference = Image.new("RGBA", (300, 600), (0, 0, 0, 0))
    render = Image.new("RGB", (300, 600), "#FFFFFF")

    assert compare_images(reference, render, 1)["mean_abs_diff"] == 0.0


# -------------------------------------------------------------- fake status bar


def _band(texts: list[str] = [], icons: list[str] = []) -> dict[str, Any]:
    return {
        "band": 60,
        "texts": [{"text": t, "x": 0, "y": 10} for t in texts],
        "icons": [{"name": n, "x": 300, "y": 10} for n in icons],
    }


@pytest.mark.parametrize(
    "band, detected",
    [
        (_band(["9:41"]), True),
        (_band(["12:30 PM"]), True),
        (_band(["Inbox"], ["battery-full", "wifi"]), True),
        (_band(["Inbox"], ["signal-high", "battery"]), True),
        (_band(["Inbox"], ["wifi"]), False),  # a settings row
        (_band(["Today 9:41", "$9.99"], ["bell"]), False),
        (_band(), False),
    ],
)
def test_a_fake_status_bar_is_a_clock_or_two_status_icon_families(band: dict[str, Any], detected: bool) -> None:
    assert fake_status_bar(band)["detected"] is detected


def test_an_unprobed_render_has_no_status_bar_verdict() -> None:
    assert fake_status_bar(None) == {"detected": None}


# ---------------------------------------------------------------- render report


def test_error_metrics_summarize_the_render_report() -> None:
    report: dict[str, Any] = {
        "status": "degraded",
        "ready_ms": 812,
        "runtime_errors": [
            {"kind": "unknown_icon", "message": 'lucide-react-native has no icon "Wifi2".', "fatal": False},
            {"kind": "native_compat", "rule": "web-style", "message": "...", "fatal": False},
            {"kind": "native_compat", "rule": "web-style", "message": "other", "fatal": False},
            {"kind": "native_compat", "rule": "dom-element", "message": "...", "fatal": False},
        ],
    }

    metrics = error_metrics(report)

    assert metrics["renders"] and not metrics["fatal"] and not metrics["runtime_error"]
    assert metrics["unknown_icon"] and metrics["native_compat"] and not metrics["unknown_import"]
    assert metrics["native_compat_rules"] == {"dom-element": 1, "web-style": 2}
    assert metrics["error_kinds"] == {"native_compat": 3, "unknown_icon": 1}


@pytest.mark.parametrize("kind", ["unhandled_rejection", "invalid_hook_call"])
def test_async_and_hook_errors_are_runtime_errors(kind: str) -> None:
    # The screen can still render ("degraded") while the app is failing.
    report: dict[str, Any] = {"status": "degraded", "runtime_errors": [{"kind": kind, "message": "boom", "fatal": False}]}

    metrics = error_metrics(report)

    assert metrics["renders"] and metrics["runtime_error"]


def test_an_unknown_import_is_a_fatal_runtime_error() -> None:
    report: dict[str, Any] = {"status": "error", "runtime_errors": [{"kind": "import", "message": 'Cannot import "expo-blur".', "fatal": True}]}

    metrics = error_metrics(report)

    assert metrics["fatal"] and metrics["unknown_import"] and not metrics["renders"]


def test_run_metrics_count_iterations_tokens_and_cost() -> None:
    run: dict[str, Any] = {
        "run_id": "r1",
        "model": "some-model",
        "status": "completed",
        "total_duration_ms": 61234,
        "total_cost_usd": 0.42,
        "has_unpriced_calls": False,
        "llm_calls": [
            {"usage": {"input": 1000, "output": 200, "total": 1200}},
            {"usage": {"input": 1500, "output": 100, "total": 1600}},
            {"usage": None},
        ],
        "tool_calls": [{"name": "create_file"}, {"name": "screenshot_preview"}, {"name": "edit_file"}, {"name": "screenshot_preview"}],
    }

    metrics = run_metrics(run)

    assert metrics is not None
    assert (metrics["llm_calls"], metrics["iterations"], metrics["edits"], metrics["latency_s"]) == (3, 2, 1, 61.2)
    assert metrics["tokens"] == {"input": 2500, "output": 300, "total": 2800}
    assert run_metrics(None) is None


# ---------------------------------------------------------------------- aggregate


def _output(ssim_value: float | None, status: str, fake: bool | None, bundle: bool | None, cost: float | None) -> dict[str, Any]:
    image: dict[str, Any] = {"error": "no render"} if ssim_value is None else {"ssim": ssim_value, "mean_abs_diff": 1 - ssim_value}
    return {
        "image": image,
        "errors": error_metrics({"status": status, "runtime_errors": []}),
        "fake_status_bar": {"detected": fake},
        "native_bundle": bundle,
        "run": None
        if cost is None
        else {"iterations": 2, "llm_calls": 4, "latency_s": 50.0, "cost_usd": cost, "has_unpriced_calls": False},
    }


def test_the_aggregate_reports_rates_over_known_values_only() -> None:
    outputs = [
        _output(0.8, "ok", False, True, 0.2),
        _output(0.6, "degraded", True, None, 0.4),
        _output(None, "error", None, False, None),
    ]

    report = aggregate(outputs)

    assert report["outputs"] == 3 and report["image_not_compared"] == 1
    assert report["ssim"]["mean"] == 0.7 and report["ssim"]["of"] == 2
    assert report["renders"] == {"rate": 0.667, "count": 2, "of": 3}
    assert report["clean_render"]["count"] == 1
    assert report["fake_status_bar"] == {"rate": 0.5, "count": 1, "of": 2}
    assert report["native_bundle"] == {"rate": 0.5, "count": 1, "of": 2}
    assert report["cost_usd"]["total"] == 0.6 and report["runs_recorded"] == 2

    markdown = format_markdown(report, "baseline")
    assert "| Renders (ok or degraded) | 67% (2/3) |" in markdown
    assert "| Cost (USD) | 0.60 total, 0.300 mean |" in markdown


def test_an_empty_folder_aggregates_to_not_available() -> None:
    markdown = format_markdown(aggregate([]), "empty")

    assert "| SSIM (higher is better) | n/a |" in markdown


# ----------------------------------------------------------- rendered end to end

APP = """import React from 'react';
import { View, Text } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

export default function App() {
  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: '#F2F2F7' }}>
      <View style={{ margin: 20, height: 120, borderRadius: 12, backgroundColor: '#007AFF' }} />
      <Text style={{ marginHorizontal: 20, fontSize: 17 }}>Inbox</Text>
    </SafeAreaView>
  );
}
"""

FAKE_STATUS_BAR_APP = """import React from 'react';
import { View, Text } from 'react-native';
import { Battery, Wifi, Signal } from 'lucide-react-native';

export default function App() {
  return (
    <View style={{ flex: 1 }}>
      <View style={{ flexDirection: 'row', justifyContent: 'space-between', paddingHorizontal: 24, paddingTop: 12 }}>
        <Text style={{ fontWeight: '600' }}>9:41</Text>
        <View style={{ flexDirection: 'row', gap: 4 }}>
          <Signal size={16} /><Wifi size={16} /><Battery size={22} />
        </View>
      </View>
      <Text style={{ fontSize: 34, padding: 16 }}>Inbox</Text>
    </View>
  );
}
"""


@pytest.fixture
async def backend(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[PlaywrightBackend]:
    backend = PlaywrightBackend()
    if not await backend.available():
        pytest.skip("Chromium unavailable")
    monkeypatch.setattr("preview_screenshot.registry._backend", backend)
    yield backend
    await (await backend._get_browser()).close()  # pyright: ignore[reportPrivateUsage]


@needs_runtime
async def test_an_eval_output_scores_itself_against_its_input(tmp_path: Path, backend: PlaywrightBackend) -> None:
    # The input is the render itself, framed with a status bar and home
    # indicator, so the content areas match and SSIM is near 1.
    blank = encode_png(Image.new("RGB", (1179, 2556), "#FFFFFF"))
    profile = react_native_eval_profile(blank)
    first = await write_react_native_outputs(str(tmp_path / "draft_0.html"), APP, profile)
    assert first["status"] == "ok"
    render = Image.open(io.BytesIO((tmp_path / "draft_0.png").read_bytes()))
    _, screen = read_screenshot(Image.new("RGB", (1179, 2556)), load_device_table())
    screenshot = Image.new("RGB", (1179, 2556), "#000000")
    screenshot.paste(render, (0, screen.device.crop_top_px))
    input_png = tmp_path / "inbox.png"
    screenshot.save(input_png)

    await write_react_native_outputs(str(tmp_path / "inbox_0.html"), APP, profile, input_png=str(input_png))
    await write_react_native_outputs(str(tmp_path / "inbox_1.html"), FAKE_STATUS_BAR_APP, profile, input_png=str(input_png))

    same = json.loads((tmp_path / "inbox_0.metrics.json").read_text())
    other = json.loads((tmp_path / "inbox_1.metrics.json").read_text())
    assert same["image"]["ssim"] > 0.99 and same["image"]["mean_abs_diff"] < 0.01
    assert other["image"]["ssim"] < same["image"]["ssim"]
    assert same["fake_status_bar"]["detected"] is False
    assert other["fake_status_bar"] == {"detected": True, "clock_text": ["9:41"], "icon_families": ["battery", "signal", "wifi"]}
    assert same["errors"]["status"] == "ok" and same["run"] is None


@needs_runtime
async def test_a_results_folder_gets_a_report(tmp_path: Path, backend: PlaywrightBackend) -> None:
    profile = react_native_eval_profile(None)
    await write_react_native_outputs(str(tmp_path / "feed_0.html"), APP, profile)
    await write_react_native_outputs(str(tmp_path / "feed_1.html"), FAKE_STATUS_BAR_APP, profile)
    # An output from before the probe existed is re-rendered to probe it.
    older = json.loads((tmp_path / "feed_1.json").read_text())
    del older["top_band"]
    (tmp_path / "feed_1.json").write_text(json.dumps(older))

    summary = await report_folder(str(tmp_path), inputs_dir=None)

    assert summary["outputs"] == 2
    assert summary["fake_status_bar"] == {"rate": 0.5, "count": 1, "of": 2}
    assert summary["image_not_compared"] == 2  # no inputs folder given
    assert "| Fake status bar | 50% (1/2) |" in (tmp_path / "report.md").read_text()
    assert len(json.loads((tmp_path / "report.json").read_text())["outputs"]) == 2


@needs_runtime
async def test_a_react_native_eval_run_scores_each_output_with_its_agent_run(
    tmp_path: Path, backend: PlaywrightBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    import evals.config
    from evals.runner import run_image_evals
    from llm import Llm

    monkeypatch.setattr(evals.config, "EVALS_DIR", str(tmp_path))
    monkeypatch.setattr("evals.runner.EVALS_DIR", str(tmp_path))
    inputs = tmp_path / "sets" / "phones" / "inputs"
    inputs.mkdir(parents=True)
    Image.new("RGB", (1179, 2556), "#F2F2F7").save(inputs / "inbox.png")
    run_dir = tmp_path / "runs" / "run_1"
    run_dir.mkdir(parents=True)
    run: dict[str, Any] = {"run_id": "run_1", "total_duration_ms": 42000, "total_cost_usd": 0.12, "llm_calls": [{}, {}], "tool_calls": [{"name": "screenshot_preview"}]}
    (run_dir / "run.json").write_text(json.dumps(run))

    async def fake_generate(**kwargs: Any) -> str:
        kwargs["run_dirs"].append(str(run_dir))
        return APP

    monkeypatch.setattr("evals.runner.generate_code_for_image", fake_generate)

    outputs = await run_image_evals(stack="react_native", model=list(Llm)[0].value, eval_set="phones")

    assert outputs == ["inbox_0.html"]
    [metrics_path] = list((tmp_path / "results").glob("*/inbox_0.metrics.json"))
    metrics = json.loads(metrics_path.read_text())
    assert metrics["input"] == "inbox.png"
    assert metrics["image"]["compared_pt"] == [393, 759]  # the iPhone 16: 852 pt less 59 and 34 pt insets
    assert metrics["run"]["iterations"] == 1 and metrics["run"]["latency_s"] == 42.0 and metrics["run"]["cost_usd"] == 0.12
