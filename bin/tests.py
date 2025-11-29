#!/usr/bin/env -S uv run --script
# /// script
# dependencies = [
#   "psutil",
# ]
# ///
import argparse
import os
import subprocess
import sys
import tempfile
import time
import socket
import shutil
import psutil
from pathlib import Path

# TODO: I need to prepare the test_runner so I don't have to do "uv run" I can
# just "pytest", I want dependencies installed ahead of time. This will be
# different for dev runner. 

ROOT = Path(__file__).parent.parent.absolute()

REQUIRED_COMMANDS = [
    "qemu-img",
    "qemu-system-aarch64",
    "ssh",
    "ssh-keygen",
    "rsync",
    "nc"
]

def require_commands(commands):
    """Check that required commands are available."""
    missing = []
    for cmd in commands:
        if shutil.which(cmd) == None:
            missing.append(cmd)

    if missing:
        print(f"Error: Missing required commands: {', '.join(missing)}",
              file=sys.stderr)
        sys.exit(1)

def run_step(description, func):
    """Run a step with a description."""
    print(f"  - {description}...", end="", flush=True)
    func()
    print()


def get_system_resources():
    """Get system CPU and memory resources."""
    max_core = psutil.cpu_count()
    min_core = 1
    # limit to half of cores on host
    core = max(max_core // 2, min_core)

    max_mem = psutil.virtual_memory().total
    min_mem = 512 * 1024 * 1024 # 512MB
    # limit to fourth of memory on host
    mem = max(max_mem // 4, min_mem)

    return core, mem


def check_port(port=2222):
    """Wait for port to be ready."""
    while True:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.1)
                s.connect(("localhost", port))
                break
        except (socket.timeout, ConnectionRefusedError, OSError):
            print(".", end="", flush=True)
            time.sleep(0.1)


def check_ssh(ssh_cmd):
    """Wait for SSH to be available."""
    while True:
        result = subprocess.run(
            ssh_cmd + ["faas_user@localhost", "true"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        if result.returncode == 0:
            break
        print(".", end="", flush=True)


def rsync_files(ssh_base):
    """Rsync test files to the VM."""
    subprocess.run(
        [
            "rsync",
            "-e", " ".join(ssh_base),
            "-qa",
            "--include", "pyproject.toml",
            "--include", "pytest.toml",
            "--include", "uv.lock",
            "--include", "src/***",
            "--include", "tests/***",
            "--exclude", "*",
            f"{ROOT}/",
            "faas_user@localhost:~"
        ],
        check=True
    )
    print("Done")


def run_once(ssh_cmd):
    """Run the test suite once."""
    subprocess.run(
        ssh_cmd + ["faas_user@localhost", "uv run pytest && sudo poweroff"],
        check=True
    )


def run_shell(ssh_cmd):
    """Run an interactive shell session."""
    print("Starting interactive session...")
    subprocess.run(
        ssh_cmd + ["-t", "faas_user@localhost", "bash -l"],
        check=True
    )
    print("Session ended, shutting down vm...")
    subprocess.run(
        ssh_cmd + ["faas_user@localhost", "sudo shutdown -h now"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )


def main():
    parser = argparse.ArgumentParser(
        description="Run the test suite.",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "-i",
        action="store_true",
        help="Run a shell in the vm"
    )
    args = parser.parse_args()

    require_commands(REQUIRED_COMMANDS)

    # tests run in overlay img so startup environment is controlled and
    # runtime effects are isolated
    base_img = ROOT / "vm" / "test_runner.img"
    test_img = ROOT / "vm" / "test_run_1.img"

    # Create overlay image
    subprocess.run(
        [
            "qemu-img", "create",
            "-f", "qcow2",
            "-F", "qcow2",
            "-b", str(base_img),
            str(test_img)
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True
    )

    def cleanup():
        test_img.unlink(missing_ok=True)

    try:
        ssh_key = ROOT / "vm" / "ssh-key"
        ssh_base = [
            "ssh",
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "ConnectTimeout=1",
            "-o", "ConnectionAttempts=1",
            "-o", "LogLevel=quiet",
            "-p", "2222",
            "-i", str(ssh_key)
        ]

        cores, mem = get_system_resources()

        print("Booting vm")

        # Get brew prefix for QEMU
        brew_prefix = subprocess.run(
            ["brew", "--prefix", "qemu"],
            capture_output=True,
            text=True,
            check=True
        ).stdout.strip()

        bios_path = f"{brew_prefix}/share/qemu/edk2-aarch64-code.fd"

        # Start QEMU
        qemu_proc = subprocess.Popen(
            [
                "qemu-system-aarch64",
                "-bios", bios_path,
                "-accel", "hvf",
                "-cpu", "host",
                "-machine", "virt,highmem=on",
                "-smp", str(cores),
                "-m", str(mem),
                "-serial", "mon:stdio",
                "-display", "none",
                "-drive", f"if=virtio,format=qcow2,file={test_img}",
                "-nic", "user,model=virtio-net-pci,hostfwd=tcp::2222-:22"
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        try:
            run_step("checking for port readiness", lambda: check_port())
            run_step(
                "checking for ssh availability...",
                lambda: check_ssh(ssh_base)
            )

            if args.i:
                print("  - copying test files onto vm...", end="", flush=True)
                rsync_files(ssh_base)
                run_shell(ssh_base)
            else:
                run_step("Running pytest", lambda: (
                    rsync_files(ssh_base),
                    run_once(ssh_base)
                ))

            # Wait for QEMU to finish
            qemu_proc.wait()

        except Exception:
            qemu_proc.kill()
            raise

    finally:
        cleanup()


if __name__ == "__main__":
    main()
