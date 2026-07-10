#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
. .venv/bin/activate

bash scripts/configure_pip_mirror.sh

python -m pip install -e third_party/pyAgxArm
python -m pip install -e third_party/XRoboToolkit-Teleop-Sample-Python --no-deps --no-build-isolation
python -m pip install \
  meshcat \
  placo \
  opencv-python-headless \
  tyro \
  pybind11
python -m pip install -e . --no-build-isolation
bash scripts/build_xrobotoolkit_sdk.sh

echo "Minimal Nero teleop runtime installed."
