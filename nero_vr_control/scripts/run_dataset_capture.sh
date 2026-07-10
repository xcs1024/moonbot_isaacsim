#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

export LD_LIBRARY_PATH="$ROOT/third_party/XRoboToolkit-PC-Service-Pybind/lib:${LD_LIBRARY_PATH:-}"
export ROS_PACKAGE_PATH="$ROOT/third_party:${ROS_PACKAGE_PATH:-}"
PYTHON="$ROOT/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
  PYTHON="python3"
fi

MODE="${1:-real}"
HEADSET="${2:-${XROBOT_HEADSET:-quest3}}"
if [ "$#" -ge 1 ]; then
  shift
fi
if [ "$#" -ge 1 ]; then
  shift
fi

case "$MODE" in
  dry-run)
    exec "$PYTHON" -m xrobot_nero.teleop \
      --config configs/nero_dual_agx.yml \
      --headset "$HEADSET" \
      --dry-run \
      --dataset-capture \
      --disable-log \
      "$@"
    ;;
  real)
    bash "$ROOT/scripts/check_can_ready.sh" can0 can1
    bash "$ROOT/scripts/stop_hold_enabled.sh"
    set +e
    "$PYTHON" -m xrobot_nero.teleop \
      --config configs/nero_dual_agx.yml \
      --headset "$HEADSET" \
      --real \
      --dataset-capture \
      --disable-log \
      "$@"
    status=$?
    set -e
    if [ "$status" -eq 0 ] && bash "$ROOT/scripts/check_can_ready.sh" can0 can1; then
      bash "$ROOT/scripts/start_hold_enabled.sh"
    elif [ "$status" -ne 0 ]; then
      echo "dataset capture exited with status $status; not starting hold_enabled after failed initialization." >&2
    fi
    exit "$status"
    ;;
  *)
    echo "Usage: $0 {dry-run|real} [quest3|pico4ultra] [teleop dataset options]"
    echo "Example: $0 real pico4ultra --dataset-repo-id local/nero_tube_pick_place --dataset-task 'pick up the test tube and place it into the tube rack'"
    exit 2
    ;;
esac
