"""The React Native eval set's committed manifest (DESIGN.md §14, PLAN.md 5.1).

The screenshots live in the gitignored ``evals_data/sets/<set>/inputs/``;
``react_native_set.json`` (next to this file) is committed and records each
one's source, licence and tags, its sha256 and, optionally, the insets
device detection should find. Each item:

    {
      "file": "ios-settings-light.png",
      "sha256": "…",                        # filled by --write-hashes
      "source": "own capture, iPhone 16, iOS 26" or a URL,
      "licence": "CC BY 4.0",
      "platform": "ios" | "android",
      "theme": "light" | "dark",
      "categories": ["settings", …],        # CATEGORIES
      "long": false,                        # a stitched long screenshot
      "insets": {"top": 59, "bottom": 34},  # optional, in pt / dp
      "notes": ""                           # optional
    }

``python -m evals.react_native_set`` checks the manifest against the images:
errors (bad fields, missing or changed images, unlisted images, insets that
detection doesn't find) always fail; gaps in DESIGN §14's coverage fail only
with ``--strict``.
"""

import argparse
import hashlib
import json
import os
from typing import Any, Mapping, Optional, Sequence, cast

from PIL import Image

MANIFEST_PATH = os.path.join(os.path.dirname(__file__), "react_native_set.json")
CATEGORIES = ("lists-feeds", "forms", "settings", "onboarding", "tab-bars", "chat", "cards")
PLATFORMS = ("ios", "android")
THEMES = ("light", "dark")
MIN_ITEMS, MAX_ITEMS = 25, 30
MIN_LONG = 3
REQUIRED_TEXT = ("file", "source", "licence")
INSET_TOLERANCE = 0.5


def load_manifest(path: str = MANIFEST_PATH) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def sha256_file(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _detected_insets(path: str) -> dict[str, float]:
    from react_native.profiles import load_device_table, read_screenshot

    with Image.open(path) as image:
        _, screen = read_screenshot(image, load_device_table())
    return {"top": screen.device.inset_top, "bottom": screen.device.inset_bottom}


def item_errors(item: Mapping[str, Any]) -> list[str]:
    """Problems with one manifest entry's fields."""
    name = str(item.get("file") or "?")
    errors = [f"{name}: missing {key}" for key in REQUIRED_TEXT if not str(item.get(key) or "").strip()]
    if item.get("platform") not in PLATFORMS:
        errors.append(f"{name}: platform must be one of {', '.join(PLATFORMS)}")
    if item.get("theme") not in THEMES:
        errors.append(f"{name}: theme must be one of {', '.join(THEMES)}")
    categories = item.get("categories")
    if not isinstance(categories, list) or not categories:
        errors.append(f"{name}: categories must be a non-empty list")
    else:
        unknown = [c for c in cast(list[Any], categories) if c not in CATEGORIES]
        if unknown:
            errors.append(f"{name}: unknown categories {unknown}; use {', '.join(CATEGORIES)}")
    if not isinstance(item.get("long", False), bool):
        errors.append(f"{name}: long must be true or false")
    insets = item.get("insets")
    if insets is not None and not (
        isinstance(insets, dict)
        and set(cast(dict[str, Any], insets)) <= {"top", "bottom"}
        and all(isinstance(v, (int, float)) for v in cast(dict[str, Any], insets).values())
    ):
        errors.append(f"{name}: insets must be {{\"top\": pt, \"bottom\": pt}}")
    return errors


def check_images(items: Sequence[Mapping[str, Any]], inputs_dir: str) -> list[str]:
    """Missing, changed or unlisted images, and insets detection disagrees with."""
    errors: list[str] = []
    listed = {str(item.get("file")) for item in items}
    present: set[str] = (
        {name for name in os.listdir(inputs_dir) if name.endswith(".png")} if os.path.isdir(inputs_dir) else set()
    )
    errors += [f"{name}: in {inputs_dir} but not in the manifest" for name in sorted(present - listed)]
    for item in items:
        name = str(item.get("file"))
        path = os.path.join(inputs_dir, name)
        if name not in present:
            errors.append(f"{name}: not found in {inputs_dir}")
            continue
        if item.get("sha256") and item["sha256"] != sha256_file(path):
            errors.append(f"{name}: sha256 differs from the manifest (the image changed?)")
        expected = item.get("insets")
        if isinstance(expected, dict):
            detected = _detected_insets(path)
            for side, value in cast(dict[str, Any], expected).items():
                if isinstance(value, (int, float)) and abs(detected[side] - value) > INSET_TOLERANCE:
                    errors.append(f"{name}: detection finds a {side} inset of {detected[side]:g}, not {value:g}")
    return errors


def coverage_gaps(items: Sequence[Mapping[str, Any]]) -> list[str]:
    """Where the set falls short of DESIGN.md §14."""
    gaps: list[str] = []
    if not MIN_ITEMS <= len(items) <= MAX_ITEMS:
        gaps.append(f"{len(items)} screenshots; the design calls for {MIN_ITEMS}–{MAX_ITEMS}")
    for field, values in (("platform", PLATFORMS), ("theme", THEMES)):
        seen = {item.get(field) for item in items}
        gaps += [f"no {value} screenshots" for value in values if value not in seen]
    seen_categories: set[str] = {str(c) for item in items for c in cast(list[Any], item.get("categories") or [])}
    gaps += [f"no {category} screenshots" for category in CATEGORIES if category not in seen_categories]
    long_count = sum(1 for item in items if item.get("long") is True)
    if long_count < MIN_LONG:
        gaps.append(f"{long_count} long stitched screenshots; the design calls for at least {MIN_LONG}")
    return gaps


def check(manifest: Mapping[str, Any], inputs_dir: Optional[str]) -> tuple[list[str], list[str]]:
    items: list[Mapping[str, Any]] = list(manifest.get("items") or [])
    errors = [error for item in items for error in item_errors(item)]
    names = [str(item.get("file")) for item in items]
    errors += [f"{name}: listed more than once" for name in sorted({n for n in names if names.count(n) > 1})]
    if inputs_dir is not None:
        errors += check_images(items, inputs_dir)
    return errors, coverage_gaps(items)


def write_hashes(manifest: dict[str, Any], inputs_dir: str, path: str) -> int:
    """Fill in missing sha256s from the images; returns how many were added."""
    added = 0
    items: list[dict[str, Any]] = manifest.get("items") or []
    for item in items:
        image = os.path.join(inputs_dir, str(item.get("file")))
        if not item.get("sha256") and os.path.exists(image):
            item["sha256"] = sha256_file(image)
            added += 1
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")
    return added


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Check the React Native eval set's manifest against its images.")
    parser.add_argument("--manifest", default=MANIFEST_PATH)
    parser.add_argument("--inputs", help="the images' folder (default: the set's inputs folder under EVALS_DIR)")
    parser.add_argument("--strict", action="store_true", help="fail on coverage gaps too")
    parser.add_argument("--write-hashes", action="store_true", help="fill in missing sha256s")
    args = parser.parse_args(argv)

    manifest = load_manifest(args.manifest)
    inputs_dir = args.inputs
    if inputs_dir is None:
        from evals.sets import get_set_inputs_dir

        inputs_dir = get_set_inputs_dir(str(manifest["set"]))
    if args.write_hashes:
        print(f"Added {write_hashes(manifest, inputs_dir, args.manifest)} sha256s to {args.manifest}")
    errors, gaps = check(manifest, inputs_dir)
    for error in errors:
        print(f"error: {error}")
    for gap in gaps:
        print(f"{'error' if args.strict else 'coverage'}: {gap}")
    items = len(manifest.get("items") or [])
    print(f"{items} screenshots, {len(errors)} errors, {len(gaps)} coverage gaps")
    return 1 if errors or (args.strict and gaps) else 0


if __name__ == "__main__":
    raise SystemExit(main())
