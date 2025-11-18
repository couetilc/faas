#!/usr/bin/env bash
# Builds the base qcow2 disk and SSH key used by test_suite_orb.sh.
# This runs once (or whenever you delete images/faasvm-base.qcow2).
set -euo pipefail

die() {
    >&2 echo "[build-qemu] $*"
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
    [ "$missing" -eq 0 ] || die "Install the missing commands and re-run this script."
}

# QEMU looks for firmware in <prefix>/share/qemu. Work that out from the binary
# path so we do not need any user input.
default_qemu_share_dir() {
    local bin
    bin=$(command -v qemu-system-aarch64)
    local prefix
    prefix=$(dirname "$(dirname "$bin")")
    printf "%s/share/qemu" "$prefix"
}

# Build the cloud-init seed image using whatever tool is available locally.
create_seed_image() {
    local user_data="$1"
    local meta_data="$2"
    local output="$3"
    local cloud_dir
    cloud_dir=$(dirname "$user_data")

    if command -v cloud-localds >/dev/null 2>&1; then
        cloud-localds "$output" "$user_data" "$meta_data"
        return 0
    fi
    if command -v genisoimage >/dev/null 2>&1; then
        genisoimage -output "$output" -volid cidata -joliet -rock "$user_data" "$meta_data" >/dev/null
        return 0
    fi
    if command -v mkisofs >/dev/null 2>&1; then
        mkisofs -output "$output" -volid cidata -joliet -rock "$user_data" "$meta_data" >/dev/null
        return 0
    fi
    if command -v hdiutil >/dev/null 2>&1; then
        hdiutil makehybrid -iso -joliet -default-volume-name cidata -o "$output" "$cloud_dir" >/dev/null
        if [ -f "${output}.cdr" ]; then
            mv "${output}.cdr" "$output"
        fi
        return 0
    fi
    die "Unable to build cloud-init seed image; install cloud-localds (preferred) or genisoimage/mkisofs."
}

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE_DIR="${IMAGE_DIR:-$REPO_ROOT/images}"
SSH_DIR="${SSH_DIR:-$IMAGE_DIR/faasvm-ssh}"
SETUP_SCRIPT="$REPO_ROOT/tests/setup_vm.sh"
UBUNTU_RELEASE="${UBUNTU_RELEASE:-noble}"
CLOUD_IMAGE="$IMAGE_DIR/ubuntu-${UBUNTU_RELEASE}-server-cloudimg-arm64.img"
CLOUD_URL="${CLOUD_URL:-https://cloud-images.ubuntu.com/${UBUNTU_RELEASE}/current/${UBUNTU_RELEASE}-server-cloudimg-arm64.img}"
BASE_IMAGE="${BASE_IMAGE:-$IMAGE_DIR/faasvm-base.qcow2}"
WORK_IMAGE="$IMAGE_DIR/faasvm-build.qcow2"
SEED_IMAGE="$IMAGE_DIR/faasvm-seed.iso"
SSH_KEY_PATH="$SSH_DIR/id_ed25519"

[ -f "$SETUP_SCRIPT" ] || die "Missing setup script at $SETUP_SCRIPT"
mkdir -p "$IMAGE_DIR" "$SSH_DIR"

CLOUD_INIT_DIR
CLOUD_INIT_DIR=$(mktemp -d "$IMAGE_DIR/cloudinit.XXXXXX")
USER_DATA="$CLOUD_INIT_DIR/user-data"
META_DATA="$CLOUD_INIT_DIR/meta-data"
UEFI_VARS_WORK=""

cleanup() {
    rm -rf "$CLOUD_INIT_DIR" "$SEED_IMAGE"
    if [ -n "$UEFI_VARS_WORK" ] && [ -f "$UEFI_VARS_WORK" ]; then
        rm -f "$UEFI_VARS_WORK"
    fi
}
trap cleanup EXIT

if [ -f "$BASE_IMAGE" ]; then
    echo "[build-qemu] Base image already exists at $BASE_IMAGE"
    exit 0
fi

require_cmd curl qemu-img qemu-system-aarch64 ssh-keygen

# Download the Ubuntu cloud image we will use as a base.
if [ ! -f "$CLOUD_IMAGE" ]; then
    echo "[build-qemu] Downloading Ubuntu ${UBUNTU_RELEASE} cloud image"
    curl -fsSL "$CLOUD_URL" -o "$CLOUD_IMAGE"
fi

# Generate an SSH key that the runner will use to talk to the VM.
if [ ! -f "$SSH_KEY_PATH" ]; then
    echo "[build-qemu] Generating SSH key for faasvm"
    ssh-keygen -t ed25519 -N "" -f "$SSH_KEY_PATH" >/dev/null
fi
SSH_PUB_KEY=$(cat "$SSH_KEY_PATH.pub")

# Cloud-init payload copies tests/setup_vm.sh and runs it once to configure
# uv, faas_user, etc. We also tell cloud-init to power the VM off when done.
cat >"$META_DATA" <<'EOF'
instance-id: faasvm
local-hostname: faasvm
EOF

SETUP_PAYLOAD=$(sed 's/^/        /' "$SETUP_SCRIPT")
cat >"$USER_DATA" <<EOF
#cloud-config
hostname: faasvm
package_update: true
package_upgrade: false
users:
  - default
  - name: faas_user
    groups: [sudo]
    shell: /bin/bash
    sudo: ALL=(ALL) NOPASSWD:ALL
    lock_passwd: true
    ssh_authorized_keys:
      - $SSH_PUB_KEY
write_files:
  - path: /root/setup_vm.sh
    permissions: '0755'
    owner: root:root
    content: |
$SETUP_PAYLOAD
runcmd:
  - [ bash, /root/setup_vm.sh ]
  - [ rm, -f, /root/setup_vm.sh ]
power_state:
  delay: '+0'
  mode: poweroff
  timeout: 600
  condition: true
EOF

echo "[build-qemu] Creating cloud-init seed image"
create_seed_image "$USER_DATA" "$META_DATA" "$SEED_IMAGE"

# Expand the base disk so we have room for venvs, uv cache, etc.
cp "$CLOUD_IMAGE" "$WORK_IMAGE"
qemu-img resize "$WORK_IMAGE" +20G >/dev/null

# Use the firmware bundled with QEMU. Override via QEMU_EFI_CODE/VARS if needed.
QEMU_FIRMWARE_DIR="${QEMU_FIRMWARE_DIR:-$(default_qemu_share_dir)}"
UEFI_CODE="${QEMU_EFI_CODE:-$QEMU_FIRMWARE_DIR/edk2-aarch64-code.fd}"
UEFI_VARS_SRC="${QEMU_EFI_VARS:-$QEMU_FIRMWARE_DIR/edk2-arm-vars.fd}"
[ -f "$UEFI_CODE" ] || die "UEFI firmware not found at $UEFI_CODE (set QEMU_EFI_CODE)."
[ -f "$UEFI_VARS_SRC" ] || die "UEFI variable store not found at $UEFI_VARS_SRC (set QEMU_EFI_VARS)."
UEFI_VARS_WORK=$(mktemp "$IMAGE_DIR/faasvm-ovmf-vars.XXXXXX.fd")
cp "$UEFI_VARS_SRC" "$UEFI_VARS_WORK"

VM_CPUS="${QEMU_CPUS:-4}"
VM_RAM="${QEMU_RAM:-4096}"

echo "[build-qemu] Bootstrapping VM (cpus=$VM_CPUS ram=${VM_RAM}M)"
qemu-system-aarch64 \
    -accel "${QEMU_ACCEL:-hvf}" \
    -cpu host \
    -machine virt,highmem=on \
    -smp "$VM_CPUS" \
    -m "$VM_RAM" \
    -display none \
    -serial mon:stdio \
    -drive if=pflash,format=raw,readonly=on,file="$UEFI_CODE" \
    -drive if=pflash,format=raw,file="$UEFI_VARS_WORK" \
    -drive if=virtio,cache=writeback,format=qcow2,file="$WORK_IMAGE" \
    -drive if=virtio,format=raw,file="$SEED_IMAGE" \
    -device virtio-net-pci,netdev=net0 \
    -netdev user,id=net0 || die "QEMU provisioning failed"

mv "$WORK_IMAGE" "$BASE_IMAGE"
echo "[build-qemu] Base image available at $BASE_IMAGE"
