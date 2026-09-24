"""The native bundling check, gate RNW-6 (Phase 4, task 4.3).

The fast tests replace npm and the Expo CLI. The real bundle runs only with
RN_BUNDLE_CHECK=1 (it needs Node, npm and about 400 MB on first run).
"""

import io
import json
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Any

import pytest

import config
from react_native import bundle_check
from react_native.bundle_check import check_bundle, error_lines, files_from_path, workspace_for

SDK: dict[str, Any] = json.loads((Path(__file__).resolve().parents[2] / "rn-runtime" / "expo-sdk.json").read_text())
FIXTURE = (Path(__file__).resolve().parents[2] / "rn-runtime" / "fixtures" / "App.jsx").read_text()


class FakeTools:
    """Stands in for npm install and npx expo export."""

    def __init__(self, export_ok: bool = True, log: str = "") -> None:
        self.commands: list[list[str]] = []
        self.export_ok = export_ok
        self.log = log
        self.seen_app: list[str] = []

    def __call__(self, command: list[str], cwd: Path, timeout: int) -> "subprocess.CompletedProcess[str]":
        self.commands.append(command)
        if command[:2] == ["npm", "install"]:
            (cwd / "node_modules").mkdir(exist_ok=True)
            return subprocess.CompletedProcess(command, 0, "added 503 packages", "")
        self.seen_app.append((cwd / "App.jsx").read_text())
        assert not (cwd / "assets.js").exists() or "assets.js" in self.log
        if self.export_ok:
            output = Path(command[command.index("--output-dir") + 1])
            for platform in ("ios", "android"):
                (output / "_expo/static/js" / platform).mkdir(parents=True)
                (output / "_expo/static/js" / platform / "index.hbc").write_bytes(b"hbc")
            return subprocess.CompletedProcess(command, 0, "iOS Bundled 40s index.js", "")
        return subprocess.CompletedProcess(command, 1, self.log, "")


def test_installs_once_then_bundles_each_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tools = FakeTools()
    monkeypatch.setattr(bundle_check, "_run", tools)

    first = check_bundle({"App.jsx": "export default () => null;\n"}, SDK, tmp_path)
    second = check_bundle({"App.jsx": "export default () => 1;\n"}, SDK, tmp_path)

    assert first.ok and second.ok and first.errors == []
    assert [command[:2] for command in tools.commands] == [["npm", "install"], ["npx", "expo"], ["npx", "expo"]]
    assert tools.commands[1][2:6] == ["export", "--platform", "ios", "--platform"]
    assert tools.seen_app == ["export default () => null;\n", "export default () => 1;\n"]
    workspace = workspace_for(SDK, tmp_path)
    assert json.loads((workspace / "package.json").read_text())["dependencies"] == SDK["dependencies"]
    assert "SafeAreaProvider" in (workspace / "index.js").read_text()


def test_a_stale_assets_module_is_removed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bundle_check, "_run", FakeTools(log="assets.js"))
    check_bundle({"App.jsx": "x", "assets.js": "export const ASSETS = {};\n"}, SDK, tmp_path)
    assert (workspace_for(SDK, tmp_path) / "assets.js").exists()
    monkeypatch.setattr(bundle_check, "_run", FakeTools())
    check_bundle({"App.jsx": "x"}, SDK, tmp_path)
    assert not (workspace_for(SDK, tmp_path) / "assets.js").exists()


def test_a_failed_bundle_reports_metros_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log = (
        "Starting Metro Bundler\n"
        "\x1b[31mError: Unable to resolve module react-native-maps from /w/App.jsx\x1b[39m\n"
        "  1 | import MapView from 'react-native-maps';\n"
    )
    monkeypatch.setattr(bundle_check, "_run", FakeTools(export_ok=False, log=log))
    result = check_bundle({"App.jsx": "import MapView from 'react-native-maps';"}, SDK, tmp_path)
    assert not result.ok
    assert result.errors == ["Error: Unable to resolve module react-native-maps from /w/App.jsx"]
    assert result.as_json()["ok"] is False


def test_error_lines_keep_syntax_errors_once() -> None:
    log = "SyntaxError: App.jsx: Unterminated JSX contents. (8:11)\nSyntaxError: App.jsx: Unterminated JSX contents. (8:11)\n"
    assert error_lines(log) == ["SyntaxError: App.jsx: Unterminated JSX contents. (8:11)"]


def test_projects_are_read_from_export_zips(tmp_path: Path) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("app/App.jsx", "A")
        archive.writestr("app/assets.js", "B")
        archive.writestr("app/package.json", "{}")
    zip_path = tmp_path / "export.zip"
    zip_path.write_bytes(buffer.getvalue())
    assert files_from_path(zip_path) == {"App.jsx": "A", "assets.js": "B"}


@pytest.mark.skipif(
    not config.RN_BUNDLE_CHECK or shutil.which("npx") is None,
    reason="set RN_BUNDLE_CHECK=1 to bundle for real (needs Node, npm and registry access)",
)
def test_rnw6_the_fixture_bundles_and_a_missing_module_does_not() -> None:
    passed = check_bundle({"App.jsx": FIXTURE.replace("__ASSET_BASE__", "http://127.0.0.1:7001")})
    assert passed.ok, passed.log_tail
    failed = check_bundle({"App.jsx": "import MapView from 'react-native-maps';\nexport default () => <MapView />;\n"})
    assert not failed.ok
    assert any("react-native-maps" in line for line in failed.errors)
