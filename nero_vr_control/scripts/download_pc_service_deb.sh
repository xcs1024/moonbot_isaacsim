#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEB_DIR="$ROOT/assets/deb"
DEB="$DEB_DIR/XRoboToolkit_PC_Service_1.0.0_ubuntu_22.04_amd64.deb"
URL="https://github.com/XR-Robotics/XRoboToolkit-PC-Service/releases/download/v1.0.0/XRoboToolkit_PC_Service_1.0.0_ubuntu_22.04_amd64.deb"
SHA256="61961067eb4b41f81ed7cae35f4690dbb0ddfefb329a12b24e0b90ebc46ada91"

mkdir -p "$DEB_DIR"
if [ ! -f "$DEB" ]; then
  wget -O "$DEB" "$URL"
fi

echo "$SHA256  $DEB" | sha256sum -c -
echo "PC Service deb ready: $DEB"
