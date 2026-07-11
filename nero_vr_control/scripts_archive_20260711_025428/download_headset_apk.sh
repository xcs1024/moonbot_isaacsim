#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG="${XROBOT_CONFIG:-configs/nero_dual_agx.yml}"
HEADSET="${1:-}"

if [ -z "$HEADSET" ]; then
  echo "Usage: $0 {quest3|pico4ultra}" >&2
  exit 2
fi

PYTHON="$ROOT/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
  PYTHON="python3"
fi

mapfile -t profile < <("$PYTHON" - "$CONFIG" "$HEADSET" <<'PY'
import sys
from xrobot_nero.config import load_config

cfg = load_config(sys.argv[1])
profile = cfg.headsets.require(sys.argv[2])
print(profile.apk_path)
print(profile.apk_url)
print(profile.apk_sha256)
print(profile.display_name)
PY
)

APK="${profile[0]}"
URL="${profile[1]}"
SHA256="${profile[2]}"
DISPLAY="${profile[3]}"

mkdir -p "$(dirname "$APK")"
if [ ! -f "$APK" ]; then
  wget -O "$APK" "$URL"
fi

echo "$SHA256  $APK" | sha256sum -c -
echo "$DISPLAY APK ready: $APK"
