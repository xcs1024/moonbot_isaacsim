#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
. .venv/bin/activate

if [ ! -d third_party/XRoboToolkit-PC-Service-Pybind ]; then
  git clone --depth 1 https://github.com/XR-Robotics/XRoboToolkit-PC-Service-Pybind.git third_party/XRoboToolkit-PC-Service-Pybind
fi

bash third_party/XRoboToolkit-PC-Service/RoboticsService/PXREARobotSDK/build.sh
mkdir -p third_party/XRoboToolkit-PC-Service-Pybind/lib
cp third_party/XRoboToolkit-PC-Service/RoboticsService/PXREARobotSDK/build/libPXREARobotSDK.so \
  third_party/XRoboToolkit-PC-Service-Pybind/lib/

export pybind11_DIR="$(python -m pybind11 --cmakedir)"
export LD_LIBRARY_PATH="$ROOT/third_party/XRoboToolkit-PC-Service-Pybind/lib:${LD_LIBRARY_PATH:-}"

python -m pip install -e third_party/XRoboToolkit-PC-Service-Pybind --no-build-isolation

echo "xrobotoolkit_sdk installed."
