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
import time
from pathlib import Path
from typing import Any, AsyncIterator, Iterator, cast

import pytest
from PIL import Image, ImageDraw, ImageStat
from playwright.async_api import Browser, Page, Request, Route

from preview_screenshot.playwright_backend import PlaywrightBackend
from react_native.preview_html import inline_script, preview_config_json, render_preview_html
from react_native.render import ROUTE_ORIGIN, PreviewRender, preview_html_for, render_preview
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
    "card-boxshadow", "card-bordered", "progress-ring", "settings-row-profile", "settings-row-about",
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
    # Babel's "/App.jsx: ... (8:11)" wrapper is stripped; the code frame travels separately.
    assert error["message"] == "Unterminated JSX contents."
    assert ">  8 |     </View>" in error["frame"]
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


async def test_box_shadow_and_legacy_shadow_both_render_on_web(browser: Browser) -> None:
    render = await render_preview(browser, bundle(), fixture("shadows"), IPHONE, inspect=probe)
    shadows = render.extra["shadows"]
    assert shadows["modern"] and shadows["modern"] != "none"
    assert shadows["legacy"] and shadows["legacy"] != "none"
    assert any('"shadow*" style props are deprecated' in warning for warning in render.console_warnings)
    # The lint steers the model to boxShadow, which renders the same on iOS and Android.
    assert render.status == "degraded"
    assert {error["rule"] for error in render.runtime_errors} == {"legacy-shadow"}


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


async def test_failed_image_is_reported_without_failing_the_render(browser: Browser) -> None:
    render = await render_preview(browser, bundle(), fixture("broken-image"), IPHONE)
    assert render.status == "degraded"
    assert kinds(render) == ["image_load"]
    assert "missing.png" in render.runtime_errors[0]["message"]


async def test_hung_app_times_out_instead_of_blocking(browser: Browser, monkeypatch: pytest.MonkeyPatch) -> None:
    # Production bounds are seconds; shrink them so the test stays fast.
    monkeypatch.setattr("react_native.render.STATE_TIMEOUT_S", 0.5)
    monkeypatch.setattr("react_native.render.SCREENSHOT_TIMEOUT_MS", 500)
    started = time.perf_counter()
    render = await render_preview(browser, bundle(), fixture("broken-hang"), IPHONE, ready_timeout_ms=2000)
    assert render.status == "timeout"
    assert render.ready_ms is None
    assert render.runtime_errors[0]["kind"] == "timeout" and render.runtime_errors[0]["fatal"] is True
    assert time.perf_counter() - started < 10


# ---------------------------------------------------------------- hot-swap and streaming (1.4)

SCREEN_A = """import React from 'react';
import { Text, View } from 'react-native';

export default function App() {
  return (
    <View testID="screen-a" style={{ flex: 1, padding: 24, backgroundColor: '#EEF2FF' }}>
      <Text testID="title-a" style={{ fontSize: 22, fontWeight: '700' }}>Screen A</Text>
    </View>
  );
}
"""
SCREEN_B = SCREEN_A.replace("screen-a", "screen-b").replace("title-a", "title-b").replace("Screen A", "Screen B")

UPDATE_JS = """([source, mode]) => window.postMessage({ type: 'rn-preview:update', source, mode }, '*')"""
AFTER_UPDATE_JS = """() => {
  const badge = document.getElementById('rn-preview-streaming');
  return {
    status: window.__RN_PREVIEW_STATUS__,
    errors: window.__RN_PREVIEW_ERRORS__.map(({ key, ...rest }) => rest),
    meta: (({ app, ...rest }) => rest)(window.__RN_PREVIEW_META__),
    testIds: Array.from(document.querySelectorAll('[data-testid]')).map((el) => el.getAttribute('data-testid')),
    badge: Boolean(badge && !badge.hidden),
    // Set before the update; a page reload would have cleared it.
    sameDocument: window.__beforeUpdate === true,
  };
}"""


async def update(page: Page, source: str, mode: str, render_id: int) -> dict[str, Any]:
    """Post an update the way the frontend does and wait for that render to settle."""
    await page.evaluate("() => { window.__beforeUpdate = true; }")
    await page.evaluate(UPDATE_JS, [source, mode])
    await page.wait_for_function(
        "(id) => window.__RN_PREVIEW_READY__ === true && window.__RN_PREVIEW_META__.renderId === id",
        arg=render_id,
        timeout=10000,
    )
    return cast(dict[str, Any], await page.evaluate(AFTER_UPDATE_JS))


async def test_hot_swap_replaces_the_screen_without_reloading_scripts(browser: Browser) -> None:
    async def swap(page: Page) -> dict[str, Any]:
        return await update(page, SCREEN_B, "final", 2)

    render = await render_preview(browser, bundle(), SCREEN_A, IPHONE, inspect=swap)
    after = render.extra
    assert after["status"] == "ok" and after["errors"] == []
    assert "screen-b" in after["testIds"] and "screen-a" not in after["testIds"]
    assert after["sameDocument"] is True  # swapped in place, no reload
    # Target is 150 ms from update to settled; allow slack for loaded CI machines.
    assert after["meta"]["readyMs"] < 500


async def test_streaming_keeps_the_last_good_render(browser: Browser) -> None:
    async def stream(page: Page) -> dict[str, Any]:
        return {
            "partial": await update(page, SCREEN_B[: len(SCREEN_B) // 2], "streaming", 2),
            "throwing": await update(page, fixture("broken-runtime"), "streaming", 3),
            "final": await update(page, SCREEN_B, "final", 4),
        }

    render = await render_preview(browser, bundle(), SCREEN_A, IPHONE, inspect=stream)
    partial, throwing, final = render.extra["partial"], render.extra["throwing"], render.extra["final"]
    # A half-written file (syntax error) keeps screen A up, with the badge and no errors.
    assert partial["status"] == "streaming" and partial["errors"] == []
    assert "screen-a" in partial["testIds"] and partial["badge"] is True
    # A file that throws while still streaming falls back to screen A too.
    assert throwing["status"] == "streaming" and throwing["errors"] == []
    assert "screen-a" in throwing["testIds"] and "rn-preview-error" not in throwing["testIds"]
    # The finished file renders normally and the badge goes away.
    assert final["status"] == "ok" and "screen-b" in final["testIds"] and final["badge"] is False


async def test_streaming_before_any_render_shows_a_blank_screen(browser: Browser) -> None:
    partial = "import React from 'react';\nexport default fun"
    render = await render_preview(browser, bundle(), partial, IPHONE, mode="streaming", inspect=probe)
    assert render.status == "streaming" and render.runtime_errors == []
    assert "rn-preview-error" not in render.extra["testIds"]


async def test_parent_window_drives_updates_and_receives_status(browser: Browser) -> None:
    runtime = bundle()
    page = await browser.new_page(viewport={"width": 480, "height": 900})

    async def fulfill(route: Route) -> None:
        await route.fulfill(path=runtime.path(route.request.url.rsplit("/", 1)[-1]), content_type="text/javascript")

    await page.route(f"{ROUTE_ORIGIN}/rn-runtime/*", fulfill)
    try:
        await page.set_content(
            '<iframe id="preview" style="width:390px;height:751px;border:0"></iframe>'
            "<script>window.statuses = []; addEventListener('message', (e) => {"
            " if (e.data && e.data.type === 'rn-preview:status') window.statuses.push(e.data); });</script>"
        )
        await page.evaluate("(html) => { document.getElementById('preview').srcdoc = html; }", preview_html_for(runtime, SCREEN_A, IPHONE))
        await page.wait_for_function("window.statuses.length === 1", timeout=15000)
        await page.evaluate(
            "(source) => document.getElementById('preview').contentWindow.postMessage({ type: 'rn-preview:update', source }, '*')",
            SCREEN_B,
        )
        await page.wait_for_function("window.statuses.length === 2", timeout=10000)
        # A message that doesn't come from the parent window is ignored. It must
        # be sent from the iframe's own realm: postMessage's source is the caller.
        await page.evaluate(
            "(source) => document.getElementById('preview').contentWindow.eval("
            " `window.postMessage({ type: 'rn-preview:update', source: ${JSON.stringify(source)} }, '*')`)",
            SCREEN_A,
        )
        await page.wait_for_timeout(400)
        statuses = cast(list[dict[str, Any]], await page.evaluate("window.statuses"))
        title = await page.frame_locator("#preview").locator('[data-testid^="title-"]').first.text_content()
    finally:
        await page.close()
    assert [status["renderId"] for status in statuses] == [1, 2]
    assert all(status["status"] == "ok" and status["errors"] == [] for status in statuses)
    assert title == "Screen B"


# ---------------------------------------------------------------- native-compatibility lint (1.5)


async def test_dom_elements_and_onclick_are_fatal(browser: Browser) -> None:
    render = await render_preview(browser, bundle(), fixture("lint-dom"), IPHONE, inspect=probe)
    found = {(error["rule"], error["fatal"], error.get("line")) for error in render.runtime_errors}
    assert render.status == "error"
    assert ("host-element", True, 7) in found
    assert ("on-click", True, 7) in found
    assert ("class-name", False, 7) in found
    assert "rn-preview-error" in render.extra["testIds"]


async def test_web_only_styles_are_warnings_with_source_lines(browser: Browser) -> None:
    render = await render_preview(browser, bundle(), fixture("lint-web-styles"), IPHONE, inspect=probe)
    lint = [error for error in render.runtime_errors if error["kind"] == "native_compat"]
    found = sorted((str(error["rule"]), int(error["line"])) for error in lint)
    assert render.status == "degraded"  # it still renders
    assert "web-styles" in render.extra["testIds"]
    assert all(error["fatal"] is False for error in render.runtime_errors)
    # react-native-web's own style validation agrees about the shorthand.
    assert any("only single values are supported" in error["message"] for error in render.runtime_errors)
    assert found == sorted([
        ("platform-branch", 5),
        ("unit-string", 9),
        ("web-style", 9),        # cursor
        ("css-shorthand", 17),   # padding: '8px 16px'
        ("web-style", 18),       # display: 'grid'
        ("web-style", 18),       # gridTemplateColumns
        ("web-style", 18),       # position: 'sticky'
        ("css-shorthand", 19),   # border
        ("legacy-shadow", 19),   # shadowColor
        ("legacy-shadow", 19),   # elevation
    ])
