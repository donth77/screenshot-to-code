"""Fill rn-runtime's preview template: the Python half of a two-language contract.

The frontend does the same substitution in
``frontend/src/lib/react-native/previewHtml.ts``. Both implementations must
produce byte-identical output; ``rn-runtime/test-vectors/preview-html.json``
is the shared test suite that holds them to it.

The template has two placeholders:

* ``__RN_PREVIEW_CONFIG__`` inside ``<script type="application/json">``:
  replaced by compact JSON ``{source, profile, mode}``. ``<`` is escaped as
  ``\\u003c`` so the JSON can never close its script element.
* ``<!--RN_PREVIEW_SCRIPTS-->``: replaced by ``<script src>`` tags (served
  runtime) or by the scripts themselves (self-contained file).

Substitution is a single pass, so substituted content is never re-scanned for
placeholders.
"""

import html
import json
import math
import re
from typing import Any, Literal, Mapping, cast

PreviewMode = Literal["final", "streaming"]

CONFIG_PLACEHOLDER = "__RN_PREVIEW_CONFIG__"
SCRIPTS_PLACEHOLDER = "<!--RN_PREVIEW_SCRIPTS-->"
_PLACEHOLDER_RE = re.compile(
    f"{re.escape(CONFIG_PLACEHOLDER)}|{re.escape(SCRIPTS_PLACEHOLDER)}"
)
# "<!--", "<script" and "</script" would put the HTML tokenizer into a script
# data escaped state; \x3C is "<" in strings, template literals and regexes.
_INLINE_HAZARD_RE = re.compile(r"<(?=!--|/?script)", re.IGNORECASE)


def _js_compatible(value: Any) -> Any:
    """Match JSON.stringify: integral floats print as integers (3.0 -> 3)."""
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("preview config numbers must be finite")
        return int(value) if value.is_integer() else value
    if isinstance(value, Mapping):
        mapping = cast(Mapping[Any, Any], value)
        return {str(key): _js_compatible(item) for key, item in mapping.items()}
    if isinstance(value, (list, tuple)):
        items = cast(list[Any], list(cast(Any, value)))
        return [_js_compatible(item) for item in items]
    return value


def preview_config_json(
    source: str,
    profile: Mapping[str, Any],
    mode: PreviewMode = "final",
) -> str:
    """The JSON that replaces ``__RN_PREVIEW_CONFIG__``, safe inside <script>."""
    config: dict[str, Any] = {"source": source, "profile": _js_compatible(profile), "mode": mode}
    text = json.dumps(config, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return text.replace("<", "\\u003c")


def script_tags(base_url: str, runtime_file: str, babel_file: str) -> str:
    """Tags that load Babel, then the runtime, from ``<base_url>/rn-runtime/``.

    ``base_url`` may be empty for URLs relative to the page's origin.
    """
    base = base_url.rstrip("/")
    return "\n".join(
        f'<script src="{html.escape(f"{base}/rn-runtime/{name}", quote=True)}"></script>'
        for name in (babel_file, runtime_file)
    )


def inline_script(js: str) -> str:
    """A <script> element carrying ``js`` inline, safe from early termination."""
    escaped = _INLINE_HAZARD_RE.sub(lambda _: "\\x3C", js)
    return f"<script>{escaped}</script>"


def render_preview_html(template: str, config_json: str, scripts_html: str) -> str:
    """Substitute both placeholders in one pass.

    Raises ``ValueError`` unless each placeholder appears exactly once, so a
    template edit that drops or duplicates one fails loudly.
    """
    for placeholder in (CONFIG_PLACEHOLDER, SCRIPTS_PLACEHOLDER):
        count = template.count(placeholder)
        if count != 1:
            raise ValueError(f"template must contain {placeholder} once, found {count}")
    replacements = {CONFIG_PLACEHOLDER: config_json, SCRIPTS_PLACEHOLDER: scripts_html}
    return _PLACEHOLDER_RE.sub(lambda match: replacements[match.group(0)], template)
