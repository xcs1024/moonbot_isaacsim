#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

CONFIG="${CONFIG:-configs/nero_single_right_controller.yml}"
HEADSET="${HEADSET:-pico4ultra}"
CAN_IFACE="${CAN_IFACE:-can0}"
CAN_BITRATE="${CAN_BITRATE:-1000000}"
SERVICE_DIR="${SERVICE_DIR:-/opt/apps/roboticsservice}"
PYTHON="${PYTHON:-/home/nvidia/miniconda3/envs/env_isaacsim/bin/python}"
XRSDK_ROOT="${XRSDK_ROOT:-/home/nvidia/xrobotoolkit_sdk}"
LOG_DIR="$ROOT/logs"
LOG_FILE="${LOG_FILE:-$LOG_DIR/teleop_single_right_isaac_sync.log}"
PID_FILE="${PID_FILE:-$LOG_DIR/teleop_single_right_isaac_sync.pid}"

ISAAC_SYNC_TOPIC="${ISAAC_SYNC_TOPIC:-isaac_joint_commands}"
ISAAC_SYNC_RATE="${ISAAC_SYNC_RATE:-30}"
ISAAC_SYNC_JOINT_NAMES="${ISAAC_SYNC_JOINT_NAMES:-joint1,joint2,joint3,joint4,joint5,joint6,joint7,gripper_joint1,gripper_joint2}"
ISAAC_SYNC_GRIPPER="${ISAAC_SYNC_GRIPPER:-1}"
ISAAC_ROS_DISTRO="${ISAAC_ROS_DISTRO:-${ROS_DISTRO:-jazzy}}"
RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_fastrtps_cpp}"

mkdir -p "$LOG_DIR"

if ! pgrep -af '[R]oboticsServiceProcess' >/dev/null; then
  if [ ! -x "$SERVICE_DIR/runService.sh" ] && [ ! -f "$SERVICE_DIR/runService.sh" ]; then
    echo "VR service script not found: $SERVICE_DIR/runService.sh" >&2
    exit 1
  fi
  echo "Starting VR service..."
  (cd "$SERVICE_DIR" && nohup setsid bash runService.sh > /tmp/roboticsservice.log 2>&1 < /dev/null &)
  sleep 2
fi

if ! pgrep -af '[R]oboticsServiceProcess' >/dev/null; then
  echo "VR service failed to start. See /tmp/roboticsservice.log" >&2
  tail -80 /tmp/roboticsservice.log >&2 || true
  exit 1
fi

echo "Bringing up $CAN_IFACE at $CAN_BITRATE..."
if [ "$(id -u)" -ne 0 ]; then
  if [ -t 0 ]; then
    sudo -v
  else
    sudo -S -v
  fi
fi
sudo ip link set "$CAN_IFACE" down 2>/dev/null || true
sudo ip link set "$CAN_IFACE" up type can bitrate "$CAN_BITRATE"

if [ -f "$PID_FILE" ]; then
  old_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -n "${old_pid:-}" ] && kill -0 "$old_pid" 2>/dev/null; then
    echo "Stopping previous Isaac-sync teleop pid $old_pid..."
    kill "$old_pid" 2>/dev/null || true
    sleep 2
    if kill -0 "$old_pid" 2>/dev/null; then
      echo "Previous Isaac-sync teleop pid $old_pid did not exit; forcing stop..."
      kill -9 "$old_pid" 2>/dev/null || true
      sleep 1
    fi
  fi
fi

if [ ! -x "$PYTHON" ]; then
  echo "Python not found or not executable: $PYTHON" >&2
  exit 1
fi

CONDA_PREFIX="${CONDA_PREFIX:-$(cd "$(dirname "$PYTHON")/.." && pwd)}"
PYTHON_MM="$("$PYTHON" -c 'import sys; print(f"python{sys.version_info.major}.{sys.version_info.minor}")')"
ISAAC_ROS2_BASE="$CONDA_PREFIX/lib/$PYTHON_MM/site-packages/isaacsim/exts/isaacsim.ros2.core"
ISAAC_ROS2_DIR="$ISAAC_ROS2_BASE/$ISAAC_ROS_DISTRO"
if [ ! -d "$ISAAC_ROS2_DIR/rclpy" ]; then
  if [ -d "$ISAAC_ROS2_BASE/jazzy/rclpy" ]; then
    ISAAC_ROS_DISTRO="jazzy"
  elif [ -d "$ISAAC_ROS2_BASE/humble/rclpy" ]; then
    ISAAC_ROS_DISTRO="humble"
  else
    echo "Isaac Sim ROS2 libraries not found under $ISAAC_ROS2_BASE" >&2
    exit 1
  fi
  ISAAC_ROS2_DIR="$ISAAC_ROS2_BASE/$ISAAC_ROS_DISTRO"
fi

export PYTHONUNBUFFERED=1
export ROS_PACKAGE_PATH="$ROOT/third_party:${ROS_PACKAGE_PATH:-}"
export ROS_DISTRO="$ISAAC_ROS_DISTRO"
export RMW_IMPLEMENTATION
export PYTHONPATH="$ISAAC_ROS2_DIR/rclpy:${PYTHONPATH:-}"

XRSDK_LIB_DIR="$XRSDK_ROOT/lib"
if [ "$(uname -m)" = "aarch64" ]; then
  XRSDK_LIB_DIR="$XRSDK_ROOT/lib/aarch64:$ROOT/third_party/XRoboToolkit-PC-Service-Pybind/lib/aarch64:$XRSDK_LIB_DIR"
fi
export LD_LIBRARY_PATH="$ISAAC_ROS2_DIR/lib:$XRSDK_LIB_DIR:${LD_LIBRARY_PATH:-}"

: > "$LOG_FILE"
echo "Starting single-arm right-controller teleop with Isaac Sim joint sync in foreground..."
echo "Log: $LOG_FILE"
echo "Isaac sync: topic=$ISAAC_SYNC_TOPIC distro=$ROS_DISTRO joints=$ISAAC_SYNC_JOINT_NAMES rate=${ISAAC_SYNC_RATE}Hz gripper=$ISAAC_SYNC_GRIPPER"
echo "Exit: hold B on controller for 0.5s, or press Ctrl+C here. Arms stay enabled."

sync_gripper_args=()
if [ "$ISAAC_SYNC_GRIPPER" = "0" ] || [ "$ISAAC_SYNC_GRIPPER" = "false" ]; then
  sync_gripper_args+=(--no-isaac-sync-gripper)
fi

"$PYTHON" -u -m xrobot_nero.teleop \
  --config "$CONFIG" \
  --headset "$HEADSET" \
  --real \
  --disable-log \
  --isaac-sync \
  --isaac-sync-topic "$ISAAC_SYNC_TOPIC" \
  --isaac-sync-joint-names "$ISAAC_SYNC_JOINT_NAMES" \
  --isaac-sync-rate "$ISAAC_SYNC_RATE" \
  --isaac-sync-ros-distro "$ROS_DISTRO" \
  "${sync_gripper_args[@]}" \
  > >(tee -a "$LOG_FILE") 2>&1 &

teleop_pid=$!
echo "$teleop_pid" > "$PID_FILE"

cleanup() {
  if kill -0 "$teleop_pid" 2>/dev/null; then
    echo "Stopping teleop pid $teleop_pid..."
    kill "$teleop_pid" 2>/dev/null || true
    wait "$teleop_pid" 2>/dev/null || true
  fi
}
trap cleanup INT TERM

wait "$teleop_pid"
status=$?
rm -f "$PID_FILE"
exit "$status"
