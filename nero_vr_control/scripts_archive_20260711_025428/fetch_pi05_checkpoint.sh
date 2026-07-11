#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTE_ALIAS="${XROBOT_PI05_REMOTE:-A800}"
REMOTE_ROOT="${XROBOT_PI05_REMOTE_ROOT:-/local/zqm/zxd}"
EXP_NAME="${1:-tube_pick_place}"
STEP="${2:-latest}"
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

case "$REMOTE_ROOT" in
  /local/zqm/zxd|/local/zqm/zxd/*) ;;
  *)
    echo "Refusing remote root outside /local/zqm/zxd: $REMOTE_ROOT" >&2
    exit 2
    ;;
esac

if [ "$STEP" = "latest" ]; then
  STEP="$(ssh "${SSH_OPTS[@]}" "$REMOTE" "find '$REMOTE_ROOT/checkpoints/nero_pi05/$EXP_NAME' -mindepth 1 -maxdepth 1 -type d -printf '%f\n' 2>/dev/null | sort -n | tail -n 1")"
fi
if [ -z "$STEP" ]; then
  echo "Could not find checkpoint step for exp: $EXP_NAME" >&2
  exit 1
fi

mkdir -p "$ROOT/checkpoints/nero_pi05/$EXP_NAME"
rsync -a --info=progress2 -e "$RSYNC_RSH" \
  "$REMOTE:$REMOTE_ROOT/checkpoints/nero_pi05/$EXP_NAME/$STEP/" \
  "$ROOT/checkpoints/nero_pi05/$EXP_NAME/$STEP/"
echo "Fetched checkpoint to $ROOT/checkpoints/nero_pi05/$EXP_NAME/$STEP"
