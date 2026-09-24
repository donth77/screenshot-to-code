"""POST /api/export/expo: a React Native generation as an Expo project zip."""

import io
import os
from typing import Optional
from urllib.parse import unquote, urlparse

import httpx
from fastapi import APIRouter
from fastapi.responses import Response
from PIL import Image
from pydantic import BaseModel

from config import LOCAL_ASSET_DIR
from react_native.export_assets import embed_images
from react_native.expo_project import project_files, project_zip
from routes.export import MAX_ASSET_BYTES, extension_from_url, fetch_remote_asset

router = APIRouter()

LOCAL_ASSETS_PREFIX = "/local-assets/"
# React Native's Image shows raster formats; an SVG data URI doesn't render natively.
IMAGE_MIME_TYPES = {"PNG": "image/png", "JPEG": "image/jpeg", "GIF": "image/gif", "WEBP": "image/webp"}


class ExpoExportRequest(BaseModel):
    code: str


def as_image(content: bytes) -> Optional[tuple[bytes, str]]:
    """(content, mime type) when the bytes are an image React Native can show."""
    if len(content) > MAX_ASSET_BYTES:
        return None
    try:
        with Image.open(io.BytesIO(content)) as image:
            image_format = image.format or ""
    except Exception:
        return None
    mime_type = IMAGE_MIME_TYPES.get(image_format)
    return (content, mime_type) if mime_type else None


def local_asset(url: str) -> Optional[bytes]:
    """A /local-assets/ file, read from disk: a phone can't reach this server."""
    path = urlparse(url).path
    if not path.startswith(LOCAL_ASSETS_PREFIX):
        return None
    root = os.path.realpath(LOCAL_ASSET_DIR)
    file_path = os.path.realpath(os.path.join(root, unquote(path[len(LOCAL_ASSETS_PREFIX):])))
    if not file_path.startswith(root + os.sep) or not os.path.isfile(file_path):
        return None
    with open(file_path, "rb") as file:
        return file.read()


@router.post("/api/export/expo")
async def export_expo(request: ExpoExportRequest) -> Response:
    async with httpx.AsyncClient(
        timeout=20,
        headers={"User-Agent": "screenshot-to-code-export/1.0"},
    ) as client:

        async def fetch_image(url: str) -> Optional[tuple[bytes, str]]:
            content = local_asset(url)
            if content is not None:
                return as_image(content)
            if not url.startswith(("http://", "https://")):
                return None
            # Only URLs that look like images (and Replicate outputs): links stay links.
            hint = extension_from_url(url)
            if hint == "bin" and urlparse(url).hostname != "replicate.delivery":
                return None
            fetched = await fetch_remote_asset(client, url, hint)  # public hosts only
            return as_image(fetched[0]) if fetched else None

        embedded = await embed_images(request.code, fetch_image)

    files = project_files(embedded.source, embedded.assets, embedded.skipped)
    archive = project_zip(files)
    print(
        "Expo export complete: "
        f"assets={len(embedded.assets)} skipped={len(embedded.skipped)} bytes={len(archive)}"
    )
    return Response(
        content=archive,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="screenshot-to-code-expo.zip"'},
    )
