"""The React Native eval set's manifest checks (evals/react_native_set.py)."""

import json
from pathlib import Path
from typing import Any

from PIL import Image

from evals.react_native_set import (
    CATEGORIES,
    MANIFEST_PATH,
    check,
    coverage_gaps,
    load_manifest,
    main,
    sha256_file,
    write_hashes,
)


def _item(file: str, **fields: Any) -> dict[str, Any]:
    return {
        "file": file,
        "source": "own capture",
        "licence": "CC0",
        "platform": "ios",
        "theme": "light",
        "categories": ["settings"],
        "long": False,
        **fields,
    }


def test_the_committed_manifest_is_well_formed() -> None:
    manifest = load_manifest()

    errors, _ = check(manifest, inputs_dir=None)

    assert manifest["set"] == "react-native"
    assert errors == []


def test_bad_fields_are_errors() -> None:
    manifest = {
        "items": [
            _item("a.png", licence="", platform="web", categories=["maps"], long="yes"),
            _item("b.png", insets={"left": 3}),
            _item("b.png"),
        ]
    }

    errors, _ = check(manifest, inputs_dir=None)

    assert errors == [
        "a.png: missing licence",
        "a.png: platform must be one of ios, android",
        f"a.png: unknown categories ['maps']; use {', '.join(CATEGORIES)}",
        "a.png: long must be true or false",
        'b.png: insets must be {"top": pt, "bottom": pt}',
        "b.png: listed more than once",
    ]


def test_images_are_checked_against_the_manifest(tmp_path: Path) -> None:
    Image.new("RGB", (1179, 2556), "#FFFFFF").save(tmp_path / "iphone.png")
    Image.new("RGB", (1179, 2556), "#000000").save(tmp_path / "unlisted.png")
    manifest = {
        "items": [
            _item("iphone.png", sha256="0" * 64, insets={"top": 59, "bottom": 20}),
            _item("missing.png"),
        ]
    }

    errors, _ = check(manifest, str(tmp_path))

    assert errors == [
        "unlisted.png: in {0} but not in the manifest".format(tmp_path),
        "iphone.png: sha256 differs from the manifest (the image changed?)",
        "iphone.png: detection finds a bottom inset of 34, not 20",
        f"missing.png: not found in {tmp_path}",
    ]


def test_coverage_follows_the_design() -> None:
    items = [_item(f"{n}.png", categories=list(CATEGORIES)) for n in range(4)]

    assert coverage_gaps(items) == [
        "4 screenshots; the design calls for 25–30",
        "no android screenshots",
        "no dark screenshots",
        "0 long stitched screenshots; the design calls for at least 3",
    ]
    full = [
        _item(f"{n}.png", platform=("ios", "android")[n % 2], theme=("light", "dark")[n // 2 % 2], categories=list(CATEGORIES), long=n < 3)
        for n in range(26)
    ]
    assert coverage_gaps(full) == []


def test_the_command_fills_hashes_and_fails_only_on_errors_unless_strict(tmp_path: Path, capsys: Any) -> None:
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    Image.new("RGB", (1179, 2556), "#FFFFFF").save(inputs / "iphone.png")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps({"set": "react-native", "items": [_item("iphone.png")]}))

    assert main(["--manifest", str(manifest_path), "--inputs", str(inputs), "--write-hashes"]) == 0
    assert json.loads(manifest_path.read_text())["items"][0]["sha256"] == sha256_file(str(inputs / "iphone.png"))
    assert main(["--manifest", str(manifest_path), "--inputs", str(inputs), "--strict"]) == 1
    assert "1 screenshots, 0 errors, 10 coverage gaps" in capsys.readouterr().out
    assert write_hashes(json.loads(manifest_path.read_text()), str(inputs), str(manifest_path)) == 0
    assert MANIFEST_PATH.endswith("react_native_set.json")
