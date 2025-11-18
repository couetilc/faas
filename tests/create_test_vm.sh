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
