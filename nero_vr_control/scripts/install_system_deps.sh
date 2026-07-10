#!/usr/bin/env bash
set -euo pipefail

if ! grep -RhsE '^[[:space:]]*deb[[:space:]].*[[:space:]]jammy-updates[[:space:]]' /etc/apt/sources.list /etc/apt/sources.list.d/*.list /etc/apt/sources.list.d/*.sources >/dev/null 2>&1; then
  cat <<'EOF' | sudo tee /etc/apt/sources.list.d/jammy-updates.list >/dev/null
deb http://mirrors.aliyun.com/ubuntu/ jammy-updates main restricted universe multiverse
EOF
fi

sudo apt-get update
sudo apt-get install -y \
  git \
  adb \
  can-utils \
  build-essential \
  cmake \
  ethtool \
  iproute2 \
  python3.10-venv \
  python3-pip

echo "System dependencies installed."
