"""React Native eval and run-recorder outputs.

Browser tests skip when rn-runtime isn't built or Chromium is missing.
"""

import io
import json
from pathlib import Path
from typing import Any, AsyncIterator

import pytest
from PIL import Image

from config import LOCAL_ASSET_BASE_URL
from evals.core import react_native_eval_profile
from evals.react_native_outputs import write_react_native_outputs
from fs_logging.agent_runs import AgentRunRecorder
from preview_screenshot import PlaywrightBackend
from react_native.profiles import encode_png
from react_native.runtime_files import load_runtime

BUILT = load_runtime() is not None
needs_runtime = pytest.mark.skipif(not BUILT, reason="rn-runtime is not built (cd rn-runtime && pnpm build)")
PROFILE: dict[str, Any] = {"platform": "android", "width": 412, "height": 841, "scale": 1080 / 412, "insets": {"top": 0, "right": 0, "bottom": 0, "left": 0}}
APP = """import React from 'react';
import { Text } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

export default function App() {
  return (
    <SafeAreaView testID="screen" style={{ flex: 1, backgroundColor: '#FFFFFF' }}>
      <Text>Inbox</Text>
    </SafeAreaView>
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
async def test_an_eval_output_is_a_preview_page_with_source_render_and_status(
    tmp_path: Path, backend: PlaywrightBackend
) -> None:
    html_path = tmp_path / "settings_0.html"

    report = await write_react_native_outputs(str(html_path), APP, PROFILE)

    assert (tmp_path / "settings_0.jsx").read_text() == APP
    page = html_path.read_text()
    assert f'src="{LOCAL_ASSET_BASE_URL.rstrip("/")}/rn-runtime/' in page  # the eval pages' iframes load it from the backend
    assert Image.open(io.BytesIO((tmp_path / "settings_0.png").read_bytes())).size == (1080, 2205)
    assert json.loads((tmp_path / "settings_0.json").read_text())["status"] == report["status"] == "ok"


@needs_runtime
async def test_a_react_native_run_records_its_jsx_and_a_preview_page(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOGS_PATH", str(tmp_path))
    recorder = AgentRunRecorder(
        generation_id="gen_test_00000000",
        variant_index=0,
        entry_point="websocket",
        stack="react_native",
        input_mode="image",
        generation_type="create",
        enabled=True,
    )

    await recorder.record_run_end("completed", final_html=APP, preview_profile=PROFILE)

    run_dir = Path(recorder.run_dir)
    assert (run_dir / "final.jsx").read_text() == APP
    assert (run_dir / "final_selfcontained.jsx").exists()
    page = (run_dir / "final.html").read_text()
    assert '"platform":"android"' in page and "rn-runtime/" in page
    assert not (run_dir / "final_selfcontained.html").exists()  # the viewer falls back to final.html


def test_an_eval_input_renders_at_its_screenshots_profile() -> None:
    table = json.loads((Path(__file__).resolve().parents[2] / "rn-runtime" / "device-profiles.json").read_text())
    pixel_8 = encode_png(Image.new("RGB", (1080, 2400), "#FFFFFF"))

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("evals.core.load_device_table", lambda: table)
        profile = react_native_eval_profile(pixel_8)
        default = react_native_eval_profile(None)

    assert (profile["platform"], profile["width"], profile["height"]) == ("android", 412, 841)
    assert (default["platform"], default["width"], default["height"]) == ("ios", 390, 763)
