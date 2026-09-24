"""Locate and read the built React Native preview runtime (rn-runtime/dist).

The build writes content-hashed script names into ``manifest.json``. A rebuild
while the backend runs replaces them, so the manifest is re-read whenever its
modification time changes.
"""

import json
import os
from dataclasses import dataclass
from typing import Any, Optional

from config import RN_RUNTIME_DIST

REQUIRED_KEYS = ("runtime", "babel", "template", "expoSdk", "deviceProfiles")


@dataclass(frozen=True)
class RuntimeBundle:
    dist_dir: str
    manifest: dict[str, Any]
    template: str

    @property
    def runtime_file(self) -> str:
        return str(self.manifest["runtime"])

    @property
    def babel_file(self) -> str:
        return str(self.manifest["babel"])

    def path(self, name: str) -> str:
        """Absolute path of a file in dist/, refusing anything outside it."""
        resolved = os.path.realpath(os.path.join(self.dist_dir, name))
        root = os.path.realpath(self.dist_dir)
        if not resolved.startswith(root + os.sep):
            raise ValueError(f"not a runtime file: {name!r}")
        return resolved

    def read_text(self, name: str) -> str:
        with open(self.path(name), encoding="utf-8") as file:
            return file.read()

    def read_json(self, name: str) -> Any:
        return json.loads(self.read_text(name))


_cache: dict[str, tuple[float, RuntimeBundle]] = {}


def load_runtime(dist_dir: Optional[str] = None) -> Optional[RuntimeBundle]:
    """The runtime bundle, or None when it hasn't been built (or is incomplete)."""
    directory = os.path.abspath(dist_dir or RN_RUNTIME_DIST)
    manifest_path = os.path.join(directory, "manifest.json")
    try:
        mtime = os.path.getmtime(manifest_path)
    except OSError:
        return None
    cached = _cache.get(directory)
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        with open(manifest_path, encoding="utf-8") as file:
            manifest: dict[str, Any] = json.load(file)
        if any(key not in manifest for key in REQUIRED_KEYS):
            return None
        bundle = RuntimeBundle(dist_dir=directory, manifest=manifest, template="")
        for key in REQUIRED_KEYS:
            if not os.path.isfile(bundle.path(str(manifest[key]))):
                return None
        bundle = RuntimeBundle(
            dist_dir=directory,
            manifest=manifest,
            template=bundle.read_text(str(manifest["template"])),
        )
    except (OSError, ValueError):
        return None
    _cache[directory] = (mtime, bundle)
    return bundle
