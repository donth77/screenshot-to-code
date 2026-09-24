"""Native bundling check, gate RNW-6 (DESIGN.md §13.3).

Bundles an exported Expo project for iOS and Android with
`npx expo export --platform ios --platform android`: the check the web
preview can't make (imports that don't exist natively, syntax Metro rejects).
Projects share one cached workspace per set of pins, so node_modules is
installed once (about 400 MB, 35 s) and Metro's cache stays warm; a lock
runs one bundle at a time.

    cd backend && poetry run python -m react_native.bundle_check App.jsx [more.jsx|export.zip ...]

Needs Node and npm (registry access for the first install).
"""

import argparse
import fcntl
import hashlib
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional

from react_native.expo_project import INDEX_JS, app_json, expo_sdk, package_json

# The files a check replaces in the workspace; the rest are the workspace's own.
PROJECT_SOURCES = ("App.jsx", "assets.js")
DEFAULT_TIMEOUT_S = 600
LOG_TAIL_LINES = 40
EXPORT_ENV = {"CI": "1", "EXPO_NO_TELEMETRY": "1", "EXPO_OFFLINE": "1"}
ERROR_LINE_RE = re.compile(r"(Unable to resolve|SyntaxError|Error:|error:|TransformError)")


@dataclass
class BundleResult:
    ok: bool
    seconds: float
    errors: list[str] = field(default_factory=lambda: list[str]())
    log_tail: str = ""

    def as_json(self) -> dict[str, Any]:
        return {"ok": self.ok, "seconds": round(self.seconds, 1), "errors": self.errors}


def default_workspace_root() -> Path:
    configured = os.environ.get("RN_BUNDLE_WORKSPACE")
    return Path(configured) if configured else Path.home() / ".cache" / "screenshot-to-code" / "expo-bundle-check"


def workspace_for(sdk: Mapping[str, Any], root: Optional[Path] = None) -> Path:
    """One workspace per set of pins, so a bump installs afresh."""
    digest = hashlib.sha256(package_json(sdk).encode("utf-8")).hexdigest()[:10]
    return (root or default_workspace_root()) / f"sdk-{str(sdk['sdk']).split('.')[0]}-{digest}"


def _run(command: list[str], cwd: Path, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env={**os.environ, **EXPORT_ENV},
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def ensure_workspace(workspace: Path, sdk: Mapping[str, Any], timeout: int = DEFAULT_TIMEOUT_S) -> None:
    """Write the project skeleton and install its dependencies once."""
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "package.json").write_text(package_json(sdk), encoding="utf-8")
    (workspace / "app.json").write_text(app_json(), encoding="utf-8")
    (workspace / "index.js").write_text(INDEX_JS, encoding="utf-8")
    stamp = workspace / ".installed"
    if stamp.exists() and (workspace / "node_modules").is_dir():
        return
    install = _run(["npm", "install", "--no-audit", "--no-fund"], workspace, timeout)
    if install.returncode != 0:
        raise RuntimeError(f"npm install failed in {workspace}:\n{install.stderr[-2000:]}")
    stamp.write_text(time.strftime("%Y-%m-%dT%H:%M:%S"), encoding="utf-8")


def error_lines(log: str) -> list[str]:
    """The lines that say what went wrong, without ANSI colours."""
    plain = re.sub(r"\x1b\[[0-9;]*m", "", log)
    found: list[str] = []
    for line in plain.splitlines():
        line = line.strip()
        if ERROR_LINE_RE.search(line) and line not in found:
            found.append(line[:500])
    return found[:10]


def check_bundle(
    files: Mapping[str, str],
    sdk: Optional[Mapping[str, Any]] = None,
    workspace_root: Optional[Path] = None,
    timeout: int = DEFAULT_TIMEOUT_S,
) -> BundleResult:
    """Bundle one exported project (its App.jsx and assets.js) for iOS and Android."""
    sdk = sdk or expo_sdk()
    workspace = workspace_for(sdk, workspace_root)
    workspace.mkdir(parents=True, exist_ok=True)
    with open(workspace.parent / f"{workspace.name}.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)  # one bundle at a time per workspace
        ensure_workspace(workspace, sdk, timeout)
        for name in PROJECT_SOURCES:
            path = workspace / name
            if name in files:
                path.write_text(files[name], encoding="utf-8")
            elif path.exists():
                path.unlink()
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="expo-export-") as output:
            try:
                result = _run(
                    ["npx", "expo", "export", "--platform", "ios", "--platform", "android", "--output-dir", output],
                    workspace,
                    timeout,
                )
                log = f"{result.stdout}\n{result.stderr}"
                bundles = list(Path(output).glob("_expo/static/js/*/*"))
                ok = result.returncode == 0 and {path.parent.name for path in bundles} >= {"ios", "android"}
            except subprocess.TimeoutExpired as exc:
                log, ok = f"timed out after {timeout} s\n{exc.stdout or ''}", False
        seconds = time.monotonic() - started
    tail = "\n".join(log.strip().splitlines()[-LOG_TAIL_LINES:])
    return BundleResult(ok=ok, seconds=seconds, errors=[] if ok else error_lines(log) or [tail[-500:]], log_tail=tail)


def files_from_path(path: Path) -> dict[str, str]:
    """A project's sources from an App.jsx (or eval .jsx output) or an export zip."""
    if path.suffix == ".zip":
        with zipfile.ZipFile(io.BytesIO(path.read_bytes())) as archive:
            return {
                Path(name).name: archive.read(name).decode("utf-8")
                for name in archive.namelist()
                if Path(name).name in PROJECT_SOURCES
            }
    return {"App.jsx": path.read_text(encoding="utf-8")}


def main() -> None:
    parser = argparse.ArgumentParser(description="Bundle React Native App.jsx files for iOS and Android (RNW-6).")
    parser.add_argument("paths", nargs="+", type=Path, help="App.jsx files, eval .jsx outputs or Expo export zips")
    args = parser.parse_args()
    if shutil.which("npx") is None:
        sys.exit("npx not found: install Node.js")
    failures = 0
    for path in args.paths:
        result = check_bundle(files_from_path(path))
        failures += 0 if result.ok else 1
        print(f"{'PASS' if result.ok else 'FAIL'} {path} ({result.seconds:.0f} s)")
        for line in result.errors:
            print(f"    {line}")
    print(f"{len(args.paths) - failures}/{len(args.paths)} bundled")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
