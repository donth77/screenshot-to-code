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
from typing import Any, AsyncIterator, Iterator, cast

import pytest
from fastapi import FastAPI
from playwright.async_api import Browser, Response, Route

from preview_screenshot.playwright_backend import PlaywrightBackend
from react_native.runtime_files import load_runtime
from react_native.serving import IMMUTABLE, configure_runtime_routes
from tests.dev_servers import READY_TIMEOUT_S, ROOT, VITE, serve_app, vite_dev_server

IPHONE: dict[str, Any] = {"platform": "ios", "width": 390, "height": 751, "scale": 3, "insets": {"top": 0, "right": 0, "bottom": 0, "left": 0}}
PIXEL_PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="

pytestmark = [
    pytest.mark.skipif(load_runtime() is None, reason="rn-runtime is not built (cd rn-runtime && pnpm build)"),
    pytest.mark.skipif(not VITE.exists(), reason="frontend dependencies are not installed (cd frontend && pnpm install)"),
]


@pytest.fixture(scope="module")
def backend_url() -> Iterator[str]:
    app = FastAPI()
    configure_runtime_routes(app)
    with serve_app(app, "/rn-runtime/manifest.json") as url:
        yield url


@pytest.fixture(scope="module")
def vite_url(backend_url: str) -> Iterator[str]:
    with vite_dev_server(backend_url, "/dev/rn-preview-harness.html") as url:
        yield url


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
