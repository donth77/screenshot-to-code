"""Metrics for React Native eval outputs (DESIGN.md §14, PLAN.md 5.3).

For each output ``<name>_<n>`` (written by react_native_outputs.py), this
compares the render with the input screenshot and summarizes the render
report and the agent run into ``<name>_<n>.metrics.json``:

- ``image``: SSIM and mean absolute pixel difference between the input's
  content area (cropped as the model saw it) and the render, in pure NumPy.
  Both are compared at logical points (pixels / scale), so every device
  counts alike and subpixel text antialiasing matters less.
- ``errors``: render status, error kinds, native-compat lint rules, and
  unknown imports, icons and exports.
- ``fake_status_bar``: a clock or battery/wifi/signal icons drawn in the top
  60 pt of the screen. The system bar is outside the content area, so App.jsx
  must not draw one (a heuristic; see ``fake_status_bar``).
- ``native_bundle``: whether the output bundles for iOS and Android (RNW-6),
  when the eval ran with RN_BUNDLE_CHECK.
- ``run``: LLM calls, screenshot_preview calls (refinement iterations),
  latency, tokens and cost from the run recorder (PROMPT_REPORTS_ENABLED).

``aggregate`` rolls a results folder up into rates and averages, and
``python -m evals.react_native_metrics <results folder> --inputs <dir>``
(re)computes everything for an existing folder and writes report.json and
report.md.
"""

import argparse
import asyncio
import json
import os
import re
import statistics
from collections import Counter
from typing import Any, Mapping, Optional, Sequence

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from react_native.profiles import load_device_table, read_screenshot

# Renders and crops round the content height to whole pixels differently;
# larger differences mean the profile doesn't match the input.
SIZE_TOLERANCE_PX = 2
# SSIM per Wang et al. (2004): an 11-tap Gaussian window with sigma 1.5.
SSIM_WINDOW = 11
SSIM_SIGMA = 1.5
STATUS_BAR_BAND_PT = 60

# A status-bar clock: "9:41", "12:30 PM". Times inside longer text (a chat's
# "Today 9:41") don't count.
CLOCK_RE = re.compile(r"^(?:[01]?\d|2[0-3]):[0-5]\d(?:\s?[AaPp]\.?[Mm]\.?)?$")
# lucide icon families a fake status bar uses (battery-full, wifi-high, ...).
STATUS_ICON_FAMILIES = ("battery", "wifi", "signal")

# Error kinds from the preview (rn-runtime/src) and render.py.
RUNTIME_ERROR_KINDS = ("runtime", "uncaught", "module", "transform", "runtime_load", "no_default_export", "timeout")

FloatArray = NDArray[np.floating[Any]]


# ---------------------------------------------------------------- image metrics


def _gaussian_kernel(size: int = SSIM_WINDOW, sigma: float = SSIM_SIGMA) -> FloatArray:
    x = np.arange(size, dtype=np.float64) - (size - 1) / 2
    kernel = np.exp(-(x**2) / (2 * sigma**2))
    return kernel / kernel.sum()


def _filter_valid(image: FloatArray, kernel: FloatArray) -> FloatArray:
    """Separable 2-D filtering, keeping only fully covered positions."""
    n = len(kernel)
    height, width = image.shape
    rows = sum(kernel[i] * image[:, i : width - n + 1 + i] for i in range(n))
    return sum(kernel[i] * rows[i : height - n + 1 + i, :] for i in range(n))  # type: ignore[return-value]


def ssim(a: FloatArray, b: FloatArray, data_range: float = 255.0) -> float:
    """Mean SSIM of two same-size grayscale images."""
    if a.shape != b.shape:
        raise ValueError(f"shape mismatch: {a.shape} vs {b.shape}")
    if min(a.shape) < SSIM_WINDOW:
        raise ValueError(f"images must be at least {SSIM_WINDOW} px on each side")
    kernel = _gaussian_kernel()
    c1 = (0.01 * data_range) ** 2
    c2 = (0.03 * data_range) ** 2
    mu_a = _filter_valid(a, kernel)
    mu_b = _filter_valid(b, kernel)
    var_a = _filter_valid(a * a, kernel) - mu_a**2
    var_b = _filter_valid(b * b, kernel) - mu_b**2
    cov = _filter_valid(a * b, kernel) - mu_a * mu_b
    ssim_map = ((2 * mu_a * mu_b + c1) * (2 * cov + c2)) / ((mu_a**2 + mu_b**2 + c1) * (var_a + var_b + c2))
    return float(ssim_map.mean())


def _rgb(image: Image.Image) -> Image.Image:
    if image.mode in ("RGBA", "LA", "P"):
        rgba = image.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        return Image.alpha_composite(background, rgba).convert("RGB")
    return image.convert("RGB")


def compare_images(reference: Image.Image, render: Image.Image, scale: float) -> dict[str, Any]:
    """SSIM and mean absolute difference of two screens of (nearly) one size.

    Sizes may differ by SIZE_TOLERANCE_PX; both are cropped to the common
    size from the top left. Returns ``{"error": ...}`` otherwise.
    """
    delta = [render.width - reference.width, render.height - reference.height]
    result: dict[str, Any] = {"reference_px": [reference.width, reference.height], "render_px": [render.width, render.height]}
    if max(abs(d) for d in delta) > SIZE_TOLERANCE_PX:
        return {**result, "error": f"size mismatch of {delta[0]} x {delta[1]} px"}
    width, height = min(reference.width, render.width), min(reference.height, render.height)
    points = (max(1, round(width / scale)), max(1, round(height / scale)))
    pair = [_rgb(image).crop((0, 0, width, height)).resize(points, Image.Resampling.BOX) for image in (reference, render)]
    rgb = [np.asarray(image, dtype=np.float64) for image in pair]
    gray = [np.asarray(image.convert("L"), dtype=np.float64) for image in pair]
    try:
        score = ssim(gray[0], gray[1])
    except ValueError as error:
        return {**result, "error": str(error)}
    return {
        **result,
        "compared_pt": list(points),
        "ssim": round(score, 4),
        # 0 (identical) to 1 (black vs white), over RGB channels.
        "mean_abs_diff": round(float(np.abs(rgb[0] - rgb[1]).mean()) / 255, 4),
    }


def reference_content(screenshot: Image.Image) -> Image.Image:
    """The input's content area, cropped exactly as the eval prompt crops it."""
    cropped, _ = read_screenshot(screenshot, load_device_table())
    return cropped


# ------------------------------------------------------------------ fake status bar

# Visible text and lucide icons within the top band of the rendered screen.
TOP_BAND_JS = """(band) => {
  const inView = (r) => r.width > 0 && r.height > 0 && r.top < band && r.bottom > 0
    && r.left < window.innerWidth && r.right > 0;
  const texts = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const range = document.createRange();
  for (let node = walker.nextNode(); node && texts.length < 50; node = walker.nextNode()) {
    const text = node.textContent.trim();
    if (!text) continue;
    range.selectNodeContents(node);
    const r = range.getBoundingClientRect();
    if (inView(r)) texts.push({ text: text.slice(0, 80), x: Math.round(r.left), y: Math.round(r.top) });
  }
  const icons = [];
  for (const svg of document.querySelectorAll('svg')) {
    const match = /\\blucide-([a-z0-9-]+)/.exec(svg.getAttribute('class') || '');
    if (!match || icons.length >= 50) continue;
    const r = svg.getBoundingClientRect();
    if (inView(r)) icons.push({ name: match[1], x: Math.round(r.left), y: Math.round(r.top) });
  }
  return { band, texts, icons };
}"""


async def probe_top_band(page: Any) -> dict[str, Any]:
    """A render_preview inspector: what's drawn in the top STATUS_BAR_BAND_PT."""
    return {"top_band": await page.evaluate(TOP_BAND_JS, STATUS_BAR_BAND_PT)}


def fake_status_bar(top_band: Optional[Mapping[str, Any]]) -> dict[str, Any]:
    """Whether the screen draws its own status bar.

    Flags a clock on its own, or icons from two of the battery, wifi and
    signal families (one alone could be a settings row). None when the
    render wasn't probed.
    """
    if top_band is None:
        return {"detected": None}
    clocks = [t["text"] for t in top_band.get("texts", []) if CLOCK_RE.match(str(t.get("text", "")))]
    families = sorted(
        {
            family
            for icon in top_band.get("icons", [])
            for family in STATUS_ICON_FAMILIES
            if str(icon.get("name", "")).startswith(family)
        }
    )
    return {"detected": bool(clocks) or len(families) >= 2, "clock_text": clocks, "icon_families": families}


# ------------------------------------------------------------------- render report


def error_metrics(report: Mapping[str, Any]) -> dict[str, Any]:
    """Summarize a render report's status and runtime_errors.

    Counts are of distinct errors, capped by render.py's MAX_RUNTIME_ERRORS.
    """
    errors: list[Mapping[str, Any]] = list(report.get("runtime_errors") or [])
    kinds = Counter(str(e.get("kind")) for e in errors)
    rules = Counter(str(e.get("rule")) for e in errors if e.get("kind") == "native_compat")
    status = report.get("status")
    return {
        "status": status,
        "renders": status in ("ok", "degraded"),
        "fatal": status in ("error", "timeout") or any(bool(e.get("fatal")) for e in errors),
        "error_kinds": dict(sorted(kinds.items())),
        "native_compat_rules": dict(sorted(rules.items())),
        "runtime_error": any(kinds[k] for k in RUNTIME_ERROR_KINDS),
        "native_compat": kinds["native_compat"] > 0,
        "unknown_import": kinds["import"] > 0,
        "unknown_icon": kinds["unknown_icon"] > 0,
        "unknown_export": kinds["unknown_export"] > 0,
        "ready_ms": report.get("ready_ms"),
    }


# ----------------------------------------------------------------------- agent run


def run_metrics(run: Optional[Mapping[str, Any]]) -> Optional[dict[str, Any]]:
    """Iterations, latency, tokens and cost from a recorder run.json."""
    if run is None:
        return None
    llm_calls: list[Mapping[str, Any]] = list(run.get("llm_calls") or [])
    tool_calls: list[Mapping[str, Any]] = list(run.get("tool_calls") or [])
    tool_names = Counter(str(call.get("name")) for call in tool_calls)
    tokens: Counter[str] = Counter()
    for call in llm_calls:
        usage: Mapping[str, Any] = call.get("usage") or {}
        for key, value in usage.items():
            tokens[key] += int(value or 0)
    duration_ms = run.get("total_duration_ms")
    return {
        "run_id": run.get("run_id"),
        "model": run.get("model"),
        "status": run.get("status"),
        "llm_calls": len(llm_calls),
        "tool_calls": dict(sorted(tool_names.items())),
        "iterations": tool_names["screenshot_preview"],
        "edits": tool_names["edit_file"],
        "latency_s": round(duration_ms / 1000, 1) if isinstance(duration_ms, (int, float)) else None,
        "tokens": dict(tokens),
        "cost_usd": run.get("total_cost_usd"),
        "has_unpriced_calls": bool(run.get("has_unpriced_calls")),
    }


def load_run(run_dir: Optional[str]) -> Optional[dict[str, Any]]:
    if not run_dir:
        return None
    path = os.path.join(run_dir, "run.json")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# -------------------------------------------------------------------- per output


def output_metrics(
    report: Mapping[str, Any],
    render_png: Optional[str],
    input_png: Optional[str],
    run: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """All metrics for one output, from its render report and files."""
    image: dict[str, Any]
    if not input_png or not os.path.exists(input_png):
        image = {"error": "input screenshot not found"}
    elif not render_png or not os.path.exists(render_png):
        image = {"error": "no render"}
    else:
        with Image.open(input_png) as screenshot, Image.open(render_png) as render:
            scale = float((report.get("profile") or {}).get("scale") or 1)
            image = compare_images(reference_content(screenshot), render, scale)
    bundle = report.get("native_bundle")
    return {
        "image": image,
        "errors": error_metrics(report),
        "fake_status_bar": fake_status_bar(report.get("top_band")),
        "native_bundle": None if bundle is None else bool(bundle.get("ok")),
        "run": run_metrics(run),
    }


def write_output_metrics(
    base_path: str,
    input_png: Optional[str],
    run_dir: Optional[str] = None,
    report: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Compute and write ``<base>.metrics.json`` next to ``<base>.json``."""
    if report is None:
        with open(base_path + ".json", encoding="utf-8") as f:
            report = json.load(f)
    assert report is not None
    metrics: dict[str, Any] = {
        "output": os.path.basename(base_path),
        "input": os.path.basename(input_png) if input_png else None,
        **output_metrics(report, base_path + ".png", input_png, load_run(run_dir)),
    }
    with open(base_path + ".metrics.json", "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)
    return metrics


# ----------------------------------------------------------------------- aggregate


def _rate(values: Sequence[Optional[bool]]) -> Optional[dict[str, Any]]:
    known = [v for v in values if v is not None]
    if not known:
        return None
    return {"rate": round(sum(known) / len(known), 3), "count": sum(known), "of": len(known)}


def _summary(values: Sequence[Optional[float]]) -> Optional[dict[str, Any]]:
    known = [float(v) for v in values if v is not None]
    if not known:
        return None
    return {
        "mean": round(statistics.fmean(known), 4),
        "median": round(statistics.median(known), 4),
        "min": round(min(known), 4),
        "max": round(max(known), 4),
        "of": len(known),
    }


def aggregate(outputs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Roll per-output metrics up into rates and averages."""
    errors = [o["errors"] for o in outputs]
    runs = [o["run"] for o in outputs if o.get("run")]
    lint_rules: Counter[str] = Counter()
    for e in errors:
        lint_rules.update(e["native_compat_rules"].keys())
    costs = [r["cost_usd"] for r in runs if r.get("cost_usd") is not None]
    return {
        "outputs": len(outputs),
        "ssim": _summary([o["image"].get("ssim") for o in outputs]),
        "mean_abs_diff": _summary([o["image"].get("mean_abs_diff") for o in outputs]),
        "image_not_compared": sum(1 for o in outputs if "error" in o["image"]),
        "renders": _rate([e["renders"] for e in errors]),
        "clean_render": _rate([e["status"] == "ok" for e in errors]),
        "fatal": _rate([e["fatal"] for e in errors]),
        "runtime_error": _rate([e["runtime_error"] for e in errors]),
        "native_compat": _rate([e["native_compat"] for e in errors]),
        "native_compat_rules": dict(lint_rules.most_common()),
        "unknown_import": _rate([e["unknown_import"] for e in errors]),
        "unknown_icon": _rate([e["unknown_icon"] for e in errors]),
        "unknown_export": _rate([e["unknown_export"] for e in errors]),
        "fake_status_bar": _rate([o["fake_status_bar"]["detected"] for o in outputs]),
        "native_bundle": _rate([o.get("native_bundle") for o in outputs]),
        "iterations": _summary([r["iterations"] for r in runs]),
        "llm_calls": _summary([r["llm_calls"] for r in runs]),
        "latency_s": _summary([r["latency_s"] for r in runs]),
        "cost_usd": None if not costs else {**(_summary(costs) or {}), "total": round(sum(costs), 4)},
        "has_unpriced_calls": any(r["has_unpriced_calls"] for r in runs),
        "runs_recorded": len(runs),
    }


def _format_rate(value: Optional[Mapping[str, Any]]) -> str:
    if value is None:
        return "n/a"
    return f"{value['rate'] * 100:.0f}% ({value['count']}/{value['of']})"


def _format_summary(value: Optional[Mapping[str, Any]], digits: int = 3) -> str:
    if value is None:
        return "n/a"
    return f"{value['mean']:.{digits}f} mean, {value['median']:.{digits}f} median ({value['min']:.{digits}f}–{value['max']:.{digits}f}, n={value['of']})"


def format_markdown(report: Mapping[str, Any], title: str) -> str:
    """The aggregate as a Markdown table, for EVALS.md."""
    rows = [
        ("Outputs", str(report["outputs"])),
        ("SSIM (higher is better)", _format_summary(report["ssim"])),
        ("Mean abs. pixel diff (lower is better)", _format_summary(report["mean_abs_diff"])),
        ("Not compared (size mismatch or no render)", str(report["image_not_compared"])),
        ("Renders (ok or degraded)", _format_rate(report["renders"])),
        ("Clean render (ok, no errors)", _format_rate(report["clean_render"])),
        ("Fatal errors", _format_rate(report["fatal"])),
        ("Runtime errors", _format_rate(report["runtime_error"])),
        ("Native-compat lint findings", _format_rate(report["native_compat"])),
        ("Unknown imports", _format_rate(report["unknown_import"])),
        ("Unknown icons", _format_rate(report["unknown_icon"])),
        ("Unknown react-native exports", _format_rate(report["unknown_export"])),
        ("Fake status bar", _format_rate(report["fake_status_bar"])),
        ("Bundles for iOS and Android (RNW-6)", _format_rate(report["native_bundle"])),
        ("screenshot_preview iterations", _format_summary(report["iterations"], 1)),
        ("LLM calls", _format_summary(report["llm_calls"], 1)),
        ("Latency (s)", _format_summary(report["latency_s"], 1)),
        (
            "Cost (USD)",
            "n/a"
            if report["cost_usd"] is None
            else f"{report['cost_usd']['total']:.2f} total, {report['cost_usd']['mean']:.3f} mean"
            + (" (some calls unpriced)" if report["has_unpriced_calls"] else ""),
        ),
    ]
    lines = [f"## {title}", "", "| Metric | Value |", "| --- | --- |"]
    lines += [f"| {name} | {value} |" for name, value in rows]
    if report["native_compat_rules"]:
        rules = ", ".join(f"{rule} ({count})" for rule, count in report["native_compat_rules"].items())
        lines += ["", f"Lint rules hit (outputs per rule): {rules}."]
    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------------------- CLI

_OUTPUT_NAME_RE = re.compile(r"^(?P<stem>.+)_(?P<attempt>\d+)$")


def _input_for(stem: str, inputs_dir: Optional[str]) -> Optional[str]:
    if not inputs_dir:
        return None
    path = os.path.join(inputs_dir, stem + ".png")
    return path if os.path.exists(path) else None


async def _probe_missing_top_band(base: str, report: dict[str, Any]) -> None:
    """Older outputs weren't probed at render time: render App.jsx again."""
    from preview_screenshot import capture_react_native_preview

    with open(base + ".jsx", encoding="utf-8") as f:
        source = f.read()
    render = await capture_react_native_preview(source, report["profile"], inspect=probe_top_band)
    report["top_band"] = render.extra.get("top_band")


async def report_folder(results_dir: str, inputs_dir: Optional[str], probe: bool = True) -> dict[str, Any]:
    """(Re)compute metrics for every React Native output in a results folder."""
    outputs: list[dict[str, Any]] = []
    for name in sorted(os.listdir(results_dir)):
        if not name.endswith(".jsx"):
            continue
        base = os.path.join(results_dir, name[: -len(".jsx")])
        match = _OUTPUT_NAME_RE.match(os.path.basename(base))
        if not match or not os.path.exists(base + ".json"):
            continue
        with open(base + ".json", encoding="utf-8") as f:
            report = json.load(f)
        if probe and "top_band" not in report and report.get("profile"):
            await _probe_missing_top_band(base, report)
        previous_run: Optional[str] = None
        if os.path.exists(base + ".metrics.json"):
            with open(base + ".metrics.json", encoding="utf-8") as f:
                previous: dict[str, Any] = json.load(f)
            previous_run_metrics: Mapping[str, Any] = previous.get("run") or {}
            previous_run = previous_run_metrics.get("run_id")
        run_dir = _run_dir(previous_run)
        outputs.append(write_output_metrics(base, _input_for(match.group("stem"), inputs_dir), run_dir, report))
    summary: dict[str, Any] = {"results_dir": os.path.abspath(results_dir), **aggregate(outputs)}
    with open(os.path.join(results_dir, "report.json"), "w", encoding="utf-8") as f:
        json.dump({"aggregate": summary, "outputs": outputs}, f, indent=2)
    with open(os.path.join(results_dir, "report.md"), "w", encoding="utf-8") as f:
        f.write(format_markdown(summary, os.path.basename(os.path.normpath(results_dir))))
    return summary


def _run_dir(run_id: Optional[str]) -> Optional[str]:
    if not run_id:
        return None
    from fs_logging.agent_runs import get_agent_runs_directory

    return os.path.join(get_agent_runs_directory(), run_id)


def main(argv: Optional[Sequence[str]] = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument("results_dir", help="an eval results folder (evals_data/results/<run>)")
    parser.add_argument("--inputs", help="the input screenshots' folder (for SSIM and pixel difference)")
    parser.add_argument("--no-probe", action="store_true", help="don't re-render outputs to look for fake status bars")
    args = parser.parse_args(argv)
    summary = asyncio.run(report_folder(args.results_dir, args.inputs, probe=not args.no_probe))
    print(format_markdown(summary, os.path.basename(os.path.normpath(args.results_dir))))


if __name__ == "__main__":
    main()
