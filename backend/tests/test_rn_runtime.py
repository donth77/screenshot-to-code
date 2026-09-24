"""React Native preview runtime, rendered in real headless Chromium.

Covers gates RNW-1 (renders through the repo's Playwright backend), RNW-3
(self-contained file, offline), RNW-4 (one React) and RNW-7 (Babel 7 classic
runtime, located transform errors), plus the error-reporting contract.
Skipped when rn-runtime hasn't been built (``cd rn-runtime && pnpm build``) or
Chromium isn't installed.
"""

import asyncio
import base64
import io
from pathlib import Path
from typing import Any, AsyncIterator, Iterator, cast

import pytest
from PIL import Image, ImageDraw, ImageStat
from playwright.async_api import Browser, Page, Request

from preview_screenshot.playwright_backend import PlaywrightBackend
from react_native.preview_html import inline_script, preview_config_json, render_preview_html
from react_native.render import PreviewRender, render_preview
from react_native.runtime_files import RuntimeBundle, load_runtime

FIXTURES = Path(__file__).resolve().parents[2] / "rn-runtime" / "fixtures"
_BUNDLE = load_runtime()
pytestmark = pytest.mark.skipif(_BUNDLE is None, reason="rn-runtime is not built (cd rn-runtime && pnpm build)")

NO_INSETS = {"top": 0, "right": 0, "bottom": 0, "left": 0}
# iPhone 15-class content area: 390 x 844 pt minus 59 pt status bar and 34 pt home indicator.
IPHONE: dict[str, Any] = {"platform": "ios", "width": 390, "height": 751, "scale": 3, "insets": NO_INSETS}
# Pixel 8: scale derived from the 1080 px width, so the render is exactly 1080 px wide.
PIXEL: dict[str, Any] = {"platform": "android", "width": 412, "height": 868, "scale": 1080 / 412, "insets": NO_INSETS}

MAIN_TEST_IDS = [
    "screen", "settings-list", "avatar", "greeting", "bell-button", "search-input", "chips", "chip-all",
    "card-boxshadow", "card-legacy-shadow", "progress-ring", "settings-row-profile", "settings-row-about",
]

PROBE_JS = """() => {
  const style = (id) => { const el = document.querySelector(`[data-testid="${id}"]`); return el ? getComputedStyle(el) : null; };
  const ring = document.querySelector('[data-testid="progress-ring"] path');
  const screen = style('screen');
  return {
    testIds: Array.from(document.querySelectorAll('[data-testid]')).map((el) => el.getAttribute('data-testid')),
    svgCount: document.querySelectorAll('svg').length,
    ringPath: ring ? ring.getAttribute('d') : null,
    singleReact: !!window.__RN_MODULES__ && window.__RN_MODULES__.react === window.React,
    reactVersion: window.React && window.React.version,
    babelVersion: window.Babel && window.Babel.version,
    safeArea: screen ? { top: screen.paddingTop, bottom: screen.paddingBottom } : null,
    shadows: { modern: style('card-boxshadow')?.boxShadow, legacy: style('card-legacy-shadow')?.boxShadow },
  };
}"""


def _avatar_data_uri() -> str:
    image = Image.new("RGB", (192, 192), "#C7D2FE")
    draw = ImageDraw.Draw(image)
    draw.ellipse((56, 28, 136, 108), fill="#6366F1")
    draw.ellipse((24, 112, 168, 256), fill="#4F46E5")
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


AVATAR = _avatar_data_uri()


def fixture(name: str) -> str:
    source = (FIXTURES / f"{name}.jsx").read_text(encoding="utf-8")
    return source.replace("__ASSET_BASE__/local-assets/avatar.png", AVATAR)


def bundle() -> RuntimeBundle:
    assert _BUNDLE is not None
    return _BUNDLE


async def probe(page: Page) -> dict[str, Any]:
    return cast(dict[str, Any], await page.evaluate(PROBE_JS))


async def platform_fonts(page: Page, selector: str) -> list[dict[str, Any]]:
    """Fonts Chromium actually used to rasterize the node's text."""
    cdp = await page.context.new_cdp_session(page)
    await cdp.send("DOM.enable")
    await cdp.send("CSS.enable")
    document = cast(dict[str, Any], await cdp.send("DOM.getDocument", {"depth": -1}))
    node = cast(dict[str, Any], await cdp.send("DOM.querySelector", {"nodeId": document["root"]["nodeId"], "selector": selector}))
    fonts = cast(dict[str, Any], await cdp.send("CSS.getPlatformFontsForNode", {"nodeId": node["nodeId"]}))
    await cdp.detach()
    return cast(list[dict[str, Any]], fonts.get("fonts", []))


async def probe_with_fonts(page: Page) -> dict[str, Any]:
    result = await probe(page)
    result["fonts"] = await platform_fonts(page, '[data-testid="greeting"]')
    return result


def stddev(png: bytes) -> float:
    image = Image.open(io.BytesIO(png)).convert("RGB")
    return sum(ImageStat.Stat(image).stddev) / 3


def size(png: bytes) -> tuple[int, int]:
    return Image.open(io.BytesIO(png)).size


def kinds(render: PreviewRender) -> list[str]:
    return [str(error["kind"]) for error in render.runtime_errors]


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
    except Exception as exc:  # missing browser binary or system libraries
        pytest.skip(f"Chromium is unavailable: {exc}")
    yield chromium
    await chromium.close()


@pytest.fixture(scope="module")
async def main_render(browser: Browser) -> PreviewRender:
    return await render_preview(browser, bundle(), fixture("App"), IPHONE, inspect=probe_with_fonts)


# ---------------------------------------------------------------- RNW-1


async def test_fixture_renders_cleanly_at_the_profile_size(main_render: PreviewRender) -> None:
    assert main_render.status == "ok", main_render.runtime_errors
    assert main_render.runtime_errors == []
    assert main_render.ready_ms is not None
    assert size(main_render.png) == (1170, 2253)
    assert stddev(main_render.png) > 10


async def test_fixture_exposes_test_ids_as_data_testid(main_render: PreviewRender) -> None:
    missing = [test_id for test_id in MAIN_TEST_IDS if test_id not in main_render.extra["testIds"]]
    assert missing == []


async def test_fractional_android_scale_renders_exactly_the_screenshot_width(browser: Browser) -> None:
    render = await render_preview(browser, bundle(), fixture("App"), PIXEL, inspect=probe_with_fonts)
    width, height = size(render.png)
    assert render.status == "ok"
    assert width == 1080
    assert abs(height - PIXEL["height"] * PIXEL["scale"]) <= 2
    assert [(font["familyName"], font["isCustomFont"]) for font in render.extra["fonts"]] == [("Roboto", True)]


# ---------------------------------------------------------------- RNW-4


async def test_one_react_serves_the_app_and_every_library(main_render: PreviewRender) -> None:
    assert main_render.extra["singleReact"] is True
    assert main_render.extra["reactVersion"] == "19.2.3"
    assert "invalid_hook_call" not in kinds(main_render)


async def test_hooks_run_inside_lucide_and_svg_components(main_render: PreviewRender) -> None:
    # 9 rows x 3 icons, the header icons and two rings, all rendered as <svg>.
    assert main_render.extra["svgCount"] >= 20
    # The ring's arc comes from state set in useEffect; the initial arc ends at "32 6".
    assert not str(main_render.extra["ringPath"]).endswith(" 32 6")


# ---------------------------------------------------------------- RNW-7


async def test_babel_is_pinned_to_7(main_render: PreviewRender) -> None:
    assert str(main_render.extra["babelVersion"]).startswith("7.")


async def test_syntax_error_reports_line_and_column(browser: Browser) -> None:
    render = await render_preview(browser, bundle(), fixture("broken-syntax"), IPHONE)
    assert render.status == "error"
    error = render.runtime_errors[0]
    assert (error["kind"], error["line"], error["column"], error["fatal"]) == ("transform", 8, 12, True)
    assert stddev(render.png) > 5  # the error panel is in the screenshot


# ---------------------------------------------------------------- error contract


async def test_runtime_error_reports_source_line_and_component_stack(browser: Browser) -> None:
    render = await render_preview(browser, bundle(), fixture("broken-runtime"), IPHONE)
    assert render.status == "error"
    assert len(render.runtime_errors) == 1
    error = render.runtime_errors[0]
    assert error["kind"] == "runtime" and error["line"] == 5 and "toFixed" in error["message"]
    assert str(error["component_stack"]).startswith("Price (App.jsx:4) < App")


async def test_unknown_import_names_the_module(browser: Browser) -> None:
    render = await render_preview(browser, bundle(), fixture("broken-import"), IPHONE)
    error = render.runtime_errors[0]
    assert render.status == "error"
    assert error["kind"] == "import" and error["line"] == 3 and "@expo/vector-icons" in error["message"]


async def test_unknown_icon_renders_a_placeholder_and_suggests_names(browser: Browser) -> None:
    render = await render_preview(browser, bundle(), fixture("broken-icon"), IPHONE, inspect=probe)
    assert render.status == "degraded"
    assert kinds(render) == ["unknown_icon"]
    assert "Heart" in render.runtime_errors[0]["message"]
    assert "unknown-icon-HeartOutline" in render.extra["testIds"]


async def test_missing_default_export_is_fatal(browser: Browser) -> None:
    render = await render_preview(browser, bundle(), fixture("broken-no-default"), IPHONE)
    assert render.status == "error" and kinds(render) == ["no_default_export"]


async def test_unknown_react_native_export_is_named(browser: Browser) -> None:
    render = await render_preview(browser, bundle(), fixture("broken-unknown-export"), IPHONE)
    assert render.status == "error"
    assert render.runtime_errors[0]["kind"] == "unknown_export"
    assert render.runtime_errors[0]["name"] == "PlatformColor"


async def test_source_without_react_import_renders(browser: Browser) -> None:
    render = await render_preview(browser, bundle(), fixture("no-react-import"), IPHONE)
    assert render.status == "ok" and render.runtime_errors == []


# ---------------------------------------------------------------- fonts, safe area, shadows


async def test_ios_profile_rasterizes_with_the_bundled_inter(main_render: PreviewRender) -> None:
    assert [(font["familyName"], font["isCustomFont"]) for font in main_render.extra["fonts"]] == [("Inter", True)]


async def test_safe_area_view_uses_the_profile_insets(browser: Browser) -> None:
    full_device = dict(IPHONE, height=844, insets={"top": 59, "right": 0, "bottom": 34, "left": 0})
    render = await render_preview(browser, bundle(), fixture("App"), full_device, inspect=probe)
    assert render.extra["safeArea"] == {"top": "59px", "bottom": "34px"}


async def test_box_shadow_and_legacy_shadow_both_render(main_render: PreviewRender) -> None:
    shadows = main_render.extra["shadows"]
    assert shadows["modern"] and shadows["modern"] != "none"
    assert shadows["legacy"] and shadows["legacy"] != "none"
    assert any('"shadow*" style props are deprecated' in warning for warning in main_render.console_warnings)


# ---------------------------------------------------------------- RNW-3 (library level)


async def test_inlined_preview_renders_offline_from_a_file(browser: Browser, tmp_path: Path) -> None:
    runtime = bundle()
    html = render_preview_html(
        runtime.template,
        preview_config_json(fixture("App"), IPHONE),
        inline_script(runtime.read_text(runtime.babel_file)) + "\n" + inline_script(runtime.read_text(runtime.runtime_file)),
    )
    path = tmp_path / "preview.html"
    path.write_text(html, encoding="utf-8")
    context = await browser.new_context(offline=True, viewport={"width": 390, "height": 751}, device_scale_factor=3)
    network: list[str] = []

    def on_request(request: Request) -> None:
        if request.url.startswith("http"):
            network.append(request.url)

    context.on("request", on_request)
    try:
        page = await context.new_page()
        await page.goto(path.as_uri())
        await page.wait_for_function("window.__RN_PREVIEW_READY__ === true", timeout=20000)
        status = await page.evaluate("window.__RN_PREVIEW_STATUS__")
    finally:
        await context.close()
    assert status == "ok"
    assert network == []
