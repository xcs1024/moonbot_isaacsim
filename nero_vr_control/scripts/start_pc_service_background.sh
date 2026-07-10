#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
mkdir -p logs

if pgrep -x RoboticsService >/dev/null; then
  echo "RoboticsServiceProcess is already running."
  exit 0
fi

if command -v script >/dev/null 2>&1; then
  nohup script -q -f -c "bash scripts/run_pc_service.sh" logs/pc_service.typescript > logs/pc_service.log 2>&1 &
else
  nohup bash scripts/run_pc_service.sh > logs/pc_service.log 2>&1 &
fi
sleep 1

if pgrep -x RoboticsService >/dev/null; then
  echo "RoboticsServiceProcess started."
else
  echo "RoboticsServiceProcess failed to start. See logs/pc_service.log"
  exit 1
fi
