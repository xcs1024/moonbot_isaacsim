#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE_DIR="/opt/apps/roboticsservice"
if [ ! -x "$SERVICE_DIR/RoboticsServiceProcess" ]; then
  SERVICE_DIR="$ROOT/.local_pc_service/opt/apps/roboticsservice"
fi
if [ ! -x "$SERVICE_DIR/RoboticsServiceProcess" ]; then
  echo "XRoboToolkit PC Service is not installed."
  echo "Install it with: bash scripts/install_pc_service_deb.sh"
  exit 1
fi

export LD_LIBRARY_PATH="${LD_LIBRARY_PATH:-}:$SERVICE_DIR:$SERVICE_DIR/lib:$SERVICE_DIR/SDK/x64"
export QT_PLUGIN_PATH="$SERVICE_DIR/plugins/:${QT_PLUGIN_PATH:-}"
export QT_QML_PATH="$SERVICE_DIR/qml/:${QT_QML_PATH:-}"

cd "$SERVICE_DIR"
exec ./RoboticsServiceProcess
