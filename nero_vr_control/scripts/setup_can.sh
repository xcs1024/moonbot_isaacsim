#!/usr/bin/env bash
set -euo pipefail

LEFT_CAN="${1:-can0}"
RIGHT_CAN="${2:-can1}"
BITRATE="${3:-1000000}"

bring_up() {
  local iface="$1"
  if ip link show "$iface" >/dev/null 2>&1; then
    sudo ip link set "$iface" down || true
    sudo ip link set "$iface" up type can bitrate "$BITRATE"
    echo "$iface up at bitrate $BITRATE"
  else
    echo "$iface not found. Use pyAgxArm/scripts/ubuntu/find_all_can_port.sh to map USB-CAN adapters."
    return 1
  fi
}

bring_up "$LEFT_CAN"
bring_up "$RIGHT_CAN"
