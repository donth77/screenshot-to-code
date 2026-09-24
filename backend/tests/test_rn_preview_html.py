import json
import os
import time
from pathlib import Path
from typing import Any

import pytest

from react_native.preview_html import (
    inline_script,
    preview_config_json,
    render_preview_html,
    script_tags,
)
from react_native.runtime_files import load_runtime

VECTORS_PATH = Path(__file__).resolve().parents[2] / "rn-runtime" / "test-vectors" / "preview-html.json"
VECTORS: dict[str, Any] = json.loads(VECTORS_PATH.read_text(encoding="utf-8"))


def _ids(group: str) -> list[str]:
    return [str(case["name"]) for case in VECTORS[group]]


@pytest.mark.parametrize("case", VECTORS["configJson"], ids=_ids("configJson"))
def test_config_json_matches_shared_vectors(case: dict[str, Any]) -> None:
    assert preview_config_json(case["source"], case["profile"], case["mode"]) == case["expected"]


@pytest.mark.parametrize("case", VECTORS["inlineScript"], ids=_ids("inlineScript"))
def test_inline_script_matches_shared_vectors(case: dict[str, Any]) -> None:
    assert inline_script(case["js"]) == case["expected"]


@pytest.mark.parametrize("case", VECTORS["scriptTags"], ids=_ids("scriptTags"))
def test_script_tags_match_shared_vectors(case: dict[str, Any]) -> None:
    assert script_tags(case["baseUrl"], case["runtime"], case["babel"]) == case["expected"]


@pytest.mark.parametrize("case", VECTORS["render"], ids=_ids("render"))
def test_render_matches_shared_vectors(case: dict[str, Any]) -> None:
    assert render_preview_html(case["template"], case["configJson"], case["scripts"]) == case["expected"]


@pytest.mark.parametrize("case", VECTORS["renderErrors"], ids=_ids("renderErrors"))
def test_render_rejects_templates_without_exactly_one_of_each_placeholder(case: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        render_preview_html(case["template"], "{}", "")


def test_config_json_round_trips_and_never_closes_its_script() -> None:
    source = "const s = '</script><!--';\nexport default function App() { return null; }\n"
    profile: dict[str, Any] = {"platform": "ios", "width": 390, "height": 751, "scale": 3.0}
    text = preview_config_json(source, profile)
    assert "<" not in text
    assert json.loads(text) == {"source": source, "profile": {**profile, "scale": 3}, "mode": "final"}


def test_config_json_rejects_non_finite_numbers() -> None:
    with pytest.raises(ValueError):
        preview_config_json("", {"scale": float("nan")})


def _write_dist(directory: Path, runtime_name: str = "rn-runtime.aaa.js") -> None:
    directory.mkdir(parents=True, exist_ok=True)
    files = {
        runtime_name: "window.x=1;",
        "babel.js": "window.Babel={};",
        "preview-template.html": "__RN_PREVIEW_CONFIG__<!--RN_PREVIEW_SCRIPTS-->",
        "expo-sdk.json": "{}",
        "device-profiles.json": "{}",
    }
    for name, content in files.items():
        (directory / name).write_text(content, encoding="utf-8")
    manifest = {
        "runtime": runtime_name,
        "babel": "babel.js",
        "template": "preview-template.html",
        "expoSdk": "expo-sdk.json",
        "deviceProfiles": "device-profiles.json",
    }
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_load_runtime_returns_none_without_a_build(tmp_path: Path) -> None:
    assert load_runtime(str(tmp_path / "missing")) is None


def test_load_runtime_returns_none_when_a_listed_file_is_missing(tmp_path: Path) -> None:
    _write_dist(tmp_path)
    (tmp_path / "babel.js").unlink()
    assert load_runtime(str(tmp_path)) is None


def test_load_runtime_reads_manifest_and_template(tmp_path: Path) -> None:
    _write_dist(tmp_path)
    bundle = load_runtime(str(tmp_path))
    assert bundle is not None
    assert bundle.runtime_file == "rn-runtime.aaa.js"
    assert bundle.babel_file == "babel.js"
    assert "__RN_PREVIEW_CONFIG__" in bundle.template
    with pytest.raises(ValueError):
        bundle.path("../manifest.json")


def test_load_runtime_notices_a_rebuild(tmp_path: Path) -> None:
    _write_dist(tmp_path)
    first = load_runtime(str(tmp_path))
    assert first is not None and first.runtime_file == "rn-runtime.aaa.js"
    _write_dist(tmp_path, runtime_name="rn-runtime.bbb.js")
    later = time.time() + 5
    os.utime(tmp_path / "manifest.json", (later, later))
    second = load_runtime(str(tmp_path))
    assert second is not None and second.runtime_file == "rn-runtime.bbb.js"
