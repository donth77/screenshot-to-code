"""Phase 0 gate runner for the React Native preview runtime spike.

Renders the fixtures in real headless Chromium through the backend's own
Playwright backend (same browser launch, same ``page.set_content`` loading, so
the base URL is about:blank) and checks:

  RNW-1  renders, no pageerror, non-blank, data-testid present, pixel size =
         logical viewport x deviceScaleFactor
  RNW-4  one React: hooks inside lucide icons and react-native-svg components,
         no "Invalid hook call", __RN_MODULES__.react === window.React
  RNW-7  Babel 7.x classic runtime; transform errors carry line and column
  plus:  error reporting for broken fixtures, font override (CDP platform
         fonts), safe-area insets, shadow rendering (RNW-8 web half), and
         the three runtime-loading modes (served URL, route interception,
         inline).

Run from backend/:
    poetry run python ../spikes/rn-runtime/gates/run_gates.py
"""

import asyncio
import functools
import http.server
import io
import json
import re
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageStat

SPIKE = Path(__file__).resolve().parents[1]
REPO = SPIKE.parents[1]
sys.path.insert(0, str(REPO / "backend"))

from preview_screenshot import capture_preview_screenshot, probe_screenshot_preview  # noqa: E402
from preview_screenshot import registry  # noqa: E402

DIST = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else SPIKE / "dist"
OUT = SPIKE / "gates" / "out"
FIXTURES = SPIKE / "fixtures"
ROUTE_ORIGIN = "https://rn-runtime.invalid"

# iPhone 15: 390x844pt @3x, 59pt status bar/Dynamic Island inset, 34pt home
# indicator. The preview renders the content area only (insets cropped).
IPHONE_15_CONTENT = {
    "platform": "ios",
    "width": 390,
    "height": 844 - 59 - 34,
    "scale": 3,
    "insets": {"top": 0, "right": 0, "bottom": 0, "left": 0},
}
# Pixel 8: 1080x2400px. Scale is derived as pixel width / logical width so the
# render is exactly 1080px wide; height can land a pixel off (rounding).
PIXEL_8_CONTENT = {
    "platform": "android",
    "width": 412,
    "height": 868,
    "scale": 1080 / 412,
    "insets": {"top": 0, "right": 0, "bottom": 0, "left": 0},
}

EXPECTED_TESTIDS = [
    "screen",
    "settings-list",
    "avatar",
    "greeting",
    "bell-button",
    "search-input",
    "chips",
    "chip-all",
    "card-boxshadow",
    "card-legacy-shadow",
    "progress-ring",
    "settings-row-profile",
    "settings-row-about",
]


# ---------------------------------------------------------------------------
# Template rendering (the same substitution the backend and frontend will do)
# ---------------------------------------------------------------------------


def config_json(source: str, profile: dict[str, Any]) -> str:
    # "<" escaped so the JSON can never close its <script> element.
    return json.dumps({"source": source, "profile": profile}).replace("<", "\\u003c")


def inline_script(js: str) -> str:
    # Keep the HTML tokenizer out of script-data-escaped states: \x3C is "<" in
    # strings, template literals and regex literals alike.
    return "<script>" + re.sub(r"<(?=!--|/?script)", r"\\x3C", js, flags=re.I) + "</script>"


def render(template: str, source: str, profile: dict[str, Any], scripts: str) -> str:
    replacements = {
        "__RN_PREVIEW_CONFIG__": config_json(source, profile),
        "<!--RN_PREVIEW_SCRIPTS-->": scripts,
    }
    # Single pass so substituted content is never re-scanned for placeholders.
    return re.sub(
        "|".join(re.escape(key) for key in replacements),
        lambda match: replacements[match.group(0)],
        template,
    )


def script_tags(base_url: str, manifest: dict[str, Any]) -> str:
    return (
        f'<script src="{base_url}/rn-runtime/{manifest["babel"]}"></script>\n'
        f'<script src="{base_url}/rn-runtime/{manifest["runtime"]}"></script>'
    )


# ---------------------------------------------------------------------------
# Static server standing in for the backend's StaticFiles mounts
# ---------------------------------------------------------------------------


def start_static_server(root: Path) -> tuple[http.server.ThreadingHTTPServer, str]:
    handler = functools.partial(QuietHandler, directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        return


def make_avatar(path: Path) -> None:
    image = Image.new("RGB", (192, 192), "#C7D2FE")
    draw = ImageDraw.Draw(image)
    draw.ellipse((56, 28, 136, 108), fill="#6366F1")
    draw.ellipse((24, 112, 168, 256), fill="#4F46E5")
    image.save(path)


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------


PAGE_PROBE = """() => {
  const ids = Array.from(document.querySelectorAll('[data-testid]')).map((el) => el.getAttribute('data-testid'));
  const greeting = document.querySelector('[data-testid="greeting"]');
  const screen = document.querySelector('[data-testid="screen"]');
  const shadow = (id) => { const el = document.querySelector(`[data-testid="${id}"]`); return el ? getComputedStyle(el).boxShadow : null; };
  const ringPath = document.querySelector('[data-testid="progress-ring"] path');
  return {
    status: window.__RN_PREVIEW_STATUS__,
    errors: (window.__RN_PREVIEW_ERRORS__ || []).map(({ key, ...rest }) => rest),
    meta: window.__RN_PREVIEW_META__ || null,
    runtime: window.__RN_RUNTIME__ || null,
    singleReact: !!window.__RN_MODULES__ && window.__RN_MODULES__.react === window.React,
    reactVersion: window.React && window.React.version,
    babelVersion: window.Babel && window.Babel.version,
    testIds: ids,
    svgCount: document.querySelectorAll('svg').length,
    ringPathD: ringPath ? ringPath.getAttribute('d') : null,
    greetingFont: greeting ? getComputedStyle(greeting).fontFamily : null,
    safeAreaPadding: screen ? { top: getComputedStyle(screen).paddingTop, bottom: getComputedStyle(screen).paddingBottom } : null,
    boxShadow: { modern: shadow('card-boxshadow'), legacy: shadow('card-legacy-shadow') },
    viewport: { width: window.innerWidth, height: window.innerHeight, dpr: window.devicePixelRatio },
  };
}"""


async def platform_fonts(page: Any, selector: str) -> list[dict[str, Any]]:
    """Fonts Chromium actually used to rasterize the node's text (CDP)."""
    cdp = await page.context.new_cdp_session(page)
    await cdp.send("DOM.enable")
    await cdp.send("CSS.enable")
    document = await cdp.send("DOM.getDocument", {"depth": -1})
    node = await cdp.send("DOM.querySelector", {"nodeId": document["root"]["nodeId"], "selector": selector})
    if not node.get("nodeId"):
        return []
    fonts = await cdp.send("CSS.getPlatformFontsForNode", {"nodeId": node["nodeId"]})
    await cdp.detach()
    return fonts.get("fonts", [])


async def capture(
    html: str,
    profile: dict[str, Any],
    *,
    route_dir: Path | None = None,
    name: str,
) -> dict[str, Any]:
    browser = await registry._backend._get_browser()  # type: ignore[attr-defined]
    page = await browser.new_page(
        viewport={"width": profile["width"], "height": profile["height"]},
        device_scale_factor=profile["scale"],
    )
    page_errors: list[str] = []
    console_errors: list[str] = []
    console_warnings: list[str] = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))

    def on_console(message: Any) -> None:
        if message.type == "error":
            console_errors.append(message.text[:500])
        elif message.type == "warning":
            console_warnings.append(message.text[:500])

    page.on("console", on_console)
    if route_dir is not None:
        async def fulfill(route: Any) -> None:
            file = route_dir / route.request.url.rsplit("/", 1)[-1]
            await route.fulfill(path=str(file), content_type="text/javascript")

        await page.route(f"{ROUTE_ORIGIN}/rn-runtime/**", fulfill)

    started = time.perf_counter()
    try:
        await page.set_content(html, wait_until="domcontentloaded", timeout=30000)
        ready_error = None
        try:
            await page.wait_for_function("window.__RN_PREVIEW_READY__ === true", timeout=20000)
        except Exception as exc:  # reported as a result, not raised
            ready_error = f"not ready: {exc}"
        ready_seconds = round(time.perf_counter() - started, 3)
        probe = await page.evaluate(PAGE_PROBE)
        fonts = await platform_fonts(page, '[data-testid="greeting"]')
        png = await page.screenshot(full_page=False, type="png")
        (OUT / f"{name}.png").write_bytes(png)
        for card in ("card-boxshadow", "card-legacy-shadow"):
            element = await page.query_selector(f'[data-testid="{card}"]')
            if element and name.startswith("fixture"):
                await element.screenshot(path=str(OUT / f"{name}-{card}.png"))
    finally:
        await page.close()

    image = Image.open(io.BytesIO(png)).convert("RGB")
    return {
        "ready_error": ready_error,
        "ready_seconds": ready_seconds,
        "page_errors": page_errors,
        "console_errors": console_errors,
        "console_warnings": console_warnings,
        "png_size": list(image.size),
        "png_stddev": round(sum(ImageStat.Stat(image).stddev) / 3, 2),
        "platform_fonts": fonts,
        **probe,
    }


# ---------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------


IFRAME_HOST = """<!DOCTYPE html><html><head><meta charset="utf-8"></head>
<body style="margin:0"><iframe id="preview" title="Preview" style="border:0;width:390px;height:751px"></iframe></body></html>"""


async def capture_in_iframe(base_url: str, html: str, sandbox: str | None) -> dict[str, Any]:
    """Like the frontend: an iframe on the app's origin whose srcdoc is the preview."""
    browser = await registry._backend._get_browser()  # type: ignore[attr-defined]
    page = await browser.new_page(viewport={"width": 800, "height": 900})
    page_errors: list[str] = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    try:
        await page.goto(f"{base_url}/host.html")
        await page.evaluate(
            """([html, sandbox]) => {
                 const iframe = document.getElementById('preview');
                 if (sandbox !== null) iframe.setAttribute('sandbox', sandbox);
                 iframe.srcdoc = html;
               }""",
            [html, sandbox],
        )
        handle = await page.wait_for_selector("#preview")
        frame = await handle.content_frame()
        assert frame is not None
        ready_error = None
        try:
            await frame.wait_for_function("window.__RN_PREVIEW_READY__ === true", timeout=20000)
        except Exception as exc:
            ready_error = f"not ready: {exc}"
        probe = await frame.evaluate(PAGE_PROBE)
        # Select-and-edit needs the parent to reach into the preview document.
        parent_access = await page.evaluate(
            "document.getElementById('preview').contentWindow.document.querySelectorAll('[data-testid]').length"
        )
        return {"ready_error": ready_error, "page_errors": page_errors, "parent_dom_access": parent_access, **probe}
    finally:
        await page.close()


async def capture_offline_file(html_path: Path, profile: dict[str, Any]) -> dict[str, Any]:
    """The downloaded, fully inlined HTML opened from file:// with networking off."""
    browser = await registry._backend._get_browser()  # type: ignore[attr-defined]
    context = await browser.new_context(
        offline=True,
        viewport={"width": profile["width"], "height": profile["height"]},
        device_scale_factor=profile["scale"],
    )
    network_attempts: list[str] = []
    context.on("request", lambda request: network_attempts.append(request.url) if request.url.startswith("http") else None)
    page = await context.new_page()
    page_errors: list[str] = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    try:
        await page.goto(html_path.as_uri())
        ready_error = None
        try:
            await page.wait_for_function("window.__RN_PREVIEW_READY__ === true", timeout=20000)
        except Exception as exc:
            ready_error = f"not ready: {exc}"
        probe = await page.evaluate(PAGE_PROBE)
        png = await page.screenshot(full_page=False)
        (OUT / "offline-file.png").write_bytes(png)
        return {"ready_error": ready_error, "page_errors": page_errors, "network_attempts": network_attempts, **probe}
    finally:
        await context.close()


class Checks:
    def __init__(self) -> None:
        self.rows: list[tuple[str, str, bool, str]] = []

    def check(self, gate: str, name: str, ok: bool, detail: Any = "") -> None:
        self.rows.append((gate, name, bool(ok), str(detail)[:160]))

    @property
    def passed(self) -> bool:
        return all(ok for _, _, ok, _ in self.rows)


def main_fixture_checks(checks: Checks, mode: str, result: dict[str, Any], profile: dict[str, Any]) -> None:
    gate = "RNW-1"
    checks.check(gate, f"[{mode}] ready flag set", result["ready_error"] is None, result["ready_error"] or f'{result["ready_seconds"]}s')
    checks.check(gate, f"[{mode}] no pageerror", not result["page_errors"], result["page_errors"])
    checks.check(gate, f"[{mode}] status ok, no preview errors", result["status"] == "ok" and not result["errors"], result["errors"] or result["status"])
    expected = [round(profile["width"] * profile["scale"]), round(profile["height"] * profile["scale"])]
    checks.check(gate, f"[{mode}] png size = viewport x scale", result["png_size"] == expected, f'{result["png_size"]} vs {expected}')
    checks.check(gate, f"[{mode}] non-blank (pixel stddev > 10)", result["png_stddev"] > 10, result["png_stddev"])
    missing = [tid for tid in EXPECTED_TESTIDS if tid not in result["testIds"]]
    checks.check(gate, f"[{mode}] data-testid present", not missing, f"missing {missing}" if missing else f'{len(result["testIds"])} ids')

    gate = "RNW-4"
    checks.check(gate, f"[{mode}] __RN_MODULES__.react === window.React", result["singleReact"], result["reactVersion"])
    hook_errors = [e for e in result["errors"] if e["kind"] == "invalid_hook_call"]
    hook_console = [c for c in result["console_errors"] if "Invalid hook call" in c]
    checks.check(gate, f"[{mode}] no Invalid hook call", not hook_errors and not hook_console, hook_errors or hook_console)
    checks.check(gate, f"[{mode}] lucide + svg rendered (svg count)", result["svgCount"] >= 20, result["svgCount"])
    ring_moved = bool(result["ringPathD"]) and not result["ringPathD"].endswith(" 32 6")
    checks.check(gate, f"[{mode}] hook state inside Svg component applied", ring_moved, result["ringPathD"])


async def run() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    assert await probe_screenshot_preview(), "Chromium is not available to the backend"
    manifest = json.loads((DIST / "manifest.json").read_text())
    template = (DIST / "preview-template.html").read_text()
    fixture = (FIXTURES / "App.jsx").read_text()

    serve_root = Path(tempfile.mkdtemp(prefix="rn-gates-"))
    shutil.copytree(DIST, serve_root / "rn-runtime")
    (serve_root / "local-assets").mkdir()
    make_avatar(serve_root / "local-assets" / "avatar.png")
    server, base_url = start_static_server(serve_root)
    source = fixture.replace("__ASSET_BASE__", base_url)

    checks = Checks()
    results: dict[str, Any] = {"manifest": {k: manifest[k] for k in ("runtime", "babel", "mode", "versions", "sizes")}}

    # --- Main fixture in each runtime-loading mode --------------------------------
    modes = {
        "url": (script_tags(base_url, manifest), None),
        "route": (script_tags(ROUTE_ORIGIN, manifest), DIST),
        "inline": (
            inline_script((DIST / manifest["babel"]).read_text())
            + "\n"
            + inline_script((DIST / manifest["runtime"]).read_text()),
            None,
        ),
    }
    for mode, (scripts, route_dir) in modes.items():
        html = render(template, source, IPHONE_15_CONTENT, scripts)
        result = await capture(html, IPHONE_15_CONTENT, route_dir=route_dir, name=f"fixture-ios-{mode}")
        results[f"fixture-ios-{mode}"] = result
        main_fixture_checks(checks, mode, result, IPHONE_15_CONTENT)
    results["inline_html_bytes"] = len(render(template, source, IPHONE_15_CONTENT, modes["inline"][0]))

    url_scripts = modes["url"][0]
    ios = results["fixture-ios-url"]

    # --- Versions (RNW-5 preview) and Babel (RNW-7) -------------------------------
    checks.check("RNW-7", "Babel is 7.x", str(ios["babelVersion"]).startswith("7."), ios["babelVersion"])
    checks.check("RNW-5*", "runtime React 19.2.3 / RNW 0.21.2", ios["runtime"]["versions"]["react"] == "19.2.3" and ios["runtime"]["versions"]["react-native-web"] == "0.21.2", ios["runtime"]["versions"])

    # --- Fonts ---------------------------------------------------------------------
    # CDP reports the font file's own family name; isCustomFont means a web
    # font (our @font-face), not a font installed on this machine.
    used = [(f["familyName"], f["isCustomFont"]) for f in ios["platform_fonts"]]
    checks.check("fonts", "iOS profile rasterizes with bundled Inter", used == [("Inter", True)], ios["platform_fonts"])
    android = await capture(render(template, source, PIXEL_8_CONTENT, url_scripts), PIXEL_8_CONTENT, name="fixture-android-url")
    results["fixture-android-url"] = android
    used = [(f["familyName"], f["isCustomFont"]) for f in android["platform_fonts"]]
    checks.check("fonts", "Android profile rasterizes with bundled Roboto", used == [("Roboto", True)], android["platform_fonts"])
    expected_h = PIXEL_8_CONTENT["height"] * PIXEL_8_CONTENT["scale"]
    size_ok = android["png_size"][0] == 1080 and abs(android["png_size"][1] - expected_h) <= 2
    checks.check("RNW-1", "[android] png 1080px wide, height within 2px", size_ok, f'{android["png_size"]} vs [1080, {expected_h:.1f}]')

    # --- Safe-area insets (full-device profile) ---------------------------------
    full_device = dict(IPHONE_15_CONTENT, height=844, insets={"top": 59, "right": 0, "bottom": 34, "left": 0})
    insets = await capture(render(template, source, full_device, url_scripts), full_device, name="fixture-ios-insets")
    results["fixture-ios-insets"] = insets
    checks.check("safe-area", "SafeAreaView padding = profile insets", insets["safeAreaPadding"] == {"top": "59px", "bottom": "34px"}, insets["safeAreaPadding"])

    # --- RNW-8 (web half): shadows --------------------------------------------------
    results["shadows"] = ios["boxShadow"]
    checks.check("RNW-8*", "boxShadow and shadow* both render a CSS box-shadow", all(v and v != "none" for v in ios["boxShadow"].values()), ios["boxShadow"])
    deprecations = [w for w in ios["console_warnings"] if "deprecated" in w]
    results["deprecation_warnings"] = deprecations
    checks.check("RNW-8*", "RNW logs the shadow* deprecation (dev build)", any('"shadow*" style props are deprecated' in w for w in deprecations), deprecations)

    # --- RNW-2 precursor: iframe srcdoc on the app origin ---------------------------
    (serve_root / "host.html").write_text(IFRAME_HOST)
    iframe_cases = {
        "iframe, no sandbox, absolute URLs": (script_tags(base_url, manifest), None),
        "iframe, sandbox=allow-scripts allow-same-origin, relative URLs": (script_tags("", manifest), "allow-scripts allow-same-origin"),
    }
    for label, (scripts, sandbox) in iframe_cases.items():
        result = await capture_in_iframe(base_url, render(template, source, IPHONE_15_CONTENT, scripts), sandbox)
        results[label] = {k: result[k] for k in ("ready_error", "page_errors", "status", "errors", "parent_dom_access", "singleReact")}
        ok = result["ready_error"] is None and result["status"] == "ok" and not result["page_errors"] and result["parent_dom_access"] > 10
        checks.check("RNW-2~", label, ok, f'status={result["status"]} parent_dom_access={result["parent_dom_access"]} errors={result["errors"]}')

    # --- RNW-3 precursor: fully inlined HTML from file:// with networking off -------
    avatar_data_uri = "data:image/png;base64," + __import__("base64").b64encode((serve_root / "local-assets" / "avatar.png").read_bytes()).decode()
    offline_source = fixture.replace("__ASSET_BASE__/local-assets/avatar.png", avatar_data_uri)
    offline_html = OUT / "offline-preview.html"
    offline_html.write_text(render(template, offline_source, IPHONE_15_CONTENT, modes["inline"][0]))
    offline = await capture_offline_file(offline_html, IPHONE_15_CONTENT)
    results["offline-file"] = {k: offline[k] for k in ("ready_error", "page_errors", "network_attempts", "status", "errors")}
    ok = offline["ready_error"] is None and offline["status"] == "ok" and not offline["network_attempts"] and not offline["page_errors"]
    checks.check("RNW-3~", "inlined HTML renders from file:// offline", ok, f'status={offline["status"]} network={offline["network_attempts"]} bytes={offline_html.stat().st_size}')
    offline_html.unlink()

    # --- Broken fixtures and error reporting (RNW-7 + error contract) --------------
    expectations = {
        "broken-syntax": lambda e: any(x["kind"] == "transform" and x.get("line") == 8 and x.get("column") == 12 and "Unterminated JSX" in x["message"] for x in e),
        "broken-runtime": lambda e: len(e) == 1
        and e[0]["kind"] == "runtime"
        and e[0].get("line") == 5
        and "toFixed" in e[0]["message"]
        and e[0].get("componentStack", "").startswith("Price (App.jsx:4) < App"),
        "broken-import": lambda e: any(x["kind"] == "import" and "@expo/vector-icons" in x["message"] for x in e),
        "broken-icon": lambda e: any(x["kind"] == "unknown_icon" and x.get("name") == "HeartOutline" and "Heart" in x["message"] for x in e),
        "broken-no-default": lambda e: any(x["kind"] == "no_default_export" for x in e),
        "broken-unknown-export": lambda e: any(x["kind"] == "unknown_export" and x.get("name") == "PlatformColor" for x in e),
        "no-react-import": lambda e: not e,
    }
    expected_status = {"broken-icon": "degraded", "no-react-import": "ok"}
    small = dict(IPHONE_15_CONTENT)
    for name, predicate in expectations.items():
        src = (FIXTURES / f"{name}.jsx").read_text()
        result = await capture(render(template, src, small, url_scripts), small, name=name)
        results[name] = {k: result[k] for k in ("status", "errors", "page_errors", "ready_error", "testIds", "png_stddev")}
        gate = "RNW-7" if name == "broken-syntax" else "errors"
        ok = result["ready_error"] is None and predicate(result["errors"]) and result["status"] == expected_status.get(name, "error")
        checks.check(gate, f"{name}: status {result['status']}", ok, [(x["kind"], x.get("line"), x.get("column"), x["message"][:70]) for x in result["errors"]])
        if name == "broken-icon":
            checks.check("errors", "unknown icon renders placeholder, not a crash", "unknown-icon-HeartOutline" in result["testIds"], result["testIds"])
        if name.startswith("broken-") and name != "broken-icon":
            checks.check("errors", f"{name}: error panel visible in screenshot", "rn-preview-error" in result["testIds"] and result["png_stddev"] > 5, result["png_stddev"])

    # --- The unmodified existing tool path (capture_preview_screenshot) -----------
    legacy_html = render(template, source, IPHONE_15_CONTENT, url_scripts)
    started = time.perf_counter()
    legacy_png = await capture_preview_screenshot(legacy_html, device="mobile", full_page=True)
    legacy = Image.open(io.BytesIO(legacy_png)).convert("RGB")
    (OUT / "existing-tool-path-mobile.png").write_bytes(legacy_png)
    results["existing_tool_path"] = {"size": list(legacy.size), "seconds": round(time.perf_counter() - started, 2), "stddev": round(sum(ImageStat.Stat(legacy).stddev) / 3, 2)}
    checks.check("RNW-1", "existing capture_preview_screenshot renders it (non-blank)", results["existing_tool_path"]["stddev"] > 10, results["existing_tool_path"])

    server.shutdown()
    (OUT / "report.json").write_text(json.dumps(results, indent=2))

    width = max(len(name) for _, name, _, _ in checks.rows)
    for gate, name, ok, detail in checks.rows:
        print(f"{'PASS' if ok else 'FAIL'}  {gate:<9} {name:<{width}}  {detail}")
    print(f"\n{'ALL PASS' if checks.passed else 'FAILURES'}  ({sum(ok for *_, ok, _ in checks.rows)}/{len(checks.rows)})  report: {OUT / 'report.json'}")
    return 0 if checks.passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
