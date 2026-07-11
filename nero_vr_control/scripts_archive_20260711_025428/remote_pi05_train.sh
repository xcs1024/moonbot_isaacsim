#!/usr/bin/env bash
set -euo pipefail

REMOTE_ALIAS="${XROBOT_PI05_REMOTE:-A800}"
REMOTE_ROOT="${XROBOT_PI05_REMOTE_ROOT:-/local/zqm/zxd}"
REPO_ID="${1:-local/nero_tube_pick_place}"
EXP_NAME="${2:-tube_pick_place}"
OVERWRITE="${XROBOT_PI05_OVERWRITE:-1}"
SKIP_NORM_STATS="${XROBOT_PI05_SKIP_NORM_STATS:-0}"
EXTRA_SSH_OPTS=()
if [ -n "${XROBOT_PI05_SSH_OPTS:-}" ]; then
  read -r -a EXTRA_SSH_OPTS <<< "$XROBOT_PI05_SSH_OPTS"
fi

if [ -n "${XROBOT_PI05_REMOTE_HOST:-}" ]; then
  REMOTE_PORT="${XROBOT_PI05_REMOTE_PORT:-63125}"
  REMOTE_USER="${XROBOT_PI05_REMOTE_USER:-zqm}"
  REMOTE="${REMOTE_USER}@${XROBOT_PI05_REMOTE_HOST}"
  SSH_OPTS=(-p "$REMOTE_PORT" "${EXTRA_SSH_OPTS[@]}")
else
  REMOTE="$REMOTE_ALIAS"
  SSH_OPTS=("${EXTRA_SSH_OPTS[@]}")
fi

case "$REMOTE_ROOT" in
  /local/zqm/zxd|/local/zqm/zxd/*) ;;
  *)
    echo "Refusing remote root outside /local/zqm/zxd: $REMOTE_ROOT" >&2
    exit 2
    ;;
esac

ssh "${SSH_OPTS[@]}" "$REMOTE" "bash -s" -- "$REMOTE_ROOT" "$REPO_ID" "$EXP_NAME" "$OVERWRITE" "$SKIP_NORM_STATS" <<'REMOTE_SCRIPT'
set -euo pipefail

REMOTE_ROOT="$1"
REPO_ID="$2"
EXP_NAME="$3"
OVERWRITE="$4"
SKIP_NORM_STATS="$5"

case "$REMOTE_ROOT" in
  /local/zqm/zxd|/local/zqm/zxd/*) ;;
  *)
    echo "Refusing remote root outside /local/zqm/zxd: $REMOTE_ROOT" >&2
    exit 2
    ;;
esac

require_free_gb() {
  local min_gb="$1"
  local avail_kb required_kb
  avail_kb="$(df -Pk "$REMOTE_ROOT" | awk 'NR==2 {print $4}')"
  required_kb=$((min_gb * 1024 * 1024))
  if [ "$avail_kb" -lt "$required_kb" ]; then
    echo "Refusing training: $REMOTE_ROOT has less than ${min_gb} GB free" >&2
    df -h "$REMOTE_ROOT" >&2
    exit 1
  fi
}

export HF_HOME="$REMOTE_ROOT/cache/hf"
export HF_LEROBOT_HOME="$REMOTE_ROOT/datasets/lerobot"
unset LEROBOT_HOME
export UV_CACHE_DIR="$REMOTE_ROOT/cache/uv"
export UV_PYTHON_INSTALL_DIR="$REMOTE_ROOT/envs/python"
export UV_INDEX_URL="${UV_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"
export OPENPI_DATA_HOME="$REMOTE_ROOT/cache/openpi"
export GIT_LFS_SKIP_SMUDGE=1
export XLA_PYTHON_CLIENT_MEM_FRACTION="${XLA_PYTHON_CLIENT_MEM_FRACTION:-0.75}"
export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"
export UV_PROJECT_ENVIRONMENT="$REMOTE_ROOT/envs/openpi-nero"

require_free_gb "${XROBOT_PI05_TRAIN_MIN_FREE_GB:-25}"
python "$REMOTE_ROOT/tools/pi05_validate_dataset.py" "$REMOTE_ROOT/datasets/lerobot/$REPO_ID"
python "$REMOTE_ROOT/openpi_nero/apply_openpi_nero_patch.py" --openpi "$REMOTE_ROOT/openpi"

cd "$REMOTE_ROOT/openpi"
"$REMOTE_ROOT/envs/openpi-nero/bin/python" - <<'PY'
from openpi.training import config

cfg = config.get_config("nero_pi05")
print("training config:", cfg.name)
print("checkpoint_base_dir:", cfg.checkpoint_base_dir)
PY

if [ "$SKIP_NORM_STATS" = "1" ]; then
  STATS_DIR="$REMOTE_ROOT/cache/openpi/assets/nero_pi05/$REPO_ID"
  if ! find "$STATS_DIR" -type f -print -quit >/dev/null 2>&1; then
    echo "Refusing to skip norm stats: no stats files found in $STATS_DIR" >&2
    exit 1
  fi
  echo "Skipping norm stats; using existing files in $STATS_DIR"
else
  "$REMOTE_ROOT/bin/uv" run scripts/compute_norm_stats.py --config-name nero_pi05
fi
if [ "$OVERWRITE" = "1" ]; then
  "$REMOTE_ROOT/bin/uv" run scripts/train.py nero_pi05 --exp-name="$EXP_NAME" --overwrite
else
  "$REMOTE_ROOT/bin/uv" run scripts/train.py nero_pi05 --exp-name="$EXP_NAME"
fi
REMOTE_SCRIPT
