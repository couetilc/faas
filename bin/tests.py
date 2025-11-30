#!/usr/bin/env -S uv run --script
# /// script
# dependencies = [
#   "psutil",
#   "watchfiles",
#   "qemu.qmp",
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
import signal
import threading
import asyncio
import queue
import contextlib
from pathlib import Path
from watchfiles import watch, Change
from qemu.qmp import QMPClient

# TODO: I need to prepare the test_runner so I don't have to do "uv run" I can
# just "pytest", I want dependencies installed ahead of time. This will be
# different for dev runner.

# TODO: some type of TaskThread class
# - needs to specify dependencies:
#   - parent dependencies: thread does not execute until condition from parent is satisfied.
#   - child dependencies: communicate conditions somehow
# - holds reference to a cancel event used by each TaskThread
# - maybe Queue for communication between parents/childs? (instead of single Event, could have queue that receives event messages, and also shuts down when parent finishes)
#   - queue's can send messages: (like "ready")
#   - queue's can end. See "Queue.shutdown()"
# - timing tracking (start time, end time, duration)
# - automatic resource cleanup after completion.
# - handles interrupts well and across all tasks
# - task's childrens execute concurrently.

ROOT = Path(__file__).parent.parent.absolute()

# Global shutdown flag for graceful termination
shutdown_requested = threading.Event()
shutdown_message_shown = False

ssh_key = ROOT / "vm" / "ssh-key"
ssh_port = 2222
ssh_base = [
    "ssh",
    "-o", "StrictHostKeyChecking=no",
    "-o", "UserKnownHostsFile=/dev/null",
    "-o", "ConnectTimeout=1",
    "-o", "ConnectionAttempts=1",
    "-o", "LogLevel=quiet",
    "-p", str(ssh_port),
    "-i", str(ssh_key)
]

REQUIRED_COMMANDS = [
    "qemu-img",
    "qemu-system-aarch64",
    "ssh",
    "ssh-keygen",
    "rsync",
    "nc"
]

def signal_handler(signum, frame):
    """Handle SIGINT (Ctrl+C) gracefully."""
    global shutdown_message_shown
    if not shutdown_requested.is_set():
        shutdown_requested.set()
    elif not shutdown_message_shown:
        print("\nShutting down...", flush=True)
        shutdown_message_shown = True

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
    min_mem = 512  # 512MB
    # limit to fourth of memory on host (convert bytes to MB)
    mem = max(max_mem // (1024 * 1024 * 4), min_mem)

    return core, mem


def check_port(port):
    """Wait for port to be ready."""
    while True and not shutdown_requested.is_set():
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.1)
                s.connect(("localhost", port))
                break
        except (socket.timeout, ConnectionRefusedError, OSError):
            print(".", end="", flush=True)
            time.sleep(0.1)


@contextlib.contextmanager
def port_ready(stop_event, ssh_port):
    print("[port_ready] start")
    while True and not stop_event.is_set():
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.1)
                s.connect(("localhost", ssh_port))
                break
        except (socket.timeout, ConnectionRefusedError, OSError):
            print(".", end="", flush=True)
            time.sleep(0.1)
    yield None
    print("[port_ready] end")

def check_ssh(ssh_cmd):
    """Wait for SSH to be available."""
    while True and not shutdown_requested.is_set():
        result = subprocess.run(
            ssh_cmd + ["faas_user@localhost", "true"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        if result.returncode == 0:
            break
        print(".", end="", flush=True)


@contextlib.contextmanager
def ssh_ready(stop_flag, ssh_cmd):
    print("[ssh_ready] start")
    """Wait for SSH to be available."""
    while True and not stop_flag.is_set():
        result = subprocess.run(
            ssh_cmd + ["faas_user@localhost", "true"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        if result.returncode == 0:
            break
        print(".", end="", flush=True)
    yield None
    print("[ssh_ready] end")


def rsync_files(ssh_cmd):
    """Rsync test files to the VM."""
    if shutdown_requested.is_set():
        raise KeyboardInterrupt("Shutdown requested")

    proc = subprocess.Popen(
        [
            "rsync",
            "-e", " ".join(ssh_cmd),
            "-va",  # Changed from -qa to -va for verbose output
            "--include", "pyproject.toml",
            "--include", "pytest.toml",
            "--include", "uv.lock",
            "--include", "src/***",
            "--include", "tests/***",
            "--exclude", "*",
            f"{ROOT}/",
            "faas_user@localhost:~"
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1  # Line buffered
    )

    # Stream output while checking for shutdown
    try:
        for line in proc.stdout:
            if shutdown_requested.is_set():
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                raise KeyboardInterrupt("Shutdown during rsync")
            print(line, end='')

        proc.wait()
        if proc.returncode != 0:
            raise subprocess.CalledProcessError(proc.returncode, proc.args)

        print("Done")
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


def run_once(ssh_cmd):
    """Run the test suite once."""
    subprocess.run(
        ssh_cmd + ["faas_user@localhost", "uv run pytest"],
        check=True
    )


def run_shell(ssh_cmd):
    """Run an interactive shell session."""
    print("Starting interactive session...")
    subprocess.run(
        ssh_cmd + ["-t", "faas_user@localhost", "bash -l"],
        check=True
    )


def run_tests_continuous(ssh_cmd):
    """Run tests without shutting down the VM."""
    if shutdown_requested.is_set():
        raise KeyboardInterrupt("Shutdown requested")

    proc = subprocess.Popen(
        ssh_cmd + ["faas_user@localhost", "uv run pytest"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1  # Line buffered
    )

    # Stream output while checking for shutdown
    try:
        for line in proc.stdout:
            if shutdown_requested.is_set():
                proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                raise KeyboardInterrupt("Shutdown during tests")
            print(line, end='')

        proc.wait()
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


def loop_watchfiles(stop_flag, *args, **kwargs):
    for changes in watch(*args, stop_event = stop_flag, **kwargs):
        if stop_flag.is_set():
            break
        for change_type, path in changes:
            change_name = change_type.name.lower()
            print(f"  {change_name}: {path}")
        print("\n  - copying test files onto vm...", end="", flush=True)
        rsync_files(ssh_base)
        print("\n")
        run_tests_continuous(ssh_base)
        if not stop_flag.is_set():
            print("\nWatching for changes...")

@contextlib.contextmanager
def qemu_vm(image):
    print("[qemu vm] start")

    qemu_proc = None

    try:
        brew_prefix = subprocess.run(
            ["brew", "--prefix", "qemu"],
            capture_output=True,
            text=True,
            check=True
        ).stdout.strip()
        bios_path = f"{brew_prefix}/share/qemu/edk2-aarch64-code.fd"
        cores, mem = get_system_resources()

        with (
            tempfile.NamedTemporaryFile(delete=False,suffix='.log') as qemu_log,
        ):
            ssh_key = ROOT / "vm" / "ssh-key"
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
                    "-drive", f"if=virtio,format=qcow2,file={image}",
                    "-nic", f"user,model=virtio-net-pci,hostfwd=tcp::{ssh_port}-:22",
                    "-qmp", f"unix:monitor.socket,server,nowait",
                ],
                stdout=qemu_log,
                stderr=subprocess.STDOUT
            )
            print(f"[qemu vm] log: {qemu_log.name}")
            yield qemu_proc
    except Exception as error:
        print(f"[qemu vm] exception: {error}")
        pass
    finally:
        if qemu_proc != None:
            if qemu_proc.poll() == None:
                print(f"[qemu vm] terminating qemu process")
                async def shutdown():
                    qmp = QMPClient('test-vm')
                    await qmp.connect("monitor.socket")
                    await qmp.execute('system_powerdown')
                asyncio.run(shutdown())
            qemu_proc.wait()
        print("[qemu vm] end")

# @contextmanager
# def qemu_thread(arg):
#     print("starting")
#     try:
#         yield arg + arg
#     finally:
#         print("end")
#     pass
#
def loop_qemu(stop_flag, message_queue, test_img):
    def log(*args):
        print("[LOOP_QEMU] ", *args)
    log("Booting vm")
    # Create log file for QEMU output (for debugging)
    qemu_log = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.log')
    qemu_log_path = qemu_log.name
    qemu_log.close()
    # Get brew prefix for QEMU
    brew_prefix = subprocess.run(
        ["brew", "--prefix", "qemu"],
        capture_output=True,
        text=True,
        check=True
    ).stdout.strip()
    bios_path = f"{brew_prefix}/share/qemu/edk2-aarch64-code.fd"
    cores, mem = get_system_resources()
    with open(qemu_log_path, 'w') as log_file:
        with tempfile.TemporaryFile() as monitor:
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
                    "-nic", f"user,model=virtio-net-pci,hostfwd=tcp::{ssh_port}-:22",
                    "-monitor", f"unix:{monitor.name}",
                ],
                stdout=log_file,
                stderr=subprocess.STDOUT
            )
            log(f"QEMU log: {qemu_log_path}")
            log("Connecting to QEMU monitor...")
            qmp = QMPClient('test-vm')
            # await qmp.connect(monitor.name)
            log("Connected")

            while not stop_flag.is_set():
                message = message_queue.get()
                # await qmp.execute(message)
                log(f"message: {message}")
    qemu_proc.terminate()


@contextlib.contextmanager
def overlay_image(base_image, test_image):
    print("[overlay_image] starting")
    try:
        # Remove existing overlay image if it exists
        test_image.unlink(missing_ok=True)
        # Create overlay image
        subprocess.run(
            [
                "qemu-img", "create",
                "-f", "qcow2",
                "-F", "qcow2",
                "-b", str(base_image),
                str(test_image)
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True
        )
        yield test_image
    finally:
        test_image.unlink(missing_ok=True)
        print("[overlay_image] done")


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
    parser.add_argument(
        "-w", "--watch",
        action="store_true",
        help="Watch for file changes and re-run tests"
    )
    args = parser.parse_args()

    # Register signal handler for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)

    require_commands(REQUIRED_COMMANDS)

    # tests run in overlay img so startup environment is controlled and
    # runtime effects are isolated

    base_img = ROOT / "vm" / "test_runner.img"
    test_img = ROOT / "vm" / "test_run_1.img"
    with (
        overlay_image(base_img, test_img) as image,
        qemu_vm(image) as vm,
        port_ready(shutdown_requested, ssh_port),
        ssh_ready(shutdown_requested, ssh_base),
    ):
        rsync_files(ssh_base),
        run_once(ssh_base)
        return


        # qemu_thread = threading.Thread(
        #     target=loop_qemu,
        #     args=(shutdown_requested, queue.Queue(), test_img),
        # )
        # qemu_thread.start()
        #
        if shutdown_requested.is_set():
            return

        run_step("checking for port readiness", lambda: check_port())

        if shutdown_requested.is_set():
            return

        run_step(
            "checking for ssh availability...",
            lambda: check_ssh(ssh_base)
        )

        if shutdown_requested.is_set():
            return

        if args.i:
            print("  - copying test files onto vm...", end="", flush=True)
            rsync_files(ssh_base)
            run_shell(ssh_base)
        elif args.watch:
            # Initial run
            print("  - copying test files onto vm...", end="", flush=True)
            rsync_files(ssh_base)
            print("\n")
            run_tests_continuous(ssh_base)

            # Watch for changes
            print("\n\nWatching for changes in src/ and tests/...")
            print("Press Ctrl+C to stop\n")

            watch_paths = [ROOT / "src", ROOT / "tests"]

            watchfiles_thread = threading.Thread(
                target=loop_watchfiles,
                args=(shutdown_requested, *watch_paths)
            )
            watchfiles_thread.start()
        else:
            run_step("Running pytest", lambda: (
                rsync_files(ssh_base),
                run_once(ssh_base)
            ))

            # finally:
            #     # Always cleanup, check if we need to shutdown VM
            #     print("finally cleanup")
            #     if qemu_proc.poll() is None:
            #         print("proc poll success")
            #         if args.watch or args.i:
            #             # Graceful shutdown for watch/interactive modes
            #             print("\n\nShutting down VM...")
            #             subprocess.run(
            #                 ssh_base + ["faas_user@localhost", "sudo shutdown -h now"],
            #                 stdout=subprocess.DEVNULL,
            #                 stderr=subprocess.DEVNULL,
            #                 timeout=5
            #             )
            #             try:
            #                 qemu_proc.wait(timeout=10)
            #             except subprocess.TimeoutExpired:
            #                 print("VM didn't shutdown gracefully, forcing...")
            #                 qemu_proc.kill()
            #                 qemu_proc.wait()
            #         else:
            #             # Non-watch mode already triggered poweroff
            #             qemu_proc.wait()


if __name__ == "__main__":
    main()
