#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTE_ALIAS="${XROBOT_PI05_REMOTE:-A800}"
REMOTE_ROOT="${XROBOT_PI05_REMOTE_ROOT:-/local/zqm/zxd}"
BOOTSTRAP_MIN_FREE_GB="${XROBOT_PI05_BOOTSTRAP_MIN_FREE_GB:-40}"
OPENPI_COMMIT="${XROBOT_PI05_OPENPI_COMMIT:-c23745b5ad24e98f66967ea795a07b2588ed6c79}"
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

tar -C "$ROOT/tools" -cf - openpi_nero pi05_validate_dataset.py | ssh "${SSH_OPTS[@]}" "$REMOTE" "
  set -euo pipefail
  case '$REMOTE_ROOT' in
    /local/zqm/zxd|/local/zqm/zxd/*) ;;
    *)
      echo 'Refusing remote root outside /local/zqm/zxd: $REMOTE_ROOT' >&2
      exit 2
      ;;
  esac
  mkdir -p '$REMOTE_ROOT'
  cd '$REMOTE_ROOT'
  avail_kb=\$(df -Pk '$REMOTE_ROOT' | awk 'NR==2 {print \$4}')
  required_kb=\$(( $BOOTSTRAP_MIN_FREE_GB * 1024 * 1024 ))
  if [ \"\$avail_kb\" -lt \"\$required_kb\" ]; then
    echo \"Refusing bootstrap: '$REMOTE_ROOT' has less than $BOOTSTRAP_MIN_FREE_GB GB free\" >&2
    df -h '$REMOTE_ROOT' >&2
    exit 1
  fi
  tar -xf -
  mkdir -p '$REMOTE_ROOT/tools'
  cp '$REMOTE_ROOT/pi05_validate_dataset.py' '$REMOTE_ROOT/tools/pi05_validate_dataset.py'
  XROBOT_PI05_OPENPI_COMMIT='$OPENPI_COMMIT' bash '$REMOTE_ROOT/openpi_nero/remote_bootstrap.sh' '$REMOTE_ROOT'
"
