"""Render an App.jsx in headless Chromium and report what the preview saw.

The page loads the template with ``set_content`` (base URL ``about:blank``);
its script tags point at ``ROUTE_ORIGIN/rn-runtime/...``, which Playwright
fulfils from ``rn-runtime/dist`` on disk. No server, public URL or proxy is
involved, and nothing else on that origin resolves.

The viewport is the device profile's content area at the profile's scale, so
the screenshot has the input screenshot's pixel dimensions. Capture is
viewport-only: React Native content scrolls inside its own container, where a
full-page capture would not reach.
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Mapping, Optional, cast

from playwright.async_api import Browser, ConsoleMessage, Error as PlaywrightError, Page, Route
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from react_native.preview_html import (
    PreviewMode,
    preview_config_json,
    render_preview_html,
    script_tags,
)
from react_native.runtime_files import RuntimeBundle

ROUTE_ORIGIN = "https://rn-runtime.invalid"
READY_TIMEOUT_MS = 15000
STATE_TIMEOUT_S = 3.0
SCREENSHOT_TIMEOUT_MS = 5000
MAX_RUNTIME_ERRORS = 20
MAX_ERROR_CHARS = 500
MAX_WARNINGS = 20

_PAGE_STATE_JS = """() => ({
  status: window.__RN_PREVIEW_STATUS__ || null,
  errors: (window.__RN_PREVIEW_ERRORS__ || []).map(({ key, ...rest }) => rest),
  meta: (({ app, ...rest }) => rest)(window.__RN_PREVIEW_META__ || {}),
})"""

Inspector = Callable[[Page], Awaitable[dict[str, Any]]]


@dataclass
class PreviewRender:
    png: bytes
    status: str  # "ok" | "degraded" | "error" | "timeout"
    runtime_errors: list[dict[str, Any]]
    meta: dict[str, Any]
    ready_ms: Optional[int]
    console_warnings: list[str] = field(default_factory=lambda: [])
    extra: dict[str, Any] = field(default_factory=lambda: {})


def normalize_runtime_errors(
    preview_errors: list[dict[str, Any]],
    page_errors: list[str],
) -> list[dict[str, Any]]:
    """Merge preview-reported and Playwright-reported errors for the model.

    Keeps the fields the model can act on, deduplicates by kind and message,
    and caps the count and length so a runaway error loop can't flood the
    context.
    """
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    def add(entry: dict[str, Any]) -> None:
        kind = str(entry.get("kind") or "error")
        message = str(entry.get("message") or "")[:MAX_ERROR_CHARS]
        if (kind, message) in seen or len(merged) >= MAX_RUNTIME_ERRORS:
            return
        seen.add((kind, message))
        item: dict[str, Any] = {"kind": kind, "message": message, "fatal": bool(entry.get("fatal"))}
        for key in ("line", "column", "name", "rule"):
            if entry.get(key) is not None:
                item[key] = entry[key]
        if entry.get("componentStack"):
            item["component_stack"] = str(entry["componentStack"])[:MAX_ERROR_CHARS]
        if entry.get("frame"):
            item["frame"] = str(entry["frame"])[:MAX_ERROR_CHARS]
        merged.append(item)

    for entry in preview_errors:
        add(entry)
    preview_messages = {str(entry.get("message") or "") for entry in preview_errors}
    for message in page_errors:
        # Uncaught errors usually reach __RN_PREVIEW_ERRORS__ too.
        if not any(message in known or known in message for known in preview_messages if known):
            add({"kind": "uncaught", "message": message, "fatal": True})
    return merged


def preview_page(
    bundle: RuntimeBundle,
    source: str,
    profile: Mapping[str, Any],
    base_url: str,
    mode: PreviewMode = "final",
) -> str:
    """The template, filled to load the runtime from ``{base_url}/rn-runtime/``."""
    return render_preview_html(
        bundle.template,
        preview_config_json(source, profile, mode),
        script_tags(base_url, bundle.runtime_file, bundle.babel_file),
    )


def preview_html_for(bundle: RuntimeBundle, source: str, profile: Mapping[str, Any], mode: PreviewMode = "final") -> str:
    """The template, filled for a Playwright render (runtime via route interception)."""
    return preview_page(bundle, source, profile, ROUTE_ORIGIN, mode)


async def render_preview(
    browser: Browser,
    bundle: RuntimeBundle,
    source: str,
    profile: Mapping[str, Any],
    *,
    mode: PreviewMode = "final",
    ready_timeout_ms: int = READY_TIMEOUT_MS,
    inspect: Optional[Inspector] = None,
) -> PreviewRender:
    """Render ``source`` at ``profile`` and screenshot the viewport.

    ``inspect`` runs against the settled page before the screenshot and its
    result is returned in ``extra`` (tests use it to probe the DOM).
    """
    page = await browser.new_page(
        viewport={"width": round(float(profile["width"])), "height": round(float(profile["height"]))},
        device_scale_factor=float(profile["scale"]),
    )
    page_errors: list[str] = []
    console_warnings: list[str] = []

    def on_console(message: ConsoleMessage) -> None:
        if message.type == "warning" and len(console_warnings) < MAX_WARNINGS:
            console_warnings.append(message.text[:MAX_ERROR_CHARS])

    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.on("console", on_console)

    async def fulfill(route: Route) -> None:
        name = route.request.url.rsplit("/", 1)[-1]
        try:
            path = bundle.path(name)
        except ValueError:
            await route.abort()
            return
        await route.fulfill(path=path, content_type="text/javascript; charset=utf-8")

    await page.route(f"{ROUTE_ORIGIN}/rn-runtime/*", fulfill)
    ready_ms: Optional[int] = None
    state: dict[str, Any] = {}
    extra: dict[str, Any] = {}
    png = b""
    try:
        started = time.perf_counter()
        try:
            # A hung App.jsx (an infinite loop) can block parsing or rendering;
            # every step below is bounded so the tool always returns.
            await page.set_content(
                preview_html_for(bundle, source, profile, mode),
                wait_until="domcontentloaded",
                timeout=ready_timeout_ms,
            )
            await page.wait_for_function("window.__RN_PREVIEW_READY__ === true", timeout=ready_timeout_ms)
            ready_ms = round((time.perf_counter() - started) * 1000)
        except PlaywrightTimeoutError:
            ready_ms = None
        try:
            state = cast(dict[str, Any], await asyncio.wait_for(page.evaluate(_PAGE_STATE_JS), STATE_TIMEOUT_S))
        except (asyncio.TimeoutError, PlaywrightError):
            state = {}
        if inspect is not None and ready_ms is not None:
            extra = await inspect(page)
        try:
            png = await page.screenshot(full_page=False, type="png", timeout=SCREENSHOT_TIMEOUT_MS)
        except PlaywrightError:
            png = b""
    finally:
        await page.close()

    preview_errors = cast(list[dict[str, Any]], state.get("errors") or [])
    status = str(state.get("status") or "error") if ready_ms is not None else "timeout"
    runtime_errors = normalize_runtime_errors(preview_errors, page_errors)
    if ready_ms is None:
        runtime_errors.insert(
            0,
            {
                "kind": "timeout",
                "message": f"The preview did not finish rendering within {ready_timeout_ms // 1000} s.",
                "fatal": True,
            },
        )
    return PreviewRender(
        png=png,
        status=status,
        runtime_errors=runtime_errors,
        meta=cast(dict[str, Any], state.get("meta") or {}),
        ready_ms=ready_ms,
        console_warnings=console_warnings,
        extra=extra,
    )
