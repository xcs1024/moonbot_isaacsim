#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEB="$ROOT/assets/deb/XRoboToolkit_PC_Service_1.0.0_ubuntu_22.04_amd64.deb"

if [ ! -f "$DEB" ]; then
  bash "$ROOT/scripts/download_pc_service_deb.sh"
fi

sudo apt-get install -y "$DEB"
echo "PC Service installed. Start it with: bash scripts/run_pc_service.sh"
