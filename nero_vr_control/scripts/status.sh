#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "== tools =="
for tool in git wget sha256sum adb ip python3; do
  printf '%-12s %s\n' "$tool" "$(command -v "$tool" || echo missing)"
done

echo
echo "== python =="
if [ -x .venv/bin/python ]; then
  . .venv/bin/activate
  python - <<'PY'
mods = ["xrobot_nero", "pyAgxArm", "xrobotoolkit_teleop", "xrobotoolkit_sdk", "placo", "cv2", "tyro"]
for mod in mods:
    try:
        __import__(mod)
        print(f"{mod}: OK")
    except Exception as exc:
        print(f"{mod}: MISSING {type(exc).__name__}: {exc}")
PY
else
  echo ".venv missing"
fi

echo
echo "== headset adb =="
adb devices || true

echo
echo "== can =="
ip -details link show type can || true

echo
echo "== pc service =="
if [ -x /opt/apps/roboticsservice/runService.sh ]; then
  echo "/opt/apps/roboticsservice/runService.sh: installed"
else
  echo "/opt/apps/roboticsservice/runService.sh: missing"
fi
if [ -x .local_pc_service/opt/apps/roboticsservice/runService.sh ]; then
  echo "local PC Service: available"
else
  echo "local PC Service: missing"
fi
if pgrep -x RoboticsService >/dev/null; then
  echo "RoboticsServiceProcess: running"
else
  echo "RoboticsServiceProcess: not running"
fi
if [ -f logs/hold_enabled.pid ] && kill -0 "$(cat logs/hold_enabled.pid)" 2>/dev/null; then
  echo "Nero hold_enabled: running pid $(cat logs/hold_enabled.pid)"
else
  echo "Nero hold_enabled: not running"
fi
if [ -f assets/deb/XRoboToolkit_PC_Service_1.0.0_ubuntu_22.04_amd64.deb ]; then
  echo "PC Service deb: downloaded"
else
  echo "PC Service deb: missing"
fi
if [ -f assets/apk/quest3/XRoboToolkit-Quest-1.0.1.apk ]; then
  echo "Quest APK: downloaded"
else
  echo "Quest APK: missing"
fi
if [ -f assets/apk/pico4ultra/XRoboToolkit-PICO-1.1.1.apk ]; then
  echo "Pico APK: downloaded"
else
  echo "Pico APK: missing"
fi
