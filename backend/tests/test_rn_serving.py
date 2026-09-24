"""/rn-runtime static serving and the react_native_preview capability."""

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from react_native.serving import IMMUTABLE, configure_runtime_routes
from routes.capabilities import get_capabilities


def client_for(dist_dir: Path) -> TestClient:
    app = FastAPI()
    configure_runtime_routes(app, str(dist_dir))
    return TestClient(app)


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    (tmp_path / "rn-runtime.0123456789ab.js").write_text("window.__RN_PREVIEW__ = {};")
    (tmp_path / "babel-standalone-7.25.6.ba5e0123beef.js").write_text("window.Babel = {};")
    (tmp_path / "manifest.json").write_text("{}")
    (tmp_path / "preview-template.html").write_text("<!doctype html>")
    return tmp_path


def test_hashed_files_are_immutable(dist: Path) -> None:
    client = client_for(dist)
    for name in ("rn-runtime.0123456789ab.js", "babel-standalone-7.25.6.ba5e0123beef.js"):
        response = client.get(f"/rn-runtime/{name}")
        assert response.status_code == 200
        assert response.headers["cache-control"] == IMMUTABLE
        assert response.headers["content-type"].startswith("text/javascript")


def test_unhashed_files_are_revalidated(dist: Path) -> None:
    client = client_for(dist)
    for name in ("manifest.json", "preview-template.html"):
        response = client.get(f"/rn-runtime/{name}")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-cache"


def test_missing_build_is_a_404_not_a_500(tmp_path: Path) -> None:
    client = client_for(tmp_path / "not-built")
    assert client.get("/rn-runtime/manifest.json").status_code == 404


def test_paths_outside_dist_are_not_served(dist: Path) -> None:
    (dist.parent / "secret.txt").write_text("no")
    client = client_for(dist)
    assert client.get("/rn-runtime/../secret.txt").status_code == 404
    assert client.get("/rn-runtime/%2e%2e/secret.txt").status_code == 404


@pytest.mark.parametrize("built", [True, False])
async def test_capabilities_report_whether_the_runtime_is_built(monkeypatch: pytest.MonkeyPatch, built: bool) -> None:
    async def probe() -> bool:
        return False

    monkeypatch.setattr("routes.capabilities.probe_screenshot_preview", probe)
    bundle: Any = object() if built else None
    monkeypatch.setattr("routes.capabilities.load_runtime", lambda: bundle)
    assert (await get_capabilities()).react_native_preview is built
