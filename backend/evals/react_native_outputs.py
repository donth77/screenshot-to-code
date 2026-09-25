"""What a React Native eval writes for each output (DESIGN.md §11.3).

``<name>_<n>.html`` is a preview page that loads the runtime from the backend,
so the eval pages keep working through iframes. Next to it: the App.jsx
(``.jsx``), its render at the input's device profile (``.png``), and the
render's status and runtime errors (``.json``). With RN_BUNDLE_CHECK on, the
report also says whether the output bundles for iOS and Android (RNW-6).
Given the input screenshot, ``.metrics.json`` scores the output
(react_native_metrics.py).
"""

import asyncio
import json
import os
from typing import Any, Mapping, Optional

import config
from config import LOCAL_ASSET_BASE_URL
from evals.react_native_metrics import probe_top_band, write_output_metrics
from preview_screenshot import capture_react_native_preview
from react_native.bundle_check import check_bundle
from react_native.render import preview_page
from react_native.runtime_files import load_runtime


async def write_react_native_outputs(
    html_path: str,
    source: str,
    profile: Mapping[str, Any],
    input_png: Optional[str] = None,
    run_dir: Optional[str] = None,
) -> dict[str, Any]:
    bundle = load_runtime()
    if bundle is None:
        raise RuntimeError("rn-runtime is not built (cd rn-runtime && pnpm build)")
    base = os.path.splitext(html_path)[0]
    with open(base + ".jsx", "w", encoding="utf-8") as f:
        f.write(source)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(preview_page(bundle, source, profile, LOCAL_ASSET_BASE_URL))

    render = await capture_react_native_preview(source, profile, inspect=probe_top_band)
    if render.png:
        with open(base + ".png", "wb") as f:
            f.write(render.png)
    report: dict[str, Any] = {
        "status": render.status,
        "runtime_errors": render.runtime_errors,
        "ready_ms": render.ready_ms,
        "profile": dict(profile),
        "top_band": render.extra.get("top_band"),
    }
    if config.RN_BUNDLE_CHECK:
        # Assets don't affect bundling: URLs are strings to Metro.
        report["native_bundle"] = (await asyncio.to_thread(check_bundle, {"App.jsx": source})).as_json()
    with open(base + ".json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    if input_png is not None:
        write_output_metrics(base, input_png, run_dir, report)
    return report
