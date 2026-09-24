"""The Expo project export (Phase 4, tasks 4.1 and 4.2)."""

import io
import json
import zipfile
from pathlib import Path
from typing import Any, Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from react_native.export_assets import embed_images, find_url_literals
from react_native.expo_project import APP_NAME, expo_sdk, project_files
from routes import expo_export

REPO_SDK = json.loads((Path(__file__).resolve().parents[2] / "rn-runtime" / "expo-sdk.json").read_text())


def png(color: str = "#6366F1") -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (4, 4), color).save(buffer, "PNG")
    return buffer.getvalue()


APP = """import React from 'react';
import {
  Image,
  Linking,
  Text,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

const AVATAR = 'http://127.0.0.1:7001/local-assets/avatar.png';
const HELP = 'https://example.com/help';
const DYNAMIC = `${BASE}/local-assets/avatar.png`;

export default function App() {
  return (
    <SafeAreaView testID="screen">
      <Image source={{ uri: AVATAR }} />
      <Image source={{ uri: "/local-assets/avatar.png" }} />
      <Image source={{ uri: 'https://replicate.delivery/xezq/out-0.webp' }} />
      <Image source={{ uri: 'https://example.com/missing.png' }} />
      <Thing onPress={() => go()} src="/local-assets/banner.jpg" />
      <Text onPress={() => Linking.openURL(HELP)}>Help</Text>
    </SafeAreaView>
  );
}
"""


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    (tmp_path / "avatar.png").write_bytes(png())
    jpeg = io.BytesIO()
    Image.new("RGB", (4, 4), "#F59E0B").save(jpeg, "JPEG")
    (tmp_path / "banner.jpg").write_bytes(jpeg.getvalue())
    monkeypatch.setattr(expo_export, "LOCAL_ASSET_DIR", str(tmp_path))

    async def fake_remote(_client: Any, url: str, _hint: str) -> Optional[tuple[bytes, str]]:
        if "replicate.delivery" in url:
            buffer = io.BytesIO()
            Image.new("RGB", (4, 4), "#10B981").save(buffer, "WEBP")
            return buffer.getvalue(), "webp"
        return None  # e.g. a 404

    monkeypatch.setattr(expo_export, "fetch_remote_asset", fake_remote)
    app = FastAPI()
    app.include_router(expo_export.router)
    return TestClient(app)


def export(client: TestClient, code: str) -> dict[str, str]:
    response = client.post("/api/export/expo", json={"code": code})
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        names = archive.namelist()
        assert all(name.startswith(f"{APP_NAME}/") for name in names)
        return {name.split("/", 1)[1]: archive.read(name).decode("utf-8") for name in names}


def test_the_project_is_an_expo_app_pinned_to_the_sdk(client: TestClient) -> None:
    files = export(client, "export default function App() { return null; }\n")
    assert set(files) == {"package.json", "app.json", "index.js", "App.jsx", "README.md", ".gitignore"}
    package = json.loads(files["package.json"])
    assert package["main"] == "index.js"
    assert package["dependencies"] == REPO_SDK["dependencies"]  # RNW-5: the runtime's pins
    assert package["scripts"]["start"] == "expo start"
    assert json.loads(files["app.json"])["expo"]["slug"] == APP_NAME
    assert "<SafeAreaProvider>" in files["index.js"] and "registerRootComponent(Root)" in files["index.js"]
    assert files["App.jsx"] == "export default function App() { return null; }\n"
    assert f"SDK {REPO_SDK['sdk'].split('.')[0]}" in files["README.md"]


def test_the_pins_come_from_the_runtime_when_it_is_built() -> None:
    assert expo_sdk()["dependencies"] == REPO_SDK["dependencies"]


def test_images_are_embedded_and_links_stay(client: TestClient) -> None:
    files = export(client, APP)
    app, assets = files["App.jsx"], files["assets.js"]

    # Every image literal became a reference; the avatar's two URLs share one entry.
    assert "import { ASSETS } from './assets';" in app
    assert app.index("import { ASSETS }") > app.index("from 'react-native-safe-area-context';")
    assert "const AVATAR = ASSETS.asset_" in app
    assert 'source={{ uri: ASSETS.asset_' in app
    assert "<Thing onPress={() => go()} src={ASSETS.asset_" in app  # a JSX attribute string gets braces
    assert "127.0.0.1:7001" not in app and "replicate.delivery" not in app
    assert assets.count("data:image/png;base64,") == 1
    assert assets.count("data:image/jpeg;base64,") == 1
    assert assets.count("data:image/webp;base64,") == 1

    # Links, unreachable images and interpolated templates stay as written.
    assert "const HELP = 'https://example.com/help';" in app
    assert "'https://example.com/missing.png'" in app
    assert "`${BASE}/local-assets/avatar.png`" in app
    assert "https://example.com/missing.png" in files["README.md"]


def test_a_missing_or_escaping_local_asset_is_not_read(client: TestClient) -> None:
    files = export(client, "const a = '/local-assets/nope.png';\nconst b = '/local-assets/../../etc/passwd';\n")
    assert "assets.js" not in files
    assert files["App.jsx"].startswith("const a = '/local-assets/nope.png';")


def test_a_file_without_imports_gets_the_import_first() -> None:
    async def fetch(_url: str) -> Optional[tuple[bytes, str]]:
        return png(), "image/png"

    import asyncio

    embedded = asyncio.run(embed_images("const a = 'https://x.test/a.png';\n", fetch))
    assert embedded.source.startswith("import { ASSETS } from './assets';\nconst a = ASSETS.asset_")


def test_find_url_literals_matches_the_frontend_rule() -> None:
    assert find_url_literals("a('https://x.test/a.png'); b(\"/local-assets/b.png\"); c(`${x}/c.png`); d('mailto:x')") == [
        "https://x.test/a.png",
        "/local-assets/b.png",
    ]


def test_project_files_without_assets_have_no_assets_module() -> None:
    files = project_files("export default () => null;\n", [], sdk=REPO_SDK)
    assert "assets.js" not in files
