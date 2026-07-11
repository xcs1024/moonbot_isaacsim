#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON="$ROOT/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
  PYTHON="python3"
fi

CHECKPOINT_DIR="${1:-}"
if [ -z "$CHECKPOINT_DIR" ]; then
  echo "Usage: $0 checkpoints/nero_pi05/<exp>/<step>" >&2
  exit 2
fi

if [ -n "${XROBOT_OPENPI_DIR:-}" ]; then
  python3 "$ROOT/tools/openpi_nero/apply_openpi_nero_patch.py" \
    --openpi "$XROBOT_OPENPI_DIR" \
    --workspace-root "$(dirname "$XROBOT_OPENPI_DIR")"
fi

"$PYTHON" "$ROOT/tools/pi05_local_smoke.py" --checkpoint-dir "$CHECKPOINT_DIR"
