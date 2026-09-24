"""Gate RNW-2 at library level: the preview renders in an iframe on a page
served by the Vite dev server.

The backend's /rn-runtime mount serves rn-runtime/dist; Vite proxies
/rn-runtime to it, as in development. frontend/dev/rn-preview-harness.html
fills the template with the TypeScript renderer and loads it into a srcdoc
iframe. Phase 3 re-checks this through the real UI.

Skipped when rn-runtime isn't built, the frontend's dependencies aren't
installed, or Chromium is missing.
"""

import asyncio
import os
import signal
import socket
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, AsyncIterator, Iterator, cast

import pytest
import uvicorn
from fastapi import FastAPI
from playwright.async_api import Browser, Response, Route

from preview_screenshot.playwright_backend import PlaywrightBackend
from react_native.runtime_files import load_runtime
from react_native.serving import IMMUTABLE, configure_runtime_routes

ROOT = Path(__file__).resolve().parents[2]
VITE = ROOT / "frontend" / "node_modules" / ".bin" / "vite"
IPHONE: dict[str, Any] = {"platform": "ios", "width": 390, "height": 751, "scale": 3, "insets": {"top": 0, "right": 0, "bottom": 0, "left": 0}}
PIXEL_PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
READY_TIMEOUT_S = 60  # the first start pre-bundles the frontend's dependencies

pytestmark = [
    pytest.mark.skipif(load_runtime() is None, reason="rn-runtime is not built (cd rn-runtime && pnpm build)"),
    pytest.mark.skipif(not VITE.exists(), reason="frontend dependencies are not installed (cd frontend && pnpm install)"),
]


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return cast(int, sock.getsockname()[1])


def wait_for(url: str, process: "subprocess.Popen[bytes] | None" = None) -> None:
    deadline = time.monotonic() + READY_TIMEOUT_S
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            raise RuntimeError(f"{url}: the server exited with {process.returncode}")
        try:
            with urllib.request.urlopen(url, timeout=2):
                return
        except OSError:
            time.sleep(0.2)
    raise TimeoutError(f"{url} did not come up within {READY_TIMEOUT_S} s")


@pytest.fixture(scope="module")
def backend_url() -> Iterator[str]:
    app = FastAPI()
    configure_runtime_routes(app)
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", ws="none"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}"
    wait_for(f"{url}/rn-runtime/manifest.json")
    yield url
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture(scope="module")
def vite_url(backend_url: str) -> Iterator[str]:
    port = free_port()
    process = subprocess.Popen(
        [str(VITE), "--host", "127.0.0.1", "--port", str(port), "--strictPort"],
        cwd=ROOT / "frontend",
        env={**os.environ, "PROXY_CODEGEN_BACKEND": backend_url},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,  # its own process group, so teardown stops esbuild and the type checker too
    )
    url = f"http://127.0.0.1:{port}"
    try:
        wait_for(f"{url}/dev/rn-preview-harness.html", process)
        yield url
    finally:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=10)


@pytest.fixture(scope="module")
def event_loop() -> Iterator[asyncio.AbstractEventLoop]:
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
async def browser() -> AsyncIterator[Browser]:
    backend = PlaywrightBackend()
    try:
        chromium = await backend._get_browser()  # pyright: ignore[reportPrivateUsage]
    except Exception as error:  # Chromium not installed
        pytest.skip(f"Chromium unavailable: {error}")
    yield chromium
    await chromium.close()


async def test_preview_renders_in_an_iframe_on_the_vite_dev_server(browser: Browser, vite_url: str) -> None:
    source = (ROOT / "rn-runtime" / "fixtures" / "App.jsx").read_text(encoding="utf-8")
    source = source.replace("__ASSET_BASE__/local-assets/avatar.png", PIXEL_PNG)
    page = await browser.new_page()
    runtime_responses: list[Response] = []
    page.on("response", lambda response: runtime_responses.append(response) if "/rn-runtime/" in response.url else None)
    harness = f"{vite_url}/dev/rn-preview-harness.html"

    async def as_file(route: Route) -> None:
        # vite-plugin-html's history fallback answers browser navigations
        # (Accept: text/html) with the app's index.html; ask for the file.
        await route.continue_(headers={**route.request.headers, "accept": "*/*"})

    await page.route(harness, as_file)
    try:
        await page.goto(harness)
        await page.wait_for_function("window.harnessReady === true", timeout=READY_TIMEOUT_S * 1000)
        status = cast(dict[str, Any], await page.evaluate("([source, profile]) => window.renderPreview(source, profile)", [source, IPHONE]))
        # The parent reaches into the frame, as select-and-edit will.
        test_ids = cast(
            list[str],
            await page.evaluate(
                "Array.from(document.getElementById('preview').contentDocument.querySelectorAll('[data-testid]'))"
                ".map((el) => el.getAttribute('data-testid'))"
            ),
        )
        scripts = [response for response in runtime_responses if response.url.endswith(".js")]
        script_headers = [await response.all_headers() for response in scripts]
    finally:
        await page.close()

    assert status["status"] == "ok", status["errors"]
    assert status["errors"] == []
    assert {"screen", "greeting", "progress-ring", "settings-row-about"} <= set(test_ids)
    # Everything came through the Vite origin, with the backend's cache headers intact.
    assert runtime_responses and all(response.url.startswith(vite_url) for response in runtime_responses)
    assert all(response.status == 200 for response in runtime_responses)
    assert len(scripts) == 2  # Babel and the runtime
    assert all(headers["cache-control"] == IMMUTABLE for headers in script_headers)
