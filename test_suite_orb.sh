#!/usr/bin/env bash
ARCH="arm64"
DISTRO="ubuntu"
VM_NAME=faasvm
VM_IMAGE=images/faasvm.tar.zst

set -eo pipefail

cleanup() { CLEANUPS+=("$*"); }
cleanup_runner() {
    # Run in reverse order (LIFO)
    for ((i=${#CLEANUPS[@]}-1; i>=0; i--)); do
        eval "${CLEANUPS[i]}"
    done
}
trap cleanup_runner EXIT

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

if [ ! -f "$VM_IMAGE" ]; then
    echo "Creating VM image \"$VM_NAME\" at \"$VM_IMAGE\""

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
            ./tests/setup_vm.sh

    run_step "exporting image" \
        orbctl export "$VM_NAME" "$VM_IMAGE"

    run_step "stopping image" \
        orbctl stop "$VM_NAME"
fi

# # setup
# orbctl import -n "$VM_NAME" "$VM_IMAGE"
# # teardown
# cleanup "orbctl delete -f $VM_NAME" EXIT
#
# # test suite
# orbctl run \
#     -m "$VM_NAME" \
#     -w "$PWD" \
#     uv run pytest
