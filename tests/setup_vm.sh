#!/usr/bin/env bash
# Guest provisioning invoked by cloud-init. Installs tooling once so every
# test run can simply copy the repo and execute pytest as faas_user.
set -euo pipefail

export DEBIAN_FRONTEND="${DEBIAN_FRONTEND:-noninteractive}"

# Base packages needed to fetch the repo, run uv, and execute pytest.
apt-get update
apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    git \
    openssh-client \
    python3 \
    python3-pip \
    python3-venv \
    rsync

# Install uv inside the VM if it isn't already available.
if ! command -v uv >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    install -m 0755 -o root -g root /root/.local/bin/uv /usr/local/bin/uv
fi

# Minimal dedicated user/group for the test runner.
if ! getent group faas_group >/dev/null 2>&1; then
    groupadd faas_group
fi

if ! id -u faas_user >/dev/null 2>&1; then
    useradd -m -s /bin/bash faas_user
fi

usermod -aG faas_group faas_user

# Directory where the host repo will be synced each run.
install -d -o faas_user -g faas_group -m 0750 /home/faas_user/faas

# Allow the runner to power off the VM when tests finish.
cat >/etc/sudoers.d/faas_user <<'EOF'
faas_user ALL=(ALL) NOPASSWD:ALL
EOF
chmod 0440 /etc/sudoers.d/faas_user
