#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

rm -rf .venv
python3 -m venv .venv
. .venv/bin/activate

bash scripts/configure_pip_mirror.sh
python -m pip install -U pip setuptools wheel
python -m pip install -r requirements.txt

echo "Python environment ready: $ROOT/.venv"
