#!/usr/bin/env bash
PROJECT_DIR="$(dirname ${BASH_SOURCE[0]})"
ARCH="arm64"
DISTRO="ubuntu:noble"
VM_NAME=faasvm
VM_IMAGE=images/faasvm.tar.zst

set -eo pipefail

run_step() {
    local msg="$1"; shift
    printf "\t- %s..." "$msg"

    local errfile
    outfile=$(mktemp)
    errfile=$(mktemp)

    if "$@" 1>"$outfile" 2>"$errfile"; then
        printf "Done\n"
        rm -f "$outfile" "$errfile"
    else
        printf "ERROR\n"
        echo "=== STDOUT ==="
        cat "$outfile"
        echo "=== STDERR ==="
        cat "$errfile"
        rm -f "$outfile" "$errfile"
        return 1
    fi
}

read -ra vms <<<"$(orbctl list -q)"
for vm in "${vms[@]}"; do
    if [ "$VM_NAME" = "$vm" ]; then
        echo "ERROR: Test suite VM \"$VM_NAME\" is already running."
        echo "  - run \"orbctl delete $VM_NAME\" and re-run the test suite"
        exit 1
    fi
done

if [ ! -f "$VM_IMAGE" ]; then
    echo "No image found at $VM_IMAGE"
    echo "Creating VM image \"$VM_NAME\" at $VM_IMAGE"

    run_step "creating image directory" \
        mkdir -p "$(dirname "$VM_IMAGE")"

    run_step "creating image" \
        orbctl create \
            -a "$ARCH" \
            "$DISTRO" "$VM_NAME"

    run_step "initializing image" \
        orbctl run \
            -m "$VM_NAME" \
            -w "$PWD" \
            PROJECT_DIR="$PROJECT_DIR" ./tests/setup_vm.sh

    run_step "exporting VM to image" \
        orbctl export "$VM_NAME" "$VM_IMAGE"

    run_step "stopping VM" \
        orbctl stop "$VM_NAME"

    run_step "deleting VM" \
        orbctl delete -f "$VM_NAME"
fi

# setup
orbctl import -n "$VM_NAME" "$VM_IMAGE"
# teardown
trap "orbctl delete -f $VM_NAME" EXIT

# test suite
orbctl run \
    -m "$VM_NAME" \
    -w "$PWD" \
    sudo -u faas_user rm "$PROJECT_DIR/example.file"
    # ls -al "$PROJECT_DIR"
    # uv run python --version
