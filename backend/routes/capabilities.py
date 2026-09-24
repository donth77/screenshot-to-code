from fastapi import APIRouter
from pydantic import BaseModel

from preview_screenshot import probe_screenshot_preview
from react_native.runtime_files import load_runtime

router = APIRouter()


class Capabilities(BaseModel):
    screenshot_preview: bool
    # rn-runtime/dist is built and readable (the React Native stack's preview).
    react_native_preview: bool


@router.get("/api/capabilities", response_model=Capabilities)
async def get_capabilities() -> Capabilities:
    """Backend feature availability for the frontend to reflect in settings."""
    return Capabilities(
        screenshot_preview=await probe_screenshot_preview(),
        react_native_preview=load_runtime() is not None,
    )
