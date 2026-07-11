#!/usr/bin/env bash
set -euo pipefail

missing=0
for tool in git wget sha256sum adb ip python3; do
  if command -v "$tool" >/dev/null 2>&1; then
    printf '%-12s %s\n' "$tool" "$(command -v "$tool")"
  else
    printf '%-12s missing\n' "$tool"
    missing=1
  fi
done

if ! python3 - <<'PY'
import importlib.util
missing = [name for name in ["yaml", "numpy"] if importlib.util.find_spec(name) is None]
if missing:
    raise SystemExit("missing python modules: " + ", ".join(missing))
print("python modules: yaml numpy")
PY
then
  missing=1
fi

if [ "$missing" -ne 0 ]; then
  echo
  echo "Run: bash scripts/install_system_deps.sh"
  echo "Then: python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi
