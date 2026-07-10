#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PYTHON="$ROOT/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
  PYTHON="python3"
fi

"$PYTHON" -m compileall xrobot_nero tests
"$PYTHON" - <<'PY'
from xrobot_nero.config import load_config
from xrobot_nero.safety import StepLimiter, is_deadman_active, trigger_to_width

cfg = load_config("configs/nero_dual_agx.yml")
assert cfg.name == "nero_dual_agx"
assert cfg.arms["left_arm"].channel == "can0"
assert cfg.arms["right_arm"].channel == "can1"
assert trigger_to_width(0.0, 0.07, 0.0) == 0.07
assert trigger_to_width(1.0, 0.07, 0.0) == 0.0
assert is_deadman_active(0.6, 0.5)
limiter = StepLimiter(0.1)
limiter.reset([0.0, 1.0])
assert limiter.limit([1.0, 0.0]) == [0.1, 0.9]
print("smoke test passed")
PY
