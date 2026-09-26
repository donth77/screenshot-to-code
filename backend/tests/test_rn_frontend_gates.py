"""Gates RNW-2 and RNW-3 through the real app.

RNW-2: a React Native generation previews on the phone in the app served by
the Vite dev server. RNW-3: the preview HTML the app downloads renders from
file:// with no network.

Everything but the model is real: the frontend (Vite dev server), the
websocket route, prompts, agent engine, tool runtime, screenshot_preview's
Chromium renders and the /rn-runtime and /local-assets mounts. The model is
tests/rn_ui_harness.py's script: it streams the fixture App.jsx in through
create_file (one greeting per option), screenshots it, and edits the
greeting when asked.

Skipped when rn-runtime isn't built, the frontend's dependencies aren't
installed, or Chromium is missing.
"""

import asyncio
import json
import time
import zipfile
from pathlib import Path
from typing import Any, AsyncIterator, Iterator, cast
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageDraw
from playwright.async_api import Browser, BrowserContext, Page, Route, WebSocket

from preview_screenshot.playwright_backend import PlaywrightBackend
from react_native.runtime_files import load_runtime
from react_native.serving import configure_runtime_routes
import config
from react_native.bundle_check import check_bundle
from routes import capabilities, design_systems, expo_export, generate_code
from tests.dev_servers import READY_TIMEOUT_S, VITE, serve_app, vite_dev_server
from tests.rn_ui_harness import AVATAR_NAME, ScriptedModels, write_avatar

pytestmark = [
    pytest.mark.skipif(load_runtime() is None, reason="rn-runtime is not built (cd rn-runtime && pnpm build)"),
    pytest.mark.skipif(not VITE.exists(), reason="frontend dependencies are not installed (cd frontend && pnpm install)"),
]

GENERATION_TIMEOUT_S = 90
# The app's persisted settings: React Native, and a placeholder key so the
# backend picks models without reading real keys (the model is scripted).
SETTINGS: dict[str, Any] = {
    "openAiApiKey": "sk-scripted-gate-test",
    "openAiBaseURL": None,
    "replicateApiKey": None,
    "anthropicApiKey": None,
    "geminiApiKey": None,
    "screenshotOneApiKey": None,
    "isImageGenerationEnabled": False,
    "editorTheme": "cobalt",
    "generatedCodeConfig": "react_native",
    "codeGenerationModel": "gpt-4o-2024-05-13",
    "selectedDesignSystemId": None,
    "isTermOfServiceAccepted": True,
}
# Every rn-preview:status any preview frame posts, tagged with whether it
# came from the main phone preview.
RECORD_STATUSES = """
window.__rnStatuses = [];
window.addEventListener("message", (event) => {
  if (!event.data || event.data.type !== "rn-preview:status") return;
  const main = document.querySelector('[data-testid="rn-preview-frame"]');
  window.__rnStatuses.push({
    main: Boolean(main && event.source === main.contentWindow),
    status: event.data.status,
    renderId: event.data.renderId,
  });
});
"""
IPHONE_13_PROFILE: dict[str, Any] = {"platform": "ios", "width": 390, "height": 763, "scale": 3.0}


def iphone_screenshot(path: Path) -> Path:
    """A 1170 x 2532 (iPhone 13) screenshot: status bar, content, home indicator."""
    image = Image.new("RGB", (1170, 2532), "#F6F7FB")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 1169, 140), fill="#FFFFFF")
    draw.rectangle((90, 50, 230, 95), fill="#000000")
    draw.rectangle((900, 55, 1080, 90), fill="#000000")
    draw.ellipse((90, 230, 250, 390), fill="#86EFAC")
    draw.rectangle((400, 2480, 770, 2495), fill="#000000")
    image.save(path)
    return path


def gate_app(asset_dir: Path, screenshots: PlaywrightBackend) -> FastAPI:
    """The routes the app uses, with local assets in a temporary directory."""
    app = FastAPI()
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
    configure_runtime_routes(app)
    app.mount("/local-assets", StaticFiles(directory=asset_dir), name="local-assets")
    app.include_router(generate_code.router)
    app.include_router(capabilities.router)
    app.include_router(design_systems.router)
    app.include_router(expo_export.router)

    @app.on_event("shutdown")
    async def close_screenshot_browser() -> None:  # pyright: ignore[reportUnusedFunction]
        # screenshot_preview's Chromium started on this server's event loop.
        browser = getattr(screenshots, "_browser", None)
        playwright = getattr(screenshots, "_playwright", None)
        if browser is not None:
            await browser.close()
        if playwright is not None:
            await playwright.stop()

    return app


class GenerateCodeSocket:
    """The app's /generate-code websockets: what they sent and received."""

    def __init__(self, page: Page) -> None:
        self.sent: list[dict[str, Any]] = []
        self.received: list[dict[str, Any]] = []
        self.closed = 0
        page.on("websocket", self._attach)

    def _attach(self, ws: WebSocket) -> None:
        if "/generate-code" not in ws.url:
            return
        ws.on("framesent", lambda payload: self.sent.append(json.loads(payload)))
        ws.on("framereceived", lambda payload: self.received.append(json.loads(payload)))
        ws.on("close", lambda _: self._closed())

    def _closed(self) -> None:
        self.closed += 1

    async def wait_closed(self, count: int) -> None:
        deadline = time.monotonic() + GENERATION_TIMEOUT_S
        while self.closed < count:
            if time.monotonic() > deadline:
                raise TimeoutError(f"generation {count} did not finish within {GENERATION_TIMEOUT_S} s")
            await asyncio.sleep(0.1)

    def screenshot_viewports(self) -> list[Any]:
        return [
            message["data"]["output"].get("viewport")
            for message in self.received
            if message.get("type") == "toolResult" and message.get("data", {}).get("name") == "screenshot_preview"
        ]


class Session:
    def __init__(self, page: Page, socket: GenerateCodeSocket, context: BrowserContext, tmp: Path, backend_url: str) -> None:
        self.page = page
        self.socket = socket
        self.context = context
        self.tmp = tmp
        self.backend_url = backend_url

    async def main_frame_eval(self, script: str) -> Any:
        return await self.page.evaluate(
            f"(() => {{ const doc = document.querySelector('[data-testid=\"rn-preview-frame\"]').contentDocument; return {script}; }})()"
        )

    async def statuses(self) -> list[dict[str, Any]]:
        return cast(list[dict[str, Any]], await self.page.evaluate("window.__rnStatuses"))


@pytest.fixture(scope="module")
def event_loop() -> Iterator[asyncio.AbstractEventLoop]:
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
def dirs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    root = tmp_path_factory.mktemp("rn-gates")
    paths = {name: root / name for name in ("assets", "data", "downloads", "inputs")}
    for path in paths.values():
        path.mkdir()
    return paths


@pytest.fixture(scope="module")
def backend_url(dirs: dict[str, Path]) -> Iterator[str]:
    with pytest.MonkeyPatch.context() as patch:
        screenshots = PlaywrightBackend()
        patch.setattr("preview_screenshot.registry._backend", screenshots)
        patch.setattr("preview_screenshot.registry._available", None)
        patch.setenv("SCREENSHOT_TO_CODE_DATA_DIR", str(dirs["data"]))
        patch.setattr(expo_export, "LOCAL_ASSET_DIR", str(dirs["assets"]))
        write_avatar(str(dirs["assets"]))
        models = ScriptedModels(asset_base_url="")
        patch.setattr("agent.engine.create_provider_session", models)
        with serve_app(gate_app(dirs["assets"], screenshots), "/rn-runtime/manifest.json", ws="websockets") as url:
            models.asset_base_url = url
            yield url


@pytest.fixture(scope="module")
def vite_url(backend_url: str) -> Iterator[str]:
    with vite_dev_server(backend_url, env={"VITE_SNACK_EXPORT": "true"}) as url:
        yield url


@pytest.fixture(scope="module")
async def browser() -> AsyncIterator[Browser]:
    backend = PlaywrightBackend()
    try:
        chromium = await backend._get_browser()  # pyright: ignore[reportPrivateUsage]
    except Exception as error:  # Chromium not installed
        pytest.skip(f"Chromium unavailable: {error}")
    yield chromium
    await chromium.close()


@pytest.fixture(scope="module")
async def session(browser: Browser, vite_url: str, backend_url: str, dirs: dict[str, Path]) -> AsyncIterator[Session]:
    """One React Native generation from an iPhone 13 screenshot, through the UI."""
    context = await browser.new_context(viewport={"width": 1400, "height": 1000}, accept_downloads=True)
    # Let the dev server finish optimizing the app's dependencies (it reloads
    # the page when it discovers new ones) before the session starts.
    warmup = await context.new_page()
    await warmup.goto(vite_url, wait_until="networkidle", timeout=READY_TIMEOUT_S * 1000)
    await warmup.wait_for_timeout(2000)
    await warmup.close()

    await context.add_init_script(RECORD_STATUSES)
    page = await context.new_page()
    socket = GenerateCodeSocket(page)
    await page.goto(vite_url)
    await page.evaluate("(settings) => localStorage.setItem('setting', JSON.stringify(settings))", SETTINGS)
    await page.reload()
    await page.get_by_test_id("upload-input").set_input_files(str(iphone_screenshot(dirs["inputs"] / "iphone13.png")))
    await page.get_by_test_id("rn-device-summary").wait_for()
    await page.get_by_test_id("upload-generate").click()
    await socket.wait_closed(1)
    await page.wait_for_function(
        "document.querySelector('[data-testid=\"rn-preview-status\"]')?.dataset.status === 'ok'",
        timeout=GENERATION_TIMEOUT_S * 1000,
    )
    try:
        yield Session(page, socket, context, dirs["downloads"], backend_url)
    finally:
        await context.close()


async def test_rnw2_the_generation_previews_on_the_phone(session: Session) -> None:
    page, socket = session.page, session.socket

    # The request: React Native, one screenshot, the detected phone.
    request = socket.sent[0]
    assert request["generatedCodeConfig"] == "react_native"
    assert request["inputMode"] == "image"
    assert len(request["prompt"]["images"]) == 1
    assert request["reactNativeProfile"] == {}

    # One phone preview instead of desktop and mobile pages.
    assert await page.get_by_test_id("tab-phone").count() == 1
    assert await page.get_by_test_id("tab-desktop").count() == 0
    assert await page.get_by_test_id("tab-mobile").count() == 0
    assert "iPhone 12, 12 Pro, 13" in (await page.get_by_test_id("rn-preview-device").text_content() or "")

    # App.jsx rendered in the app's iframe, from the runtime the backend serves.
    greeting = await session.main_frame_eval("doc.querySelector('[data-testid=\"greeting\"]')?.textContent")
    assert str(greeting).startswith("Option ")
    test_ids = await session.main_frame_eval("Array.from(doc.querySelectorAll('[data-testid]')).map((el) => el.dataset.testid)")
    assert {"screen", "settings-list", "avatar", "progress-ring", "settings-row-about"} <= set(test_ids)
    avatar = await session.main_frame_eval("(() => { const img = doc.querySelector('[data-testid=\"avatar\"] img'); return img && [img.complete, img.naturalWidth]; })()")
    assert avatar == [True, 4]

    # The phone is the one the backend screenshotted.
    viewports = socket.screenshot_viewports()
    assert viewports and all(viewport == IPHONE_13_PROFILE for viewport in viewports)
    frame_size = await page.evaluate("(() => { const f = document.querySelector('[data-testid=\"rn-preview-frame\"]'); return [f.style.width, f.style.height]; })()")
    assert frame_size == ["390px", "763px"]

    # Hot swap: the phone's document booted once, rendered App.jsx in
    # streaming mode while create_file wrote it, and swapped in the finished
    # file without reloading. (Chunks that arrive mid-render are coalesced.)
    main = [status for status in await session.statuses() if status["main"]]
    assert [status["renderId"] for status in main].count(1) == 1
    assert max(status["renderId"] for status in main) >= 2
    assert main[0]["status"] == "streaming"
    assert main[-1]["status"] == "ok"

    # Each option's thumbnail renders its own App.jsx.
    await page.wait_for_function(
        "Array.from(document.querySelectorAll('[data-testid=\"rn-variant-preview\"]'))"
        ".filter((f) => f.contentDocument?.querySelector('[data-testid=\"greeting\"]')).length === 4",
        timeout=15000,
    )
    thumbnails = await page.evaluate(
        "Array.from(document.querySelectorAll('[data-testid=\"rn-variant-preview\"]'))"
        ".map((f) => f.contentDocument.querySelector('[data-testid=\"greeting\"]').textContent)"
    )
    assert sorted(thumbnails) == ["Option 1", "Option 2", "Option 3", "Option 4"]

    # The code view shows App.jsx, without CodePen.
    await page.get_by_test_id("tab-code").click()
    await page.locator(".cm-content").wait_for()
    assert await page.get_by_test_id("code-filename").text_content() == "App.jsx"
    assert await page.get_by_test_id("open-codepen").count() == 0
    # CodeMirror only renders the lines in view.
    assert "import { SafeAreaView } from 'react-native-safe-area-context';" in (await page.locator(".cm-content").inner_text())
    await page.get_by_test_id("tab-phone").click()
    await page.get_by_test_id("rn-preview-status").wait_for()


async def test_rnw3_the_downloaded_preview_renders_offline(browser: Browser, session: Session) -> None:
    page = session.page
    await page.get_by_test_id("rn-export-menu").click()
    async with page.expect_download() as download_info:
        await page.get_by_test_id("download-preview-html").click()
    download = await download_info.value
    target = session.tmp / download.suggested_filename
    await download.save_as(str(target))
    html = target.read_text(encoding="utf-8")
    assert "<script src" not in html
    assert AVATAR_NAME not in html  # embedded as a data: URI

    context = await browser.new_context(viewport={"width": 390, "height": 763}, offline=True)
    attempts: list[str] = []

    async def no_network(route: Route) -> None:
        if route.request.url.startswith("file:"):
            await route.continue_()
        else:
            attempts.append(route.request.url)
            await route.abort()

    try:
        await context.route("**/*", no_network)
        offline = await context.new_page()
        await offline.goto(target.as_uri())
        await offline.wait_for_function("window.__RN_PREVIEW_READY__ === true", timeout=30000)
        status = await offline.evaluate("window.__RN_PREVIEW_STATUS__")
        errors = await offline.evaluate("window.__RN_PREVIEW_ERRORS__")
        avatar = await offline.evaluate(
            "(() => { const img = document.querySelector('[data-testid=\"avatar\"] img'); return img && [img.complete, img.naturalWidth, img.src.slice(0, 22)]; })()"
        )
    finally:
        await context.close()
    assert status == "ok" and errors == []
    assert avatar == [True, 4, "data:image/png;base64,"]
    assert attempts == []


async def test_the_expo_project_download_embeds_images_and_bundles(session: Session) -> None:
    """Phase 4: the Expo zip from the export menu. With RN_BUNDLE_CHECK=1 it is
    also bundled for iOS and Android (RNW-6)."""
    page = session.page
    await page.get_by_test_id("rn-export-menu").click()
    async with page.expect_download() as download_info:
        await page.get_by_test_id("download-expo-project").click()
    download = await download_info.value
    assert download.suggested_filename == "screenshot-to-code-expo.zip"
    target = session.tmp / download.suggested_filename
    await download.save_as(str(target))
    with zipfile.ZipFile(target) as archive:
        files = {name.split("/", 1)[1]: archive.read(name).decode("utf-8") for name in archive.namelist()}

    assert {"package.json", "app.json", "index.js", "App.jsx", "assets.js", "README.md"} <= set(files)
    assert "import { ASSETS } from './assets';" in files["App.jsx"]
    assert AVATAR_NAME not in files["App.jsx"] and "ASSETS.asset_" in files["App.jsx"]
    assert files["assets.js"].count("data:image/png;base64,") == 1
    assert "<SafeAreaProvider>" in files["index.js"]

    if config.RN_BUNDLE_CHECK:
        result = await asyncio.to_thread(check_bundle, files)
        assert result.ok, result.log_tail


async def test_open_in_snack_prefills_the_screen(session: Session) -> None:
    page = session.page
    await page.get_by_test_id("rn-export-menu").click()
    assert await page.get_by_test_id("open-in-snack").text_content() == "Open in SnackOpens in Snack (Expo SDK 55)"
    # Snack itself is out of reach here: answer for it, and read the URL the app built.
    async def snack_stub(route: Route) -> None:
        await route.fulfill(body="<p>Snack</p>", content_type="text/html")

    await page.context.route("https://snack.expo.dev/**", snack_stub)
    async with page.context.expect_page() as popup_info:
        await page.get_by_test_id("open-in-snack").click()
    popup = await popup_info.value
    url = urlparse(popup.url)
    await popup.close()
    params = parse_qs(url.query)
    assert url.netloc == "snack.expo.dev"
    assert params["sdkVersion"] == ["55.0.0"]
    files = json.loads(params["files"][0])
    assert "export default function App" in files["Screen.js"]["contents"]
    assert "<SafeAreaProvider>" in files["App.js"]["contents"]


async def test_a_selected_element_is_edited_by_its_test_id(session: Session) -> None:
    page, socket = session.page, session.socket
    await page.get_by_test_id("tab-phone").click()
    await page.get_by_test_id("select-edit-toggle").click()
    await page.frame_locator('[data-testid="rn-preview-frame"]').get_by_text("Notifications", exact=True).click()
    assert await page.get_by_test_id("selected-element-label").text_content() == 'testID="settings-row-notifications"'

    textarea = page.get_by_placeholder('Describe changes for the selected testID="settings-row-notifications" element...')
    await textarea.fill("Change the greeting to Hello, Grace")
    await textarea.press("Enter")
    await socket.wait_closed(2)

    update = socket.sent[-1]
    assert update["generationType"] == "update"
    assert update["fileState"]["path"] == "App.jsx"
    assert update["reactNativeProfile"] == {}
    assert update["prompt"]["selectedElementLabel"] == 'testID="settings-row-notifications"'
    full_text = update["prompt"]["fullText"]
    assert 'the one with testID="settings-row-notifications"' in full_text
    assert "screen > settings-list > settings-row-notifications" in full_text
    assert 'Its text: "Notifications Push, email, SMS"' in full_text

    await page.wait_for_function(
        "document.querySelector('[data-testid=\"rn-preview-frame\"]').contentDocument"
        ".querySelector('[data-testid=\"greeting\"]')?.textContent === 'Hello, Grace'",
        timeout=GENERATION_TIMEOUT_S * 1000,
    )


# The open project as the library saved it in IndexedDB (null until saved).
READ_SAVED_PROJECT = """
async () => {
  const id = localStorage.getItem("library:lastProjectId");
  if (!id) return null;
  const db = await new Promise((resolve, reject) => {
    const request = indexedDB.open("screenshot-to-code-library");
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
  const read = (store) => new Promise((resolve, reject) => {
    const request = db.transaction(store).objectStore(store).get(id);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
  const [summary, snapshot] = [await read("summaries"), await read("snapshots")];
  db.close();
  if (!snapshot) return null;
  const head = snapshot.commits[snapshot.head];
  const variant = head.variants[head.selectedVariantIndex];
  return { summary, stack: snapshot.stack, versions: Object.keys(snapshot.commits).length, status: variant.status, code: variant.code };
}
"""
GREETING_IS_GRACE = (
    "document.querySelector('[data-testid=\"rn-preview-frame\"]')?.contentDocument"
    "?.querySelector('[data-testid=\"greeting\"]')?.textContent === 'Hello, Grace'"
)


async def test_the_library_keeps_the_project_across_a_reload(session: Session) -> None:
    """Projects are saved in the browser: a reload reopens the one that was
    open, and the library lists, renames, opens and deletes them. (Runs after
    the edit above, so the project has two versions.)"""
    page = session.page

    # Autosave has caught up with the finished edit. (wait_for_function
    # doesn't await a promise, so poll.)
    deadline = time.monotonic() + 15
    while True:
        saved = await page.evaluate(READ_SAVED_PROJECT)
        if saved and saved["versions"] == 2 and saved["status"] == "complete" and "Hello, Grace" in saved["code"]:
            break
        assert time.monotonic() < deadline, f"the edit wasn't saved: {saved and (saved['versions'], saved['status'])}"
        await asyncio.sleep(0.25)
    assert saved["stack"] == "react_native"
    assert saved["summary"]["name"].startswith("Screenshot, ")
    assert saved["summary"]["thumbnail"].startswith("data:image/jpeg;base64,")

    # A reload reopens it.
    await page.reload()
    await page.wait_for_function(GREETING_IS_GRACE, timeout=30000)
    assert await page.get_by_test_id("rn-preview-status").get_attribute("data-status") == "ok"

    # The library lists it; rename it.
    await page.get_by_test_id("open-library").click()
    item = page.get_by_test_id("library-item")
    await item.wait_for()
    assert await item.count() == 1
    text = await item.inner_text()
    assert "React Native (Expo)" in text and "2 versions" in text
    await page.get_by_test_id("library-name").click()
    await page.get_by_test_id("library-rename-input").fill("Settings screen")
    await page.get_by_test_id("library-rename-input").press("Enter")
    await page.get_by_test_id("library-name").filter(has_text="Settings screen").wait_for()

    # A new project leaves it in the library, and a reload no longer reopens it.
    await page.get_by_title("Start a new project").click()
    await page.get_by_test_id("upload-input").wait_for(state="attached")
    assert await page.evaluate("localStorage.getItem('library:lastProjectId')") is None
    await page.reload()
    await page.get_by_test_id("upload-input").wait_for(state="attached")

    # Open it from the library.
    await page.get_by_test_id("open-library").click()
    await page.get_by_test_id("library-open").click()
    await page.wait_for_function(GREETING_IS_GRACE, timeout=30000)
    assert await page.get_by_test_id("library-pane").count() == 0

    # Delete it: the app starts a new project and the library is empty.
    await page.get_by_test_id("open-library").click()
    await page.get_by_test_id("library-delete").click()
    await page.get_by_test_id("library-confirm-delete").click()
    await page.get_by_text("No saved projects yet.").wait_for()
    assert await page.get_by_test_id("library-item").count() == 0
    assert await page.evaluate(READ_SAVED_PROJECT) is None
    await page.get_by_test_id("open-library").click()
    await page.get_by_test_id("upload-input").wait_for(state="attached")
