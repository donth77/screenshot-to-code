"""React Native runtime contracts that need no browser.

RNW-5 (version parity): the preview runtime and the Expo export target the
same React and react-native-web versions, from one source of truth,
rn-runtime/expo-sdk.json.
"""

import json
from pathlib import Path
from typing import Any

import pytest

from react_native.render import MAX_ERROR_CHARS, MAX_RUNTIME_ERRORS, normalize_runtime_errors
from react_native.runtime_files import load_runtime

RN_RUNTIME = Path(__file__).resolve().parents[2] / "rn-runtime"
SHARED_WITH_EXPORT = [
    "react",
    "react-dom",
    "react-native-web",
    "react-native-svg",
    "react-native-safe-area-context",
    "lucide-react-native",
]


def _json(name: str) -> dict[str, Any]:
    return json.loads((RN_RUNTIME / name).read_text(encoding="utf-8"))


def test_runtime_package_pins_the_expo_sdk_versions() -> None:
    sdk = _json("expo-sdk.json")["dependencies"]
    package = _json("package.json")["dependencies"]
    for name in SHARED_WITH_EXPORT:
        assert package[name] == sdk[name], name
    assert package["react-native"] == f"npm:react-native-web@{sdk['react-native-web']}"
    assert package["@react-native/assets-registry"] == sdk["react-native"]


@pytest.mark.skipif(load_runtime() is None, reason="rn-runtime is not built")
def test_built_runtime_versions_match_the_expo_sdk() -> None:
    bundle = load_runtime()
    assert bundle is not None
    sdk = _json("expo-sdk.json")
    versions = bundle.manifest["versions"]
    for name in SHARED_WITH_EXPORT:
        assert versions[name] == sdk["dependencies"][name], name
    assert bundle.manifest["expoSdkVersion"] == sdk["sdk"]
    assert bundle.read_json("expo-sdk.json") == sdk


def test_device_profiles_are_internally_consistent() -> None:
    data = _json("device-profiles.json")
    assert set(data["fallbacks"]) == {"ios", "android"}
    seen: set[tuple[int, int, str]] = set()
    for device in data["devices"]:
        key = (device["pixelWidth"], device["pixelHeight"], device["platform"])
        assert key not in seen, key
        seen.add(key)
        assert device["platform"] in ("ios", "android")
        assert abs(device["pixelWidth"] / device["logicalWidth"] - device["scale"]) < 0.02, device["name"]
        assert abs(device["pixelHeight"] / device["scale"] - device["logicalHeight"]) < 2, device["name"]
        for inset in ("insetTop", "insetBottom"):
            assert device[inset] is None or 0 <= device[inset] < 80, device["name"]


def test_runtime_errors_are_deduplicated_and_trimmed_for_the_model() -> None:
    errors = normalize_runtime_errors(
        [
            {"kind": "runtime", "message": "boom", "line": 5, "fatal": True, "componentStack": "Price (App.jsx:4) < App", "key": "x"},
            {"kind": "runtime", "message": "boom", "line": 5, "fatal": True},
            {"kind": "unknown_icon", "message": "no icon", "name": "HeartOutline"},
        ],
        page_errors=["boom", "TypeError: unrelated"],
    )
    assert errors == [
        {"kind": "runtime", "message": "boom", "fatal": True, "line": 5, "component_stack": "Price (App.jsx:4) < App"},
        {"kind": "unknown_icon", "message": "no icon", "fatal": False, "name": "HeartOutline"},
        {"kind": "uncaught", "message": "TypeError: unrelated", "fatal": True},
    ]


def test_runtime_errors_are_capped() -> None:
    flood = [{"kind": "console_error", "message": f"{index} " + "x" * 2000} for index in range(100)]
    errors = normalize_runtime_errors(flood, page_errors=[])
    assert len(errors) == MAX_RUNTIME_ERRORS
    assert all(len(error["message"]) == MAX_ERROR_CHARS for error in errors)
