#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-python3}"
INDEX_URL="${PIP_INDEX_URL:-https://mirrors.aliyun.com/pypi/simple/}"
TRUSTED_HOST="${PIP_TRUSTED_HOST:-mirrors.aliyun.com}"

"$PYTHON_BIN" -m pip config set global.index-url "$INDEX_URL"
"$PYTHON_BIN" -m pip config set global.trusted-host "$TRUSTED_HOST"
"$PYTHON_BIN" -m pip config set global.timeout 120

echo "pip mirror configured:"
"$PYTHON_BIN" -m pip config list
