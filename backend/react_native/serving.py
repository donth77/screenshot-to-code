"""Serve rn-runtime/dist at /rn-runtime for the frontend's preview iframe.

The runtime and Babel files are content-hashed, so browsers may keep them
forever. The manifest, template and JSON files keep their names across
builds, so browsers revalidate them.
"""

import os
import re

from fastapi import FastAPI
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from config import RN_RUNTIME_DIST

MOUNT_PATH = "/rn-runtime"
IMMUTABLE = "public, max-age=31536000, immutable"
_HASHED_NAME = re.compile(r"\.[0-9a-f]{12}\.js$")


class RuntimeStaticFiles(StaticFiles):
    async def check_config(self) -> None:
        # Without a build the files 404 (and /api/capabilities says so)
        # instead of every request failing with a 500.
        if self.directory is not None and not os.path.isdir(self.directory):
            return
        await super().check_config()

    def file_response(
        self,
        full_path: str | os.PathLike[str],
        stat_result: os.stat_result,
        scope: Scope,
        status_code: int = 200,
    ) -> Response:
        response = super().file_response(full_path, stat_result, scope, status_code)
        hashed = _HASHED_NAME.search(os.path.basename(full_path))
        response.headers["Cache-Control"] = IMMUTABLE if hashed else "no-cache"
        return response


def configure_runtime_routes(app: FastAPI, dist_dir: str = RN_RUNTIME_DIST) -> None:
    app.mount(MOUNT_PATH, RuntimeStaticFiles(directory=dist_dir, check_dir=False), name="rn-runtime")
