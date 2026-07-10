#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

LEFT_CAN="${1:-can0}"
RIGHT_CAN="${2:-can1}"
BITRATE="${3:-1000000}"

if [ ! -x /opt/apps/roboticsservice/runService.sh ]; then
  bash scripts/install_pc_service_deb.sh
else
  echo "PC Service already installed at /opt/apps/roboticsservice/runService.sh"
fi

bash scripts/setup_can.sh "$LEFT_CAN" "$RIGHT_CAN" "$BITRATE"
bash scripts/status.sh
