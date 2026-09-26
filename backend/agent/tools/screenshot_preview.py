import base64
import io
from typing import Any, Dict, Mapping, Optional

from PIL import Image, ImageDraw, ImageFont

from preview_screenshot import capture_preview_screenshot, capture_react_native_preview
from react_native.profiles import decode_image

from agent.state import AgentFileState
from agent.tools.types import ToolExecutionResult, ToolMultimodalPart


PREVIEW_VIEWPORTS = ("desktop", "mobile")


async def run_screenshot_preview(
    _args: Dict[str, Any],
    *,
    file_state: AgentFileState,
) -> ToolExecutionResult:
    """Render the current HTML and return screenshots.

    These previews are for *seeing*, not keeping: the model views them as
    attached image bytes (multimodal parts) to verify its work and never
    embeds them in its output, so they are NOT persisted as assets. A data
    URL is inlined into the summary purely so the UI can show the same preview.
    """
    if not file_state.content:
        return ToolExecutionResult(
            ok=False,
            result={"error": "No file exists yet. Call create_file first."},
            summary={"error": "No file to screenshot"},
        )

    screenshots: list[Dict[str, Any]] = []
    multimodal_parts: list[ToolMultimodalPart] = []
    try:
        for viewport in PREVIEW_VIEWPORTS:
            image_bytes = await capture_preview_screenshot(
                file_state.content,
                device=viewport,
                full_page=True,
            )
            display_name = f"preview_{viewport}.png"
            image_part_index = len(multimodal_parts)
            encoded_image = base64.b64encode(image_bytes).decode("ascii")
            data_url = f"data:image/png;base64,{encoded_image}"
            screenshots.append(
                {
                    "viewport": viewport,
                    "full_page": True,
                    "image_part_index": image_part_index,
                    "image_display_name": display_name,
                    "image_bytes": len(image_bytes),
                    # Inlined for the UI thumbnail only — never stored as an asset.
                    "image_url": data_url,
                    "status": "ok",
                }
            )
            multimodal_parts.append(
                ToolMultimodalPart(
                    display_name=display_name,
                    mime_type="image/png",
                    data=image_bytes,
                )
            )
    except Exception as exc:
        print(f"Preview screenshot failed: {exc}")
        return ToolExecutionResult(
            ok=False,
            result={"error": f"Screenshot failed: {exc}"},
            summary={"error": "Screenshot failed"},
        )

    result: Dict[str, Any] = {
        "content": (
            "Full-page desktop and mobile screenshots of the current preview "
            "are attached."
        ),
        "details": {
            "screenshots": [
                {
                    "viewport": screenshot["viewport"],
                    "full_page": screenshot["full_page"],
                    "image_part_index": screenshot["image_part_index"],
                    "image_display_name": screenshot["image_display_name"],
                    "image_bytes": screenshot["image_bytes"],
                }
                for screenshot in screenshots
            ],
        },
    }
    summary: Dict[str, Any] = {
        "screenshots": screenshots,
        "status": "ok",
    }
    return ToolExecutionResult(
        ok=True,
        result=result,
        summary=summary,
        multimodal_parts=multimodal_parts,
    )


_REACT_NATIVE_STATUS = {
    "ok": "App.jsx rendered without errors.",
    "degraded": "App.jsx rendered, with the problems listed in runtime_errors.",
    "error": "App.jsx failed to render. Fix runtime_errors first.",
    "timeout": "App.jsx did not finish rendering in time. Look for an infinite loop or a hang.",
}


_COMPARISON_LABEL_PX = 30
# The gutter between the two holds the guide lines' numbers.
_COMPARISON_GAP_PX = 40
# Guide lines every 50 pt (dp), numbered every 100, so positions can be read
# off and compared. Magenta shows on light and dark screens alike.
_GUIDE_STEP = 50
_GUIDE_COLOR = (255, 0, 170)
# The cropped input and the render differ by at most a pixel of rounding.
_COMPARISON_SIZE_TOLERANCE_PX = 2


def side_by_side(reference_url: Optional[str], render_png: bytes, profile: Mapping[str, Any]) -> Optional[bytes]:
    """The input screenshot and the render next to each other at the screen's
    logical size, labelled, or None when the reference isn't this screen's
    screenshot (a different size: an image attached as a reference, say).

    The model's first look at the input was earlier in the conversation, at
    whatever scale its provider chose; side by side, sizes compare directly,
    and guide lines across both let it measure where things are.
    """
    reference = decode_image(reference_url) if reference_url else None
    if reference is None:
        return None
    render = Image.open(io.BytesIO(render_png))
    if (
        abs(reference.width - render.width) > _COMPARISON_SIZE_TOLERANCE_PX
        or abs(reference.height - render.height) > _COMPARISON_SIZE_TOLERANCE_PX
    ):
        return None
    size = (round(float(profile["width"])), round(float(profile["height"])))
    canvas = Image.new("RGB", (size[0] * 2 + _COMPARISON_GAP_PX, size[1] + _COMPARISON_LABEL_PX), "#6B6B6B")
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default(size=18)
    for index, (label, image) in enumerate((("Input screenshot", reference), ("Your render", render))):
        x = index * (size[0] + _COMPARISON_GAP_PX)
        draw.text((x + 8, 5), label, fill="#FFFFFF", font=font)
        canvas.paste(image.convert("RGB").resize(size, Image.Resampling.LANCZOS), (x, _COMPARISON_LABEL_PX))
    guides = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    guide_draw = ImageDraw.Draw(guides)
    number_font = ImageFont.load_default(size=13)
    for y in range(_GUIDE_STEP, size[1], _GUIDE_STEP):
        numbered = y % (2 * _GUIDE_STEP) == 0
        top = _COMPARISON_LABEL_PX + y
        guide_draw.line([(0, top), (canvas.width, top)], fill=(*_GUIDE_COLOR, 200 if numbered else 110), width=1)
        if numbered:
            guide_draw.text((size[0] + _COMPARISON_GAP_PX // 2, top - 1), str(y), fill="#FFFFFF", font=number_font, anchor="mb")
    canvas = Image.alpha_composite(canvas.convert("RGBA"), guides).convert("RGB")
    buffer = io.BytesIO()
    canvas.save(buffer, "PNG")
    return buffer.getvalue()


async def run_react_native_screenshot_preview(
    _args: Dict[str, Any],
    *,
    file_state: AgentFileState,
    profile: Mapping[str, Any],
    reference_url: Optional[str] = None,
) -> ToolExecutionResult:
    """Render App.jsx on the target phone; return the screenshot and what went wrong.

    Reporting runtime errors is the point of the call, so a render that has
    them is still ok; only a failed capture is not. With the input screenshot
    as ``reference_url``, the two are also returned side by side.
    """
    if not file_state.content:
        return ToolExecutionResult(
            ok=False,
            result={"error": "No file exists yet. Call create_file first."},
            summary={"error": "No file to screenshot"},
        )
    try:
        render = await capture_react_native_preview(file_state.content, profile)
    except Exception as exc:
        print(f"React Native preview screenshot failed: {exc}")
        return ToolExecutionResult(
            ok=False,
            result={"error": f"Screenshot failed: {exc}"},
            summary={"error": "Screenshot failed"},
        )

    platform = str(profile["platform"])
    unit = "pt" if platform == "ios" else "dp"
    viewport = {key: profile[key] for key in ("platform", "width", "height", "scale")}
    screenshots: list[Dict[str, Any]] = []
    multimodal_parts: list[ToolMultimodalPart] = []
    if render.png:
        display_name = f"preview_{platform}.png"
        multimodal_parts.append(ToolMultimodalPart(display_name=display_name, mime_type="image/png", data=render.png))
        screenshots.append(
            {
                "viewport": platform,
                "full_page": False,
                "image_part_index": 0,
                "image_display_name": display_name,
                "image_bytes": len(render.png),
                "status": render.status,
            }
        )
    comparison = side_by_side(reference_url, render.png, profile) if render.png else None
    if comparison:
        multimodal_parts.append(ToolMultimodalPart(display_name="comparison.png", mime_type="image/png", data=comparison))
    status_text = _REACT_NATIVE_STATUS.get(render.status, f"Status: {render.status}.")
    screenshot_text = (
        f" A screenshot of the {profile['width']} x {profile['height']} {unit} screen is attached."
        if render.png
        else " No screenshot could be taken."
    )
    if comparison:
        screenshot_text += (
            " So is the input screenshot next to your render, both at the same scale, with guide lines"
            f" every {_GUIDE_STEP} {unit} across both: each element should be the same size and in the same place in both."
        )
    details: Dict[str, Any] = {
        "status": render.status,
        "runtime_errors": render.runtime_errors,
        "status_bar": render.meta.get("statusBar"),
        "viewport": viewport,
        "screenshots": screenshots,
    }
    if comparison:
        details["comparison"] = {"image_part_index": len(multimodal_parts) - 1, "left": "input screenshot", "right": "render"}
    summary: Dict[str, Any] = {
        "status": render.status,
        "runtime_errors": render.runtime_errors,
        "viewport": viewport,
        # Inlined for the UI thumbnail only; never stored as an asset.
        "screenshots": [
            {**shot, "image_url": "data:image/png;base64," + base64.b64encode(render.png).decode("ascii")}
            for shot in screenshots
        ],
    }
    return ToolExecutionResult(
        ok=True,
        result={"content": status_text + screenshot_text, "details": details},
        summary=summary,
        multimodal_parts=multimodal_parts or None,
    )
