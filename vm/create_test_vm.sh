#!/usr/bin/env bash

set -euo pipefail

VM_DIR="$(dirname "${BASH_SOURCE[0]}")"

cd "$VM_DIR"

source common.sh

usage="./create_test_vm.sh [-h] [--help] [--clean] [--retry]

Builds a virtual machine image for running this project's test suite.

Options:
  --clean       remove all test vm build files
  --retry       remove all test vm build files then re-run the build
  --init        Re-initialize the test runner image using cloud-init
  -h, --help    show usage text   
"

# check command flags
for arg in "$@"; do
    case "$arg" in
        --help|-h)
            echo "$usage"
            exit
            ;;
        --clean)
            run_step "Removing all files" \
                rm -f ubuntu.img ssh-key* seed.iso test_runner.img
            exit
            ;;
        --retry)
            run_step "Removing all files then retrying" \
                rm -f ubuntu.img ssh-key* seed.iso test_runner.img
            break
            ;;
        --init)
            rm -f ssh-key* seed.iso test_runner.img
            ;;
    esac
done

# check for our required commands
require_cmd curl ssh-keygen docker qemu-img qemu-system-aarch64

# check ubuntu release image exists at vm/ubuntu.qcow2
if [ ! -f ubuntu.img ]; then
    printf -v image_path \
        "%s/current/%s-server-cloudimg-%s.img" \
        "noble" "noble" "arm64"

    run_step "Downloading Ubuntu release" \
        curl -fsSL -o ubuntu.img "https://cloud-images.ubuntu.com/$image_path"

    run_step "Resizing ubuntu qcow2" \
        qemu-img resize ubuntu.img +20G
else
    echo "✓ Ubuntu release exists"
fi

# check ssh key pair exists
if [ ! -f ssh-key ]; then
    run_step "Generating SSH key pair" \
        ssh-keygen -N "" -f "ssh-key"
else
    echo "✓ SSH key pair exists"
fi

if [ ! -f seed.iso ]; then
    touch seed.iso # force file mount not directory mount for docker run
    run_step "Generating seed iso" \
        docker run \
            -v ./seed.iso:/seed.iso \
            -v ./user-data:/user-data \
            -v ./meta-data:/meta-data \
            ubuntu:latest sh -c "
              set -e
              cp /user-data /user-data-copy
              echo '      - $(cat ssh-key.pub)' >> /user-data-copy
              apt-get update && apt-get install -y -qq cloud-image-utils
              cloud-localds /seed.iso /user-data-copy /meta-data
            "
else
    echo "✓ Ubuntu seed iso exists"
fi

if [ ! -f test_runner.img ]; then
    # limit to half of cores on host
    cores="$(($(sysctl -n hw.ncpu) / 2))"
    # limit to fourth of memory on host
    mem="$(($(sysctl -n hw.memsize) / (1024 * 1024 * 4)))"
    # create snapshot image from ubuntu base img
    run_step "Creating test_runner snapshot" \
        qemu-img create -f qcow2 -B qcow2 -b ubuntu.img test_runner.img
    # remove uninitialized snapshot if cloud-init fails
    trap 'rm test_runner.img' ERR
    # initialize the test_runner using cloud-init
    run_step "Booting test_runner and running cloud-init" \
        qemu-system-aarch64 \
            -bios "$(brew --prefix qemu)/share/qemu/edk2-aarch64-code.fd" \
            -accel hvf \
            -cpu host \
            -machine virt,highmem=on \
            -smp "$cores" \
            -m "$mem" \
            -display none \
            -serial mon:stdio \
            -drive if=virtio,format=raw,file=seed.iso \
            -drive if=virtio,format=qcow2,file=test_runner.img \
            -device virtio-net-pci,netdev=net0 \
            -netdev user,id=net0
    # successful initialization, no need for cleanup
    trap - ERR
else
    echo "✓ Test runner image exists"
fi

#
# Claude security notes
# 1. Shutdown capability is fine - Use sudoers approach for simplicity
# 2. Don't share sensitive host directories with VM
# 3. Use QEMU user-mode networking (not bridged)
# 4. Set VM resource limits (memory, CPU in QEMU args)
# 5. Make VM ephemeral - recreate for each test run if paranoid
# 6. This is a test VM - it's meant to be broken into!

cd - &>/dev/null
echo "Done!"
