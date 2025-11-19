#!/usr/bin/env bash

set -euo pipefail

VM_DIR="$(dirname "${BASH_SOURCE[0]}")"

source "$VM_DIR/common.sh"

# check for our required commands
require_cmd curl ssh-keygen docker

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

run_step "Generating base iso" \
    docker run \
        -v $VM_DIR/base.iso:/base.iso \
        -v $VM_DIR/user-data:/user-data \
        -v $VM_DIR/user-data:/meta-data \
        ubuntu:latest sh -c "
          cp /user-data /user-data-copy
          echo '      - $(cat $VM_DIR/ssh-key.pub)' >> /user-data-copy
          apt-get update && apt-get install -y -qq cloud-image-utils
          cloud-localds /base.iso /user-data-copy /meta-data
        "

# Claude security notes
# 1. Shutdown capability is fine - Use sudoers approach for simplicity
# 2. Don't share sensitive host directories with VM
# 3. Use QEMU user-mode networking (not bridged)
# 4. Set VM resource limits (memory, CPU in QEMU args)
# 5. Make VM ephemeral - recreate for each test run if paranoid
# 6. This is a test VM - it's meant to be broken into!

echo "Done!"
