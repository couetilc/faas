"""
pytest configuration for FaaS platform tests.

This module configures vmtest for integration testing and provides
common fixtures for both unit and integration tests.
"""

import pytest
import subprocess
import tempfile
import shutil
from pathlib import Path
import time
import json


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers",
        "vmtest: mark test to run inside a VM with real kernel (requires vmtest)"
    )
    config.addinivalue_line(
        "markers",
        "slow: mark test as slow running"
    )


@pytest.fixture(scope="session")
def project_root():
    """Path to FaaS project root directory."""
    return Path(__file__).parent.parent


@pytest.fixture(scope="session")
def faasd_script(project_root):
    """Path to faasd.py script."""
    path = project_root / "faasd.py"
    assert path.exists(), f"faasd.py not found at {path}"
    return path


@pytest.fixture(scope="session")
def faas_cli(project_root):
    """Path to faas CLI script."""
    path = project_root / "faas"
    assert path.exists(), f"faas CLI not found at {path}"
    return path


@pytest.fixture(scope="session")
def test_handler_dockerfile(project_root):
    """Path to test handler Dockerfile."""
    path = project_root / "Dockerfile.test-handler"
    assert path.exists(), f"Dockerfile.test-handler not found at {path}"
    return path


@pytest.fixture(scope="session")
def test_handler_image():
    """
    Build test handler Docker image and return tarball bytes.

    This fixture builds the test-handler image once per test session
    and returns the image as a tarball (from 'docker save').
    """
    image_name = "test-handler"

    # Build image
    print(f"\n[fixture] Building {image_name} Docker image...")
    result = subprocess.run(
        ["docker", "build", "-f", "Dockerfile.test-handler", "-t", image_name, "."],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        pytest.fail(f"Failed to build test handler image: {result.stderr}")

    # Save image to tarball
    print(f"[fixture] Saving {image_name} to tarball...")
    result = subprocess.run(
        ["docker", "save", image_name],
        capture_output=True
    )

    if result.returncode != 0:
        pytest.fail(f"Failed to save test handler image: {result.stderr}")

    tarball_bytes = result.stdout
    print(f"[fixture] Test handler image ready ({len(tarball_bytes)} bytes)")

    return tarball_bytes


@pytest.fixture
def temp_dir():
    """Create a temporary directory that is cleaned up after the test."""
    tmpdir = tempfile.mkdtemp(prefix="faas-test-")
    yield Path(tmpdir)
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture
def mock_registry_file(temp_dir):
    """Create a temporary registry.json file for testing."""
    registry_path = temp_dir / "registry.json"
    registry_data = {}

    with open(registry_path, 'w') as f:
        json.dump(registry_data, f)

    return registry_path


# =============================================================================
# vmtest-specific fixtures
# =============================================================================

@pytest.fixture
def vm_files(project_root, faasd_script, faas_cli, test_handler_image):
    """
    Prepare files to be copied into the VM.

    Returns a dictionary mapping VM paths to file contents (as bytes).
    This allows tests to easily copy all necessary files into the VM.
    """
    files = {}

    # Read faasd.py
    with open(faasd_script, 'rb') as f:
        files['/root/faasd.py'] = f.read()

    # Read faas CLI
    with open(faas_cli, 'rb') as f:
        files['/root/faas'] = f.read()

    # Read test handler Python script
    test_handler_py = project_root / "test_handler.py"
    if test_handler_py.exists():
        with open(test_handler_py, 'rb') as f:
            files['/root/test_handler.py'] = f.read()

    # Add pre-built test handler image
    files['/root/test-handler.tar'] = test_handler_image

    return files


@pytest.fixture
def setup_vm(vm_files):
    """
    Setup fixture that copies files into VM and prepares environment.

    Usage in tests:
        @pytest.mark.vmtest
        def test_something(setup_vm):
            vm = setup_vm  # VM is ready with all files
            result = vm.run("./faasd.py --help")

    This fixture requires the 'vm' fixture provided by vmtest.
    """
    def _setup(vm):
        """Copy files to VM and setup environment."""
        # Copy all files to VM
        for dest_path, content in vm_files.items():
            vm.write_file(dest_path, content)

        # Make scripts executable
        vm.run("chmod +x /root/faasd.py /root/faas")

        # Create /var/lib/faasd directory
        vm.run("mkdir -p /var/lib/faasd")

        return vm

    return _setup


@pytest.fixture
def faasd_daemon(setup_vm):
    """
    Start faasd daemon in the VM and ensure it's ready.

    Usage in tests:
        @pytest.mark.vmtest
        def test_something(faasd_daemon):
            vm, proc = faasd_daemon
            # faasd is running, make requests
            result = vm.run("curl http://localhost:8080/api/list")

    Yields (vm, process_handle) tuple.
    Automatically cleans up daemon on test completion.
    """
    def _start_daemon(vm):
        """Start faasd and wait for it to be ready."""
        # Setup VM first
        vm = setup_vm(vm)

        # Start faasd in background
        print("[fixture] Starting faasd daemon in VM...")
        proc = vm.spawn("/root/faasd.py")

        # Wait for daemon to be ready (check control API)
        max_retries = 10
        for i in range(max_retries):
            time.sleep(0.5)
            result = vm.run("curl -s http://localhost:8080/api/list", check=False)
            if result.returncode == 0:
                print(f"[fixture] faasd daemon ready after {i * 0.5}s")
                return vm, proc

        # If we get here, daemon didn't start
        pytest.fail("faasd daemon failed to start within 5 seconds")

    return _start_daemon


# =============================================================================
# Helper functions for tests
# =============================================================================

def wait_for_condition(condition_func, timeout=5, interval=0.1, error_msg="Condition not met"):
    """
    Wait for a condition function to return True.

    Args:
        condition_func: Callable that returns bool
        timeout: Maximum time to wait in seconds
        interval: Time between checks in seconds
        error_msg: Error message if timeout occurs

    Raises:
        AssertionError: If condition not met within timeout
    """
    start_time = time.time()
    while time.time() - start_time < timeout:
        if condition_func():
            return True
        time.sleep(interval)

    raise AssertionError(f"{error_msg} (timeout after {timeout}s)")


def parse_ip_from_output(output: str) -> str:
    """
    Parse IP address from faas CLI output.

    Example output: "✓ Deployed test-handler at 10.0.0.10"
    Returns: "10.0.0.10"
    """
    import re
    match = re.search(r'\d+\.\d+\.\d+\.\d+', output)
    if match:
        return match.group(0)
    raise ValueError(f"No IP address found in output: {output}")
