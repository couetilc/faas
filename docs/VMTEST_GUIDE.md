# vmtest Testing Guide for FaaS Platform

This guide explains how to use vmtest for testing the FaaS platform, including detailed explanations of the `@pytest.mark.vmtest` decorator, VM state assertions, and best practices.

## Table of Contents

1. [What is vmtest?](#what-is-vmtest)
2. [Why vmtest for FaaS Testing?](#why-vmtest-for-faas-testing)
3. [Installation and Setup](#installation-and-setup)
4. [The @pytest.mark.vmtest Decorator](#the-pytestmarkvmtest-decorator)
5. [Asserting VM State](#asserting-vm-state)
6. [Writing vmtest Tests](#writing-vmtest-tests)
7. [Running Tests](#running-tests)
8. [CI/CD Integration](#cicd-integration)
9. [Troubleshooting](#troubleshooting)

---

## What is vmtest?

**vmtest** is a pytest plugin that runs tests inside a lightweight virtual machine with a real Linux kernel. It's designed specifically for testing code that requires kernel features like:

- Namespaces (pid, network, mount, user, etc.)
- Cgroups
- Low-level system calls (like `SCM_RIGHTS` for FD passing)
- Network configuration (`ip` command)
- Root privileges

**Key characteristics:**
- ✅ **Real kernel**: Not a container or mock - actual kernel features
- ✅ **Fast**: Boots in 2-5 seconds (vs 30-90s for traditional VMs)
- ✅ **Isolated**: Each test runs in a fresh VM
- ✅ **pytest integration**: Works seamlessly with pytest fixtures and assertions
- ✅ **CI-friendly**: Runs in GitHub Actions without special configuration

## Why vmtest for FaaS Testing?

Our FaaS platform has unique requirements that make vmtest ideal:

| Requirement | Why vmtest is needed |
|-------------|----------------------|
| **Root privileges** | `runc` and `ip` commands require root |
| **Real namespaces** | Container isolation uses actual kernel namespaces |
| **SCM_RIGHTS** | Socket FD passing is a low-level Unix feature |
| **Network config** | IP allocation on loopback requires real networking |
| **runc execution** | Need actual runc, not mocks |

**Alternatives considered:**
- ❌ **Mocking**: Too much to mock (kernel, runc, networking)
- ❌ **Docker-in-Docker**: Nested containers are confusing, require privileged mode
- ❌ **Full VMs (Vagrant/QEMU)**: Too slow (30+ seconds boot time)
- ✅ **vmtest**: Perfect balance of isolation, speed, and real kernel features

---

## Installation and Setup

### 1. Install dependencies

```bash
# Install Python dependencies
pip install -r requirements-dev.txt

# Install system dependencies (Ubuntu/Debian)
sudo apt-get install -y runc qemu-system-x86_64 qemu-utils docker.io

# Verify installations
runc --version
qemu-system-x86_64 --version
pytest --version
```

### 2. Build test handler image

```bash
# Build the test handler Docker image
docker build -f Dockerfile.test-handler -t test-handler .
```

### 3. Verify setup

```bash
# Run unit tests (no VM required)
pytest tests/ -m "not vmtest" -v

# Run a single vmtest (requires sudo)
sudo pytest tests/test_container_lifecycle.py::TestContainerLifecycle::test_deploy_and_invoke_handler -v
```

---

## The @pytest.mark.vmtest Decorator

### Basic Usage

The `@pytest.mark.vmtest` decorator tells pytest to run the test inside a VM:

```python
import pytest

@pytest.mark.vmtest
def test_basic_example(vm):
    """This test runs inside a VM with a real kernel."""
    result = vm.run("uname -r")
    print(f"Kernel version: {result.stdout}")
    assert result.returncode == 0
```

**What happens when you use this decorator:**

1. **VM Creation**: vmtest boots a lightweight VM with a real Linux kernel
2. **Test Execution**: Your test function runs, with access to the `vm` fixture
3. **Isolation**: Each test gets a fresh VM (no state pollution)
4. **Cleanup**: VM is destroyed after the test completes

### The `vm` Fixture

When you use `@pytest.mark.vmtest`, you get access to the `vm` fixture, which provides:

#### `vm.run(command, check=True)`
Execute a command in the VM and wait for completion.

```python
@pytest.mark.vmtest
def test_run_command(vm):
    # Run a command
    result = vm.run("echo 'hello world'")

    # result object contains:
    assert result.returncode == 0
    assert "hello world" in result.stdout
    assert result.stderr == ""
```

**Parameters:**
- `command` (str): Shell command to execute
- `check` (bool): If True, raises exception on non-zero exit code (default: True)

**Returns:** Object with:
- `returncode` (int): Exit code
- `stdout` (str): Standard output
- `stderr` (str): Standard error

#### `vm.spawn(command)`
Start a command in the background (non-blocking).

```python
@pytest.mark.vmtest
def test_background_process(vm):
    # Start faasd in background
    proc = vm.spawn("/root/faasd.py")

    # Do other things while faasd runs
    time.sleep(2)

    # Check if process is still running
    result = vm.run("ps aux | grep faasd", check=False)
    assert "faasd.py" in result.stdout

    # Kill the process
    proc.kill()
```

**Returns:** Process handle with:
- `kill(signal=SIGTERM)`: Terminate the process
- `wait()`: Wait for process to exit

#### `vm.write_file(path, content)`
Write a file to the VM filesystem.

```python
@pytest.mark.vmtest
def test_write_file(vm):
    # Write string content
    vm.write_file("/tmp/test.txt", b"hello world")

    # Verify
    result = vm.run("cat /tmp/test.txt")
    assert result.stdout == "hello world"
```

**Parameters:**
- `path` (str): Absolute path in VM
- `content` (bytes): File content (must be bytes, not str)

#### `vm.read_file(path)`
Read a file from the VM filesystem.

```python
@pytest.mark.vmtest
def test_read_file(vm):
    # Create file in VM
    vm.run("echo 'data' > /tmp/output.txt")

    # Read it
    content = vm.read_file("/tmp/output.txt")
    assert b"data" in content
```

**Returns:** bytes (file content)

### Combining with Other Markers

```python
import pytest

@pytest.mark.vmtest
@pytest.mark.slow
def test_stress(vm):
    """This is a slow test that runs in a VM."""
    pass

# Run only vmtest tests
# pytest -m vmtest

# Run vmtest tests except slow ones
# pytest -m "vmtest and not slow"
```

---

## Asserting VM State

### Network State Assertions

#### Check if IP is configured

```python
from helpers.faas_test_utils import assert_ip_configured

@pytest.mark.vmtest
def test_ip_configuration(vm):
    # Deploy handler (configures IP)
    handler_ip = "10.0.0.10"

    # Assert IP exists
    assert_ip_configured(vm, handler_ip, should_exist=True)

    # Or check manually
    result = vm.run(f"ip addr show lo | grep {handler_ip}", check=False)
    assert result.returncode == 0, f"IP {handler_ip} should be configured"
```

#### Check IP has label

```python
from helpers.faas_test_utils import FaaSTestHelper

@pytest.mark.vmtest
def test_ip_label(vm):
    helper = FaaSTestHelper(vm)
    handler_ip = "10.0.0.10"

    # Check if IP has the 'lo:faas' label
    has_label = helper.check_ip_has_label(handler_ip, "lo:faas")
    assert has_label, f"IP should have lo:faas label"
```

#### Verify all IPs removed on cleanup

```python
@pytest.mark.vmtest
def test_cleanup_removes_ips(vm):
    # Deploy handlers
    # ...

    # Shutdown faasd
    faasd_proc.kill()
    time.sleep(2)

    # Verify IPs removed
    result = vm.run("ip addr show lo | grep '10.0.0.'", check=False)
    assert result.returncode != 0, "All FaaS IPs should be removed"
```

### Filesystem State Assertions

#### Check if rootfs exists

```python
from helpers.faas_test_utils import assert_rootfs_exists

@pytest.mark.vmtest
def test_rootfs_created(vm):
    # Deploy handler
    # ...

    # Verify rootfs directory exists
    assert_rootfs_exists(vm, "test-handler")

    # Or check manually
    result = vm.run("test -d /var/lib/faasd/images/test-handler/rootfs")
    assert result.returncode == 0
```

#### Verify bundles cleaned up

```python
from helpers.faas_test_utils import assert_bundles_cleaned_up

@pytest.mark.vmtest
def test_cleanup_bundles(vm):
    # Make request
    # ...

    # Wait for cleanup
    assert_bundles_cleaned_up(vm, timeout=5)

    # Or check manually
    result = vm.run("ls /var/lib/faasd/bundles/ | wc -l")
    bundle_count = int(result.stdout.strip())
    assert bundle_count == 0, "All bundles should be cleaned up"
```

#### Count files in directory

```python
@pytest.mark.vmtest
def test_file_count(vm):
    # Count rootfs directories
    result = vm.run("ls -1 /var/lib/faasd/images/ | wc -l")
    image_count = int(result.stdout.strip())
    assert image_count == 1, "Should have exactly one image"
```

### Process State Assertions

#### Verify process is running

```python
@pytest.mark.vmtest
def test_daemon_running(vm):
    # Start daemon
    proc = vm.spawn("/root/faasd.py")
    time.sleep(1)

    # Verify it's running
    result = vm.run("ps aux | grep faasd | grep -v grep", check=False)
    assert result.returncode == 0, "faasd should be running"
    assert "faasd.py" in result.stdout

    proc.kill()
```

#### Verify process exited

```python
@pytest.mark.vmtest
def test_process_exits(vm):
    # Start and stop process
    proc = vm.spawn("/root/faasd.py")
    time.sleep(1)
    proc.kill()
    time.sleep(1)

    # Verify it's gone
    result = vm.run("ps aux | grep faasd | grep -v grep", check=False)
    assert result.returncode != 0, "faasd should not be running"
```

### Registry State Assertions

#### Verify registry contents

```python
from helpers.faas_test_utils import FaaSTestHelper

@pytest.mark.vmtest
def test_registry_state(vm):
    helper = FaaSTestHelper(vm)

    # Read registry
    registry = helper.read_registry()

    # Assert structure
    assert "test-handler" in registry
    assert registry["test-handler"]["ip"].startswith("10.0.0.")
    assert "command" in registry["test-handler"]
```

### HTTP Response Assertions

#### Verify handler responds correctly

```python
from helpers.faas_test_utils import assert_handler_responds

@pytest.mark.vmtest
def test_handler_response(vm):
    handler_ip = "10.0.0.10"

    # Assert handler responds with expected content
    assert_handler_responds(vm, handler_ip, "Hello from FaaS handler")

    # Or make request manually
    helper = FaaSTestHelper(vm)
    response = helper.make_request(handler_ip, path="/test")
    assert "expected content" in response
    assert response.status_code == 200  # if helper supports it
```

---

## Writing vmtest Tests

### Test Structure Template

```python
import pytest
import time
from helpers.faas_test_utils import FaaSTestHelper

@pytest.mark.vmtest
def test_my_feature(vm, vm_files):
    """
    Test description: what this test verifies.

    Steps:
    1. Setup VM and start faasd
    2. Deploy handler
    3. Perform action
    4. Assert expected state
    """
    # 1. Setup VM
    for dest_path, content in vm_files.items():
        vm.write_file(dest_path, content)

    vm.run("chmod +x /root/faasd.py /root/faas")
    vm.run("mkdir -p /var/lib/faasd")

    # 2. Start faasd
    faasd_proc = vm.spawn("/root/faasd.py")
    time.sleep(2)  # Wait for startup

    # 3. Perform test actions
    helper = FaaSTestHelper(vm)
    handler_ip = helper.deploy_handler("/root/test-handler.tar", "my-handler")

    # 4. Make assertions
    assert handler_ip.startswith("10.0.0.")

    response = helper.make_request(handler_ip)
    assert "expected" in response

    # 5. Cleanup
    faasd_proc.kill()
```

### Best Practices

#### 1. Use fixtures for common setup

```python
# In conftest.py
@pytest.fixture
def running_faasd(vm, vm_files):
    """Fixture that provides a running faasd instance."""
    for dest_path, content in vm_files.items():
        vm.write_file(dest_path, content)

    vm.run("chmod +x /root/faasd.py /root/faas")
    vm.run("mkdir -p /var/lib/faasd")

    proc = vm.spawn("/root/faasd.py")
    time.sleep(2)

    yield vm, proc

    proc.kill()

# In test file
@pytest.mark.vmtest
def test_with_fixture(running_faasd):
    vm, proc = running_faasd
    # faasd is already running
    helper = FaaSTestHelper(vm)
    # ... test code
```

#### 2. Always cleanup background processes

```python
@pytest.mark.vmtest
def test_with_cleanup(vm):
    proc = vm.spawn("/root/faasd.py")

    try:
        # Test code here
        pass
    finally:
        # Always cleanup, even if test fails
        proc.kill()
```

#### 3. Add generous timeouts for slow operations

```python
@pytest.mark.vmtest
def test_slow_operation(vm):
    # Start daemon
    proc = vm.spawn("/root/faasd.py")
    time.sleep(3)  # Give daemon time to start

    # Wait for condition with timeout
    max_wait = 10
    start = time.time()
    while time.time() - start < max_wait:
        result = vm.run("curl -s http://localhost:8080/api/list", check=False)
        if result.returncode == 0:
            break
        time.sleep(0.5)

    assert result.returncode == 0, "Daemon should be ready within 10s"
```

#### 4. Print debug information

```python
@pytest.mark.vmtest
def test_with_debug(vm):
    # Useful for debugging failures
    handler_ip = deploy_handler(...)
    print(f"✓ Handler deployed at {handler_ip}")

    response = make_request(...)
    print(f"Response length: {len(response)} bytes")

    # This output appears in pytest logs when test fails
```

### Common Patterns

#### Pattern: Deploy and test single handler

```python
@pytest.mark.vmtest
def test_single_handler(vm, vm_files):
    # Setup
    for dest_path, content in vm_files.items():
        vm.write_file(dest_path, content)
    vm.run("chmod +x /root/faasd.py /root/faas")
    vm.run("mkdir -p /var/lib/faasd")

    # Start faasd
    faasd_proc = vm.spawn("/root/faasd.py")
    time.sleep(2)

    # Deploy and test
    helper = FaaSTestHelper(vm)
    handler_ip = helper.deploy_handler("/root/test-handler.tar", "test")
    time.sleep(1)

    response = helper.make_request(handler_ip)
    assert "expected" in response

    # Cleanup
    faasd_proc.kill()
```

#### Pattern: Test multiple handlers

```python
@pytest.mark.vmtest
def test_multiple_handlers(vm, vm_files):
    # Setup (same as above)
    # ...

    helper = FaaSTestHelper(vm)

    # Deploy multiple handlers
    ips = []
    for i in range(3):
        ip = helper.deploy_handler("/root/test-handler.tar", f"handler-{i}")
        ips.append(ip)

    # Verify all unique
    assert len(ips) == len(set(ips))

    # Test each handler
    for ip in ips:
        response = helper.make_request(ip)
        assert "expected" in response
```

#### Pattern: Test concurrent requests

```python
@pytest.mark.vmtest
def test_concurrent(vm, vm_files):
    # Setup and deploy handler
    # ...

    # Launch concurrent requests
    num_concurrent = 10
    for i in range(num_concurrent):
        vm.spawn(f"curl -s http://{handler_ip}/ > /tmp/response-{i}.txt")

    # Wait for completion
    time.sleep(5)

    # Check results
    success_count = 0
    for i in range(num_concurrent):
        result = vm.run(f"cat /tmp/response-{i}.txt", check=False)
        if "expected" in result.stdout:
            success_count += 1

    assert success_count >= num_concurrent * 0.8  # 80% success rate
```

---

## Running Tests

### Run all tests

```bash
# Run unit tests only (fast, no VM)
pytest tests/ -m "not vmtest" -v

# Run vmtest integration tests (requires sudo)
sudo pytest tests/ -m "vmtest and not slow" -v

# Run all tests including slow ones
sudo pytest tests/ -v
```

### Run specific test files

```bash
# Run container lifecycle tests
sudo pytest tests/test_container_lifecycle.py -v

# Run single test
sudo pytest tests/test_container_lifecycle.py::TestContainerLifecycle::test_deploy_and_invoke_handler -v
```

### Run with markers

```bash
# Run only slow tests
sudo pytest tests/ -m "slow" -v

# Run vmtest but not slow
sudo pytest tests/ -m "vmtest and not slow" -v

# Run everything except stress tests
sudo pytest tests/ -m "not stress" -v
```

### Debugging failed tests

```bash
# Show full output (including prints)
sudo pytest tests/ -v -s

# Stop on first failure
sudo pytest tests/ -v -x

# Show local variables on failure
sudo pytest tests/ -v -l

# Enter debugger on failure
sudo pytest tests/ -v --pdb
```

---

## CI/CD Integration

### GitHub Actions

The `.github/workflows/test.yml` file configures automated testing:

```yaml
# Excerpt from workflow
- name: Run integration tests (vmtest)
  run: |
    sudo -E env PATH=$PATH pytest tests/ -v -m "vmtest and not slow" --tb=short -x
  timeout-minutes: 20
```

**Key points:**
- Tests run on `ubuntu-latest`
- `sudo -E` preserves environment variables
- Timeout prevents hung tests
- Unit tests run separately (no sudo needed)
- Stress tests only run on main branch

### Local CI Simulation

```bash
# Simulate GitHub Actions locally
docker run -it --privileged ubuntu:22.04 bash

# Inside container:
apt-get update && apt-get install -y python3 python3-pip runc qemu-system-x86_64
pip3 install pytest vmtest
# ... run tests
```

---

## Troubleshooting

### "Permission denied" errors

**Problem:** Tests fail with permission errors.

**Solution:** Run with sudo:
```bash
sudo pytest tests/ -m vmtest -v
```

### "qemu-system-x86_64 not found"

**Problem:** QEMU not installed.

**Solution:**
```bash
sudo apt-get install qemu-system-x86_64 qemu-utils
```

### Tests hang or timeout

**Problem:** Test hangs waiting for daemon to start.

**Solution:** Increase timeout or check daemon logs:
```python
@pytest.mark.vmtest
def test_debug_startup(vm):
    proc = vm.spawn("/root/faasd.py > /tmp/faasd.log 2>&1")
    time.sleep(5)

    # Check logs
    result = vm.run("cat /tmp/faasd.log")
    print(f"Daemon logs:\n{result.stdout}")
```

### VM fails to boot

**Problem:** vmtest can't boot VM.

**Solution:** Check KVM support:
```bash
# Check if KVM is available
ls -l /dev/kvm

# If not, vmtest will use slower emulation (expect longer boot times)
```

### "No space left on device"

**Problem:** VM runs out of disk space.

**Solution:** Clean up between tests or increase VM size (check vmtest docs).

---

## Advanced Topics

### Custom VM Configuration

```python
# In conftest.py - configure VM size
def pytest_configure(config):
    # Configure vmtest (check vmtest documentation for options)
    pass
```

### Parallel Test Execution

```bash
# Run tests in parallel (be careful with resource-intensive tests)
sudo pytest tests/ -m "vmtest and not slow" -n 4
```

### Collecting Coverage

```bash
# Run with coverage
sudo pytest tests/ --cov=faasd --cov-report=html
```

---

## Summary

**vmtest provides:**
- ✅ Real kernel for authentic testing
- ✅ Fast boot times (2-5s)
- ✅ pytest integration
- ✅ Isolated test environments
- ✅ Root privileges when needed

**Key concepts:**
- Use `@pytest.mark.vmtest` decorator
- Access VM via `vm` fixture
- Assert state with helper functions
- Always cleanup background processes
- Run with `sudo` for integration tests

**Next steps:**
1. Read existing tests for examples
2. Write tests for your features
3. Run locally to verify
4. Push and let CI run full suite

For more information:
- vmtest docs: https://github.com/danobi/vmtest
- pytest docs: https://docs.pytest.org
- FaaS test examples: `tests/test_*.py`
