#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTE_ALIAS="${XROBOT_PI05_REMOTE:-A800}"
REMOTE_ROOT="${XROBOT_PI05_REMOTE_ROOT:-/local/zqm/zxd}"
REPO_ID="${1:-local/nero_tube_pick_place}"
LOCAL_DATASET="$ROOT/datasets/lerobot/$REPO_ID"
SYNC_EXTRA_FREE_GB="${XROBOT_PI05_SYNC_EXTRA_FREE_GB:-25}"
EXTRA_SSH_OPTS=()
if [ -n "${XROBOT_PI05_SSH_OPTS:-}" ]; then
  read -r -a EXTRA_SSH_OPTS <<< "$XROBOT_PI05_SSH_OPTS"
fi

if [ -n "${XROBOT_PI05_REMOTE_HOST:-}" ]; then
  REMOTE_PORT="${XROBOT_PI05_REMOTE_PORT:-63125}"
  REMOTE_USER="${XROBOT_PI05_REMOTE_USER:-zqm}"
  REMOTE="${REMOTE_USER}@${XROBOT_PI05_REMOTE_HOST}"
  SSH_OPTS=(-p "$REMOTE_PORT" "${EXTRA_SSH_OPTS[@]}")
  RSYNC_RSH="${XROBOT_PI05_RSYNC_RSH:-ssh -p $REMOTE_PORT ${XROBOT_PI05_SSH_OPTS:-}}"
else
  REMOTE="$REMOTE_ALIAS"
  SSH_OPTS=("${EXTRA_SSH_OPTS[@]}")
  RSYNC_RSH="${XROBOT_PI05_RSYNC_RSH:-ssh ${XROBOT_PI05_SSH_OPTS:-}}"
fi

case "$REPO_ID" in
  local/*) ;;
  *)
    echo "Expected LeRobot repo id under local/, got: $REPO_ID" >&2
    exit 2
    ;;
esac

case "$REMOTE_ROOT" in
  /local/zqm/zxd|/local/zqm/zxd/*) ;;
  *)
    echo "Refusing remote root outside /local/zqm/zxd: $REMOTE_ROOT" >&2
    exit 2
    ;;
esac

python3 "$ROOT/tools/pi05_validate_dataset.py" "$LOCAL_DATASET"
local_kb="$(du -sk "$LOCAL_DATASET" | awk '{print $1}')"
required_kb="$((local_kb + SYNC_EXTRA_FREE_GB * 1024 * 1024))"
ssh "${SSH_OPTS[@]}" "$REMOTE" "
  set -euo pipefail
  case '$REMOTE_ROOT' in
    /local/zqm/zxd|/local/zqm/zxd/*) ;;
    *)
      echo 'Refusing remote root outside /local/zqm/zxd: $REMOTE_ROOT' >&2
      exit 2
      ;;
  esac
  mkdir -p '$REMOTE_ROOT/datasets/lerobot/$(dirname "$REPO_ID")'
  avail_kb=\$(df -Pk '$REMOTE_ROOT' | awk 'NR==2 {print \$4}')
  if [ \"\$avail_kb\" -lt '$required_kb' ]; then
    echo \"Refusing sync: need dataset size plus $SYNC_EXTRA_FREE_GB GB free under '$REMOTE_ROOT'\" >&2
    df -h '$REMOTE_ROOT' >&2
    exit 1
  fi
"
rsync -a --delete --info=progress2 -e "$RSYNC_RSH" \
  "$LOCAL_DATASET/" \
  "$REMOTE:$REMOTE_ROOT/datasets/lerobot/$REPO_ID/"
echo "Synced dataset to $REMOTE:$REMOTE_ROOT/datasets/lerobot/$REPO_ID"
