import base64
from typing import Any, Dict, Mapping

from preview_screenshot import capture_preview_screenshot, capture_react_native_preview

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


async def run_react_native_screenshot_preview(
    _args: Dict[str, Any],
    *,
    file_state: AgentFileState,
    profile: Mapping[str, Any],
) -> ToolExecutionResult:
    """Render App.jsx on the target phone; return the screenshot and what went wrong.

    Reporting runtime errors is the point of the call, so a render that has
    them is still ok; only a failed capture is not.
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
    status_text = _REACT_NATIVE_STATUS.get(render.status, f"Status: {render.status}.")
    screenshot_text = (
        f" A screenshot of the {profile['width']} x {profile['height']} {unit} screen is attached."
        if render.png
        else " No screenshot could be taken."
    )
    details: Dict[str, Any] = {
        "status": render.status,
        "runtime_errors": render.runtime_errors,
        "status_bar": render.meta.get("statusBar"),
        "viewport": viewport,
        "screenshots": screenshots,
    }
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
