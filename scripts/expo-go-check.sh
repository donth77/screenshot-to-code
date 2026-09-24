#!/usr/bin/env bash
# Open an exported React Native project in Expo Go on the iOS Simulator or an
# Android emulator, and screenshot it: the automated supplement to Phase 4's
# manual Expo Go check (design-docs/react-native/PLAN.md, task 4.5), using
# the Phase 0 method (DESIGN.md §10).
#
# UNTESTED: written in a Linux sandbox with no simulator or emulator. Needs:
#   - iOS: macOS with Xcode, a booted Simulator with Expo Go installed;
#   - Android: the Android SDK (adb) and a booted emulator with Expo Go;
#   - Node 20+, and network access for npm and Expo.
#
# Usage: scripts/expo-go-check.sh screenshot-to-code-expo.zip ios|android [seconds]
set -euo pipefail

zip_path=$(cd "$(dirname "$1")" && pwd)/$(basename "$1")
platform=${2:?ios or android}
wait_seconds=${3:-60}
out_dir=$(pwd)

work=$(mktemp -d)
trap 'kill "${expo_pid:-0}" 2>/dev/null || true; rm -rf "$work"' EXIT
unzip -q "$zip_path" -d "$work"
project=$(dirname "$(find "$work" -maxdepth 2 -name package.json | head -1)")
cd "$project"

npm install --no-audit --no-fund
# The pins should be exactly what this SDK expects.
npx expo install --check

case "$platform" in
  ios)
    # Skip Expo Go's dev-menu onboarding sheet.
    xcrun simctl spawn booted defaults write host.exp.Exponent EXDevMenuIsOnboardingFinished -bool YES || true
    ;;
  android)
    # Expo Go's onboarding sheet may cover the screen on first launch; dismiss
    # it with `adb shell input tap X Y` for your emulator if it does.
    ;;
  *)
    echo "platform must be ios or android" >&2
    exit 2
    ;;
esac

CI=1 npx expo start "--$platform" >"$out_dir/expo-go-$platform.log" 2>&1 &
expo_pid=$!
sleep "$wait_seconds"

screenshot="$out_dir/expo-go-$platform.png"
if [ "$platform" = ios ]; then
  xcrun simctl io booted screenshot "$screenshot"
else
  adb exec-out screencap -p >"$screenshot"
fi

echo "Screenshot: $screenshot"
echo "Metro log:  $out_dir/expo-go-$platform.log"
if grep -iE "error" "$out_dir/expo-go-$platform.log"; then
  echo "The log has errors (above)." >&2
  exit 1
fi
