#!/usr/bin/env bash
set -euo pipefail

LEFT_CAN="${1:-can0}"
RIGHT_CAN="${2:-can1}"

check_iface() {
  local iface="$1"
  if ! ip link show "$iface" >/dev/null 2>&1; then
    echo "$iface is missing. Check USB-CAN connection and interface mapping." >&2
    return 1
  fi
  if ! ip -details link show "$iface" | grep -q "state UP"; then
    echo "$iface is not UP. Run: bash scripts/setup_can.sh can0 can1 1000000" >&2
    return 1
  fi
  if ! ip -details link show "$iface" | grep -q "can state ERROR-ACTIVE"; then
    echo "$iface is not ERROR-ACTIVE. Check CAN power, cabling, bitrate, and USB-CAN adapter." >&2
    ip -details link show "$iface" >&2
    return 1
  fi
}

check_iface "$LEFT_CAN"
check_iface "$RIGHT_CAN"
echo "CAN ready: $LEFT_CAN $RIGHT_CAN"
