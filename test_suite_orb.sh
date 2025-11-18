#!/usr/bin/env bash
# Boots the faas VM via QEMU, syncs the repo over SSH, and runs the pytest
# suite inside the guest. Environment variables:
#   QEMU_CPUS / QEMU_RAM    - tweak VM size (default 4 cores / 4GB)
#   QEMU_ACCEL              - override hvf if needed
#   FAASVM_SSH_PORT         - pick a fixed local SSH port
set -euo pipefail

info() {
    printf "[faasvm] %s\n" "$*"
}

die() {
    >&2 printf "[faasvm] %s\n" "$*"
    exit 1
}

require_cmd() {
    local missing=0
    for cmd in "$@"; do
        if ! command -v "$cmd" >/dev/null 2>&1; then
            >&2 echo "Missing required command: $cmd"
            missing=1
        fi
    done
    [ "$missing" -eq 0 ] || die "Install the missing commands and re-run."
}

default_qemu_share_dir() {
    local bin
    bin=$(command -v qemu-system-aarch64)
    local prefix
    prefix=$(dirname "$(dirname "$bin")")
    printf "%s/share/qemu" "$prefix"
}

locate_firmware() {
    local firmware_dir="${QEMU_FIRMWARE_DIR:-$(default_qemu_share_dir)}"
    UEFI_CODE="${QEMU_EFI_CODE:-$firmware_dir/edk2-aarch64-code.fd}"
    UEFI_VARS_TEMPLATE="${QEMU_EFI_VARS:-$firmware_dir/edk2-arm-vars.fd}"
    [ -f "$UEFI_CODE" ] || die "UEFI firmware not found at $UEFI_CODE (set QEMU_EFI_CODE)."
    [ -f "$UEFI_VARS_TEMPLATE" ] || die "UEFI variable store not found at $UEFI_VARS_TEMPLATE (set QEMU_EFI_VARS)."
}

pick_ssh_port() {
    if [ -n "${FAASVM_SSH_PORT:-}" ]; then
        printf "%s" "$FAASVM_SSH_PORT"
        return 0
    fi

    if ! command -v lsof >/dev/null 2>&1; then
        printf "%s" 2222
        return 0
    fi

    local port
    for port in $(seq 2222 2299); do
        if ! lsof -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
            printf "%s" "$port"
            return 0
        fi
    done

    die "Unable to find an available TCP port for SSH"
}

# Poll until sshd is reachable inside the guest (cloud-init can take a while).
wait_for_ssh() {
    local timeout="${1:-180}"
    local start
    start=$(date +%s)

    while true; do
        if ssh "${SSH_OPTS[@]}" faas_user@127.0.0.1 "true" >/dev/null 2>&1; then
            return 0
        fi
        sleep 2
        local now
        now=$(date +%s)
        if (( now - start > timeout )); then
            return 1
        fi
    done
}

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE_DIR="$REPO_ROOT/images"
BUILD_SCRIPT="$REPO_ROOT/scripts/build_qemu_image.sh"
BASE_IMAGE="$IMAGE_DIR/faasvm-base.qcow2"
SSH_DIR="$IMAGE_DIR/faasvm-ssh"
SSH_KEY="$SSH_DIR/id_ed25519"
PYTEST_ARGS=("$@")

mkdir -p "$IMAGE_DIR"

require_cmd qemu-system-aarch64 qemu-img rsync ssh

if [ ! -f "$BASE_IMAGE" ]; then
    info "Base VM image missing - building one now"
    bash "$BUILD_SCRIPT"
fi

[ -f "$SSH_KEY" ] || die "Missing SSH key at $SSH_KEY (re-run $BUILD_SCRIPT)."

locate_firmware

VM_CPUS="${QEMU_CPUS:-4}"
VM_RAM="${QEMU_RAM:-4096}"
SSH_PORT="$(pick_ssh_port)"

OVERLAY=$(mktemp "$IMAGE_DIR/faasvm-overlay-XXXX.qcow2")
VARS_COPY=$(mktemp "$IMAGE_DIR/faasvm-ovmf-vars-XXXX.fd")
qemu-img create -q -f qcow2 -b "$BASE_IMAGE" -F qcow2 "$OVERLAY"
cp "$UEFI_VARS_TEMPLATE" "$VARS_COPY"

SSH_OPTS=(-i "$SSH_KEY" -p "$SSH_PORT" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null)

cleanup() {
    local exit_code=$1
    trap - EXIT
    if [ -n "${QEMU_PID:-}" ] && ps -p "$QEMU_PID" >/dev/null 2>&1; then
        kill "$QEMU_PID" >/dev/null 2>&1 || true
        wait "$QEMU_PID" >/dev/null 2>&1 || true
    fi
    rm -f "$OVERLAY" "$VARS_COPY"
    exit "$exit_code"
}
trap 'cleanup "$?"' EXIT

info "Starting VM (cpus=$VM_CPUS ram=${VM_RAM}M ssh_port=$SSH_PORT)"
qemu-system-aarch64 \
    -accel "${QEMU_ACCEL:-hvf}" \
    -cpu host \
    -machine virt,highmem=on \
    -smp "$VM_CPUS" \
    -m "$VM_RAM" \
    -display none \
    -serial mon:stdio \
    -drive if=pflash,format=raw,readonly=on,file="$UEFI_CODE" \
    -drive if=pflash,format=raw,file="$VARS_COPY" \
    -drive if=virtio,cache=writeback,format=qcow2,file="$OVERLAY" \
    -device virtio-net-pci,netdev=net0 \
    -device virtio-rng-pci \
    -netdev user,id=net0,hostfwd=tcp::"$SSH_PORT"-:22 \
    -nographic &
QEMU_PID=$!

info "Waiting for SSH"
if ! wait_for_ssh 240; then
    die "Timed out waiting for SSH"
fi

info "Syncing repository"
RSYNC_RSH=$(printf 'ssh -i %q -p %q -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null' "$SSH_KEY" "$SSH_PORT")
# Mirror the repo into the VM while honoring .gitignore and skipping the VM images.
rsync -a --delete \
    --exclude '.git/' \
    --exclude 'images/' \
    --filter=':- .gitignore' \
    -e "$RSYNC_RSH" \
    "$REPO_ROOT/" "faas_user@127.0.0.1:~/faas"

REMOTE_CMD="cd ~/faas && uv run pytest"
if [ "${#PYTEST_ARGS[@]}" -gt 0 ]; then
    printf -v ARG_STRING ' %q' "${PYTEST_ARGS[@]}"
    REMOTE_CMD+=" $ARG_STRING"
fi

info "Running uv run pytest"
set +e
ssh "${SSH_OPTS[@]}" faas_user@127.0.0.1 -- bash -lc "$REMOTE_CMD"
TEST_EXIT=$?
set -e

info "Shutting down VM"
ssh "${SSH_OPTS[@]}" faas_user@127.0.0.1 "sudo poweroff" >/dev/null 2>&1 || true
wait "$QEMU_PID" >/dev/null 2>&1 || true

exit "$TEST_EXIT"
