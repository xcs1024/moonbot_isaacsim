#!/usr/bin/env bash
set -euo pipefail

ADB="${ADB:-adb}"

if ! command -v "$ADB" >/dev/null 2>&1; then
  echo "adb not found. Install Android platform-tools first." >&2
  exit 1
fi

adb_args=()
if [ -n "${ADB_SERIAL:-}" ]; then
  adb_args=(-s "$ADB_SERIAL")
fi

devices_output="$("$ADB" devices)"
device_count="$(printf '%s\n' "$devices_output" | awk 'NR > 1 && $2 == "device" { count++ } END { print count + 0 }')"

if printf '%s\n' "$devices_output" | grep -q 'no permissions'; then
  echo "Quest detected, but adb has no USB permission." >&2
  echo "Fix Linux udev/plugdev permissions, or run with sudo after stopping the user adb server:" >&2
  echo "  adb kill-server && sudo $0" >&2
  exit 1
fi

if printf '%s\n' "$devices_output" | grep -q 'unauthorized'; then
  echo "Quest detected, but USB debugging is unauthorized. Put on the headset and allow USB debugging." >&2
  exit 1
fi

if [ -n "${ADB_SERIAL:-}" ]; then
  if ! "$ADB" "${adb_args[@]}" get-state >/dev/null 2>&1; then
    echo "ADB_SERIAL=$ADB_SERIAL is not an authorized adb device." >&2
    echo "$devices_output" >&2
    exit 1
  fi
elif [ "$device_count" -eq 0 ]; then
  echo "No authorized Quest/Android adb device found." >&2
  echo "$devices_output" >&2
  exit 1
elif [ "$device_count" -gt 1 ]; then
  echo "More than one adb device is connected. Set ADB_SERIAL=<serial> and run again." >&2
  echo "$devices_output" >&2
  exit 1
fi

"$ADB" "${adb_args[@]}" wait-for-device

"$ADB" "${adb_args[@]}" shell am broadcast -a com.oculus.vrpowermanager.prox_close >/dev/null
"$ADB" "${adb_args[@]}" shell settings put system screen_off_timeout 2147483647 >/dev/null
"$ADB" "${adb_args[@]}" shell svc power stayon true >/dev/null

echo "Quest keep-awake applied for this boot."
echo "It will reset after the headset reboots. Press the headset power button manually when you want it to sleep."
