#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG="${XROBOT_CONFIG:-configs/nero_dual_agx.yml}"
HEADSET="${1:-}"
ADB="${ADB:-adb}"

if [ -z "$HEADSET" ]; then
  echo "Usage: $0 {quest3|pico4ultra}" >&2
  exit 2
fi

if ! command -v "$ADB" >/dev/null 2>&1; then
  echo "adb is missing. Run: bash scripts/install_system_deps.sh" >&2
  exit 1
fi

PYTHON="$ROOT/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
  PYTHON="python3"
fi

mapfile -t profile < <("$PYTHON" - "$CONFIG" "$HEADSET" <<'PY'
import sys
from xrobot_nero.config import load_config

cfg = load_config(sys.argv[1])
profile = cfg.headsets.require(sys.argv[2])
print(profile.apk_path)
print(profile.display_name)
for arg in profile.install_args:
    print(arg)
PY
)

APK="${profile[0]}"
DISPLAY="${profile[1]}"
INSTALL_ARGS=("${profile[@]:2}")

if [ ! -f "$APK" ]; then
  bash "$ROOT/scripts/download_headset_apk.sh" "$HEADSET"
fi

adb_args=()
if [ -n "${ADB_SERIAL:-}" ]; then
  adb_args=(-s "$ADB_SERIAL")
fi

devices_output="$("$ADB" devices)"
device_count="$(printf '%s\n' "$devices_output" | awk 'NR > 1 && $2 == "device" { count++ } END { print count + 0 }')"

if printf '%s\n' "$devices_output" | grep -q 'no permissions'; then
  echo "$DISPLAY detected, but adb has no USB permission." >&2
  echo "$devices_output" >&2
  exit 1
fi

if printf '%s\n' "$devices_output" | grep -q 'unauthorized'; then
  echo "$DISPLAY detected, but USB debugging is unauthorized. Confirm USB debugging inside the headset." >&2
  echo "$devices_output" >&2
  exit 1
fi

if [ -n "${ADB_SERIAL:-}" ]; then
  if ! "$ADB" "${adb_args[@]}" get-state >/dev/null 2>&1; then
    echo "ADB_SERIAL=$ADB_SERIAL is not an authorized adb device." >&2
    echo "$devices_output" >&2
    exit 1
  fi
elif [ "$device_count" -eq 0 ]; then
  echo "No authorized adb device found. Connect $DISPLAY and confirm USB debugging in the headset." >&2
  echo "$devices_output" >&2
  exit 1
elif [ "$device_count" -gt 1 ]; then
  echo "More than one adb device is connected. Set ADB_SERIAL=<serial> and run again." >&2
  echo "$devices_output" >&2
  exit 1
fi

printf '%s\n' "$devices_output"
"$ADB" "${adb_args[@]}" install "${INSTALL_ARGS[@]}" "$APK"
echo "$DISPLAY APK installed."
