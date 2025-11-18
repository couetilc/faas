#!/usr/bin/env bash
# - creates images/ directory
# - checks for required commands
# - downloads ubuntu release

set -euo pipefail

TESTS_DIR="$(dirname "${BASH_SOURCE[0]}")"
VM_DIR="$TESTS_DIR/vm"

source "$TESTS_DIR/common.sh"

# check for our required commands
require_cmd curl 

# check our test image directory exists
if [ ! -d "$VM_DIR" ]; then
    run_step "Creating images directory" \
        mkdir -p "$VM_DIR" 
else
    echo "✓ Images directory exists"
fi

# download our ubuntu release
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
