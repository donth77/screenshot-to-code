"""Embedding App.jsx's images for the Expo export (DESIGN.md §13.2).

A phone can't reach the generating server's /local-assets, and Replicate
delivery URLs expire. So each quoted URL literal in App.jsx whose content is
an image becomes an entry in assets.js (``ASSETS.asset_<hash>``, a data: URI),
and the literal is replaced by that reference. ``{ uri: ASSETS.asset_x }``
renders on iOS and Android (verified in Phase 0). Anything else (links,
unreachable URLs, non-images) stays as written.
"""

import base64
import hashlib
import re
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

# A quoted http(s) URL or a root-relative /local-assets/ path; the same rule
# as frontend/src/lib/react-native/assets.ts.
URL_LITERAL_RE = re.compile(r"""(["'`])((?:https?://|/local-assets/)[^"'`\s\\]+)\1""")
JSX_ATTRIBUTE_END_RE = re.compile(r"<[A-Za-z][^<>]*\s[A-Za-z][\w-]*=$")
IMPORT_RE = re.compile(r"^import\b[^;]*;[ \t]*$", re.MULTILINE)
MAX_ASSETS = 50

# (content, mime type) of an image, or None when the URL isn't one.
ImageFetcher = Callable[[str], Awaitable[Optional[tuple[bytes, str]]]]


@dataclass(frozen=True)
class EmbeddedAsset:
    key: str
    url: str
    mime_type: str
    content: bytes

    @property
    def data_url(self) -> str:
        return f"data:{self.mime_type};base64,{base64.b64encode(self.content).decode('ascii')}"


@dataclass(frozen=True)
class EmbeddedSource:
    source: str
    assets: list[EmbeddedAsset]
    skipped: list[str]


def find_url_literals(source: str) -> list[str]:
    urls: dict[str, None] = {}
    for match in URL_LITERAL_RE.finditer(source):
        quote, url = match.group(1), match.group(2)
        if quote == "`" and "${" in url:
            continue  # a template with interpolation isn't a literal URL
        urls[url] = None
    return list(urls)


def _add_import(source: str) -> str:
    line = "import { ASSETS } from './assets';"
    imports = list(IMPORT_RE.finditer(source))
    if not imports:
        return f"{line}\n{source}"
    end = imports[-1].end()
    return f"{source[:end]}\n{line}{source[end:]}"


def _is_jsx_attribute(before: str) -> bool:
    """Whether a string literal starting here is a JSX attribute value:
    `name=` right before it, inside a tag that is still open."""
    text = before[-2000:].replace("=>", "")  # arrow functions inside {...} aren't tag ends
    return JSX_ATTRIBUTE_END_RE.search(text) is not None and text.rfind("<") > text.rfind(">")


def _replace_literals(source: str, keys: dict[str, str]) -> str:
    def replace(match: "re.Match[str]") -> str:
        key = keys.get(match.group(2))
        if key is None:
            return match.group(0)
        reference = f"ASSETS.{key}"
        # A JSX attribute string (src="...") needs braces around an expression.
        return f"{{{reference}}}" if _is_jsx_attribute(source[: match.start()]) else reference

    return URL_LITERAL_RE.sub(replace, source)


async def embed_images(source: str, fetch_image: ImageFetcher) -> EmbeddedSource:
    """Replace each image URL literal with an ASSETS reference."""
    keys: dict[str, str] = {}
    assets: dict[str, EmbeddedAsset] = {}
    skipped: list[str] = []
    for url in find_url_literals(source)[:MAX_ASSETS]:
        try:
            image = await fetch_image(url)
        except Exception as exc:  # unreachable, refused, malformed
            print(f"Expo export: skipped {url[:120]}: {type(exc).__name__}")
            image = None
        if image is None:
            skipped.append(url)
            continue
        content, mime_type = image
        key = f"asset_{hashlib.sha256(content).hexdigest()[:12]}"
        keys[url] = key
        assets.setdefault(key, EmbeddedAsset(key=key, url=url, mime_type=mime_type, content=content))
    if not keys:
        return EmbeddedSource(source=source, assets=[], skipped=skipped)
    return EmbeddedSource(
        source=_add_import(_replace_literals(source, keys)),
        assets=list(assets.values()),
        skipped=skipped,
    )


def assets_module(assets: list[EmbeddedAsset]) -> str:
    entries = "\n".join(f"  // {asset.url[:100]}\n  {asset.key}: '{asset.data_url}'," for asset in assets)
    return f"""// Images App.jsx shows, embedded so the app runs without the server that
// generated it. Each value is a data: URI; use it as an Image source's uri.
export const ASSETS = {{
{entries}
}};
"""
