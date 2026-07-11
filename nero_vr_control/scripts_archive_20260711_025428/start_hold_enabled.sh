#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PYTHON="$ROOT/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
  PYTHON="python3"
fi
mkdir -p logs

if [ -f logs/hold_enabled.pid ] && kill -0 "$(cat logs/hold_enabled.pid)" 2>/dev/null; then
  echo "hold_enabled already running: pid $(cat logs/hold_enabled.pid)"
  exit 0
fi

if command -v setsid >/dev/null 2>&1; then
  nohup setsid "$PYTHON" -u -m xrobot_nero.hold_enabled "$@" > logs/hold_enabled.log 2>&1 &
else
  nohup "$PYTHON" -u -m xrobot_nero.hold_enabled "$@" > logs/hold_enabled.log 2>&1 &
fi
echo "$!" > logs/hold_enabled.pid
sleep 1

if kill -0 "$(cat logs/hold_enabled.pid)" 2>/dev/null; then
  echo "hold_enabled started: pid $(cat logs/hold_enabled.pid)"
else
  echo "hold_enabled failed to start. See logs/hold_enabled.log"
  exit 1
fi
