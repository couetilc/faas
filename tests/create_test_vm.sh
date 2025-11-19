#!/usr/bin/env bash

set -euo pipefail

TESTS_DIR="$(dirname "${BASH_SOURCE[0]}")"
VM_DIR="$TESTS_DIR/vm"

source "$TESTS_DIR/common.sh"

# check for our required commands
require_cmd curl ssh-keygen

# check our test image directory exists
if [ ! -d "$VM_DIR" ]; then
    run_step "Creating images directory" \
        mkdir -p "$VM_DIR" 
else
    echo "✓ Images directory exists"
fi

# check ubuntu release image exists
UBUNTU_RELEASE="noble"
ARCH="arm64"
IMAGE_NAME="$UBUNTU_RELEASE-server-cloudimg-$ARCH.img"
if [ ! -f "$VM_DIR/$IMAGE_NAME" ]; then
    run_step "Downloading Ubuntu release" \
        curl -fsSL -o "$IMAGE_NAME" --output-dir "$VM_DIR/" \
            "https://cloud-images.ubuntu.com/$UBUNTU_RELEASE/current/$IMAGE_NAME"
else
    echo "✓ Ubuntu release exists"
fi

# check ssh key pair exists
if [ ! -f "$VM_DIR/ssh-key" ]; then
    run_step "Generating SSH key pair" \
        ssh-keygen -N "" -f "$VM_DIR/ssh-key"
else
    echo "✓ SSH key pair exists"
fi

# cloud init stuff now
cat > "$VM_DIR/cloud-init" <<EOF
hostname: faasvm
package_update: true
package_upgrade: false
users:
  - default
  - name: faas_user
    groups: sudo
    shell: /bin/bash
    sudo: ['ALL=(ALL) NOPASSWD: /sbin/shutdown, /sbin/poweroff, /sbin/reboot']
    ssh_authorized_keys:
      - $(cat "$VM_DIR/ssh-key.pub")
write_files:
  - path: /usr/local/bin/setup.sh
    permissions: '0755'
    content: |
      #!/bin/bash
      set -euo pipefail
      export DEBIAN_FRONTEND=noninteractive
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
      curl -LsSf https://astral.sh/uv/install.sh | sh
      install -m 0755 -o root -g root /root/.local/bin/uv /usr/local/bin/uv
runcmd:
  - /usr/local/bin/setup.sh
  - rm -f /usr/local/bin/setup.sh
power_state:
  mode: poweroff
  delay: now
EOF

# Claude security notes
# 1. Shutdown capability is fine - Use sudoers approach for simplicity
# 2. Don't share sensitive host directories with VM
# 3. Use QEMU user-mode networking (not bridged)
# 4. Set VM resource limits (memory, CPU in QEMU args)
# 5. Make VM ephemeral - recreate for each test run if paranoid
# 6. This is a test VM - it's meant to be broken into!
