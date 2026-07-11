#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
THIRD_PARTY="$ROOT/third_party"
mkdir -p "$THIRD_PARTY"

if ! command -v git >/dev/null 2>&1; then
  echo "git is required for third-party checkout."
  echo "Run: bash scripts/install_system_deps.sh"
  echo "Archive fallback is intentionally disabled because the XR sample archive is large and slow."
  exit 1
fi

fetch_repo() {
  local name="$1"
  local repo="$2"
  local ref="$3"
  local dest="$THIRD_PARTY/$name"

  if [ -d "$dest/.git" ]; then
    echo "$name already cloned; updating to $ref"
    git -C "$dest" fetch --depth 1 origin "$ref"
    git -C "$dest" checkout FETCH_HEAD
    return
  fi

  git clone --depth 1 --branch "$ref" "$repo" "$dest" || git clone --depth 1 "$repo" "$dest"
}

fetch_repo "XRoboToolkit-Teleop-Sample-Python" "https://github.com/XR-Robotics/XRoboToolkit-Teleop-Sample-Python.git" "main"
fetch_repo "XRoboToolkit-PC-Service" "https://github.com/XR-Robotics/XRoboToolkit-PC-Service.git" "main"
fetch_repo "pyAgxArm" "https://github.com/agilexrobotics/pyAgxArm.git" "master"
fetch_repo "agx_arm_urdf" "https://github.com/agilexrobotics/agx_arm_urdf.git" "main"

python3 "$ROOT/scripts/generate_dual_nero_urdf.py"

cat > "$THIRD_PARTY/SOURCE_LOCK.txt" <<'EOF'
XRoboToolkit-Teleop-Sample-Python https://github.com/XR-Robotics/XRoboToolkit-Teleop-Sample-Python main
XRoboToolkit-PC-Service https://github.com/XR-Robotics/XRoboToolkit-PC-Service main
pyAgxArm https://github.com/agilexrobotics/pyAgxArm master
agx_arm_urdf https://github.com/agilexrobotics/agx_arm_urdf main
EOF

echo "Third-party sources are in $THIRD_PARTY"
echo "Install Python packages next:"
echo "  pip install -e third_party/pyAgxArm"
echo "  pip install -e third_party/XRoboToolkit-Teleop-Sample-Python"
echo "  pip install -e ."
