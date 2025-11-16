# FaaS Platform Testing Strategy

Complete testing strategy for the educational FaaS platform using vmtest and pytest.

## Overview

The FaaS platform uses a **layered testing approach**:

1. **Unit Tests** - Fast, isolated tests of individual components (no VM required)
2. **Integration Tests** - Tests of complete workflows in real VMs (using vmtest)
3. **Stress Tests** - Long-running tests for concurrency and resource limits

## Quick Start

```bash
# Install dependencies
pip install -r requirements-dev.txt
sudo apt-get install -y runc qemu-system-x86_64 docker.io

# Build test handler
docker build -f Dockerfile.test-handler -t test-handler .

# Run unit tests (fast, no sudo)
pytest tests/ -m "not vmtest" -v

# Run integration tests (requires sudo)
sudo pytest tests/ -m "vmtest and not slow" -v

# Run everything
sudo pytest tests/ -v
```

## Test Categories

### Unit Tests (No VM Required)

**Location:** `tests/test_image_extraction.py`

**What they test:**
- Docker image layer extraction logic
- CMD/ENTRYPOINT parsing
- Manifest handling
- Registry file I/O

**Run with:**
```bash
pytest tests/ -m "not vmtest" -v
```

**Example:**
```python
def test_extract_simple_image(temp_dir):
    """Test extracting a simple Docker image."""
    image_tar = create_test_image(...)
    rootfs_path = temp_dir / "rootfs"

    with open(image_tar, 'rb') as f:
        faasd.extract_docker_image(f, str(rootfs_path))

    assert rootfs_path.exists()
    assert (rootfs_path / "file.txt").exists()
```

### Integration Tests (vmtest Required)

#### Container Lifecycle Tests

**Location:** `tests/test_container_lifecycle.py`

**What they test:**
- Complete deployment workflow
- Rootfs extraction and reuse
- Bundle creation and cleanup
- Container spawning with runc
- Multiple handler deployments

**Key tests:**
- `test_deploy_and_invoke_handler` - Basic deployment and invocation
- `test_rootfs_reuse_across_requests` - Verify rootfs is extracted once
- `test_multiple_handler_deployments` - Test multiple simultaneous deployments
- `test_container_exit_and_cleanup` - Verify bundle cleanup

**Example:**
```python
@pytest.mark.vmtest
def test_rootfs_reuse_across_requests(vm, vm_files):
    """Verify rootfs extracted once and reused."""
    # Setup and start faasd
    # ...

    helper = FaaSTestHelper(vm)
    handler_ip = helper.deploy_handler("/root/test-handler.tar", "test")

    # Make 5 requests
    for i in range(5):
        response = helper.make_request(handler_ip)
        assert "Hello" in response

    # Verify only ONE rootfs directory
    result = vm.run("ls -1 /var/lib/faasd/images/test/rootfs | wc -l")
    assert int(result.stdout.strip()) == 1
```

#### Network Management Tests

**Location:** `tests/test_network_management.py`

**What they test:**
- IP allocation from 10.0.0.0/24 pool
- IP configuration on loopback interface
- IP labeling (`lo:faas`)
- IP cleanup on shutdown
- Unique IP assignment

**Key tests:**
- `test_ip_allocated_from_pool` - Verify IP is in correct range
- `test_ip_has_label` - Verify lo:faas label is applied
- `test_unique_ips_for_multiple_handlers` - Verify uniqueness
- `test_ip_cleanup_on_graceful_shutdown` - Verify cleanup
- `test_manually_configured_ip_not_removed` - Verify safety

**Example:**
```python
@pytest.mark.vmtest
def test_ip_cleanup_on_graceful_shutdown(vm, vm_files):
    """Test IPs removed on SIGTERM."""
    # Setup, deploy handlers
    # ...

    ip1 = helper.deploy_handler(...)
    ip2 = helper.deploy_handler(...)

    # Verify configured
    assert_ip_configured(vm, ip1, should_exist=True)
    assert_ip_configured(vm, ip2, should_exist=True)

    # Graceful shutdown
    faasd_proc.kill(signal.SIGTERM)
    time.sleep(3)

    # Verify removed
    assert_ip_configured(vm, ip1, should_exist=False)
    assert_ip_configured(vm, ip2, should_exist=False)
```

#### Socket FD Passing Tests

**Location:** `tests/test_socket_passing.py`

**What they test:**
- SCM_RIGHTS file descriptor passing
- Bidirectional communication through FD
- FD passing across multiple requests
- Concurrent FD passing (thread safety)
- Socket and execution timeouts

**Key tests:**
- `test_basic_fd_passing` - Verify FD passing works
- `test_bidirectional_communication` - Verify read/write through FD
- `test_multiple_requests_same_handler` - Verify repeated FD passing
- `test_concurrent_fd_passing` - Verify thread safety

**Example:**
```python
@pytest.mark.vmtest
def test_basic_fd_passing(vm, vm_files):
    """Test FD passing from faasd to container."""
    # Setup and deploy
    # ...

    helper = FaaSTestHelper(vm)
    handler_ip = helper.deploy_handler(...)

    # If this succeeds, FD passing worked
    response = helper.make_request(handler_ip)
    assert "Hello from FaaS handler" in response
```

#### Concurrency Tests

**Location:** `tests/test_concurrency.py`

**What they test:**
- Concurrent requests to same handler
- Concurrent requests to different handlers
- Rapid sequential deployments
- Thread safety of registry updates
- Resource limits
- No deadlocks or race conditions

**Key tests:**
- `test_concurrent_requests_to_single_handler` - 10+ concurrent requests
- `test_concurrent_requests_to_different_handlers` - Multi-handler concurrency
- `test_stress_many_sequential_requests` - 100+ sequential requests
- `test_registry_updates_thread_safe` - Verify registry integrity

**Example:**
```python
@pytest.mark.vmtest
@pytest.mark.slow
def test_concurrent_requests_to_single_handler(vm, vm_files):
    """Test 10 concurrent requests."""
    # Setup and deploy
    # ...

    # Launch 10 concurrent requests
    num_concurrent = 10
    for i in range(num_concurrent):
        vm.spawn(f"curl -s http://{handler_ip}/ > /tmp/resp-{i}.txt")

    time.sleep(10)  # Wait for completion

    # Count successes
    success_count = sum(
        1 for i in range(num_concurrent)
        if "Hello" in vm.run(f"cat /tmp/resp-{i}.txt").stdout
    )

    assert success_count >= num_concurrent * 0.7  # 70% success rate
```

## Test Infrastructure

### Fixtures (conftest.py)

The `tests/conftest.py` file provides common fixtures:

#### Session-scoped fixtures
- `project_root` - Path to project root
- `faasd_script` - Path to faasd.py
- `faas_cli` - Path to faas CLI
- `test_handler_image` - Pre-built Docker image tarball

#### Test-scoped fixtures
- `temp_dir` - Temporary directory (auto-cleanup)
- `vm_files` - Dict of files to copy to VM
- `setup_vm` - Copy files and prepare VM environment
- `faasd_daemon` - Running faasd instance (auto-cleanup)

### Helper Functions (helpers/faas_test_utils.py)

The `FaaSTestHelper` class provides:

```python
helper = FaaSTestHelper(vm)

# Deploy handler
handler_ip = helper.deploy_handler("/root/image.tar", "my-handler")

# Get handler IP
ip = helper.get_handler_ip("my-handler")

# List all handlers
handlers = helper.list_handlers()

# Make HTTP request
response = helper.make_request(handler_ip, path="/test")

# Check network state
is_configured = helper.check_ip_configured("10.0.0.10")
has_label = helper.check_ip_has_label("10.0.0.10", "lo:faas")

# Check filesystem state
exists = helper.check_rootfs_exists("my-handler")
bundle_count = helper.count_bundles()

# Read registry
registry = helper.read_registry()

# Wait for cleanup
helper.wait_for_cleanup(timeout=5)
```

### Assertion Functions

Convenient assertion functions in `helpers/faas_test_utils.py`:

```python
# Assert handler responds
assert_handler_responds(vm, handler_ip, "expected content")

# Assert IP state
assert_ip_configured(vm, "10.0.0.10", should_exist=True)

# Assert filesystem state
assert_rootfs_exists(vm, "handler-name")
assert_bundles_cleaned_up(vm, timeout=5)
```

## Running Tests

### Local Development

```bash
# Run unit tests while developing
pytest tests/test_image_extraction.py -v

# Run specific integration test
sudo pytest tests/test_container_lifecycle.py::TestContainerLifecycle::test_deploy_and_invoke_handler -v

# Run all fast tests
sudo pytest tests/ -m "vmtest and not slow" -v

# Run with verbose output
sudo pytest tests/ -v -s

# Stop on first failure
sudo pytest tests/ -v -x
```

### Continuous Integration

GitHub Actions automatically runs tests on:
- Push to main/develop branches
- Pull requests
- Manual workflow dispatch

**Workflow stages:**
1. **Unit Tests** - Fast, no VM (runs in parallel)
2. **Integration Tests** - vmtest (requires sudo)
3. **Stress Tests** - Only on main branch (slow)
4. **Code Quality** - Syntax checks, file presence

See `.github/workflows/test.yml` for details.

### Coverage

```bash
# Run with coverage
sudo pytest tests/ --cov=faasd --cov-report=html

# View coverage report
open htmlcov/index.html
```

## Test Markers

Tests are marked for categorization:

```python
@pytest.mark.vmtest     # Requires VM (use sudo)
@pytest.mark.slow       # Takes >30 seconds
@pytest.mark.unit       # Unit test (fast)
@pytest.mark.integration # Integration test
@pytest.mark.stress     # Stress/load test
```

**Run tests by marker:**
```bash
# Only vmtest
sudo pytest -m vmtest

# vmtest but not slow
sudo pytest -m "vmtest and not slow"

# Everything except stress
pytest -m "not stress"
```

## Debugging Tests

### Enable verbose output

```bash
# Show all print statements
sudo pytest tests/ -v -s

# Show local variables on failure
sudo pytest tests/ -v -l

# Enter debugger on failure
sudo pytest tests/ -v --pdb
```

### Add debug prints in tests

```python
@pytest.mark.vmtest
def test_debug_example(vm):
    handler_ip = deploy_handler(...)
    print(f"✓ Deployed at {handler_ip}")  # Shows in pytest output

    response = make_request(...)
    print(f"Response: {response[:100]}...")  # Shows on failure
```

### Check VM state manually

```python
@pytest.mark.vmtest
def test_manual_inspection(vm):
    # Deploy and start everything
    # ...

    # Check what's running
    result = vm.run("ps aux")
    print(f"Processes:\n{result.stdout}")

    # Check network config
    result = vm.run("ip addr show")
    print(f"Network:\n{result.stdout}")

    # Check filesystem
    result = vm.run("ls -la /var/lib/faasd/")
    print(f"FaaS data:\n{result.stdout}")
```

## Best Practices

### 1. Always cleanup resources

```python
@pytest.mark.vmtest
def test_with_cleanup(vm):
    proc = vm.spawn("/root/faasd.py")

    try:
        # Test code
        pass
    finally:
        proc.kill()  # Always cleanup
```

### 2. Use generous timeouts

```python
# Give daemons time to start
faasd_proc = vm.spawn("/root/faasd.py")
time.sleep(2)  # Wait for startup

# Wait for listener to be ready
time.sleep(1)
```

### 3. Check intermediate state

```python
# Don't just check final result
handler_ip = deploy_handler(...)
assert handler_ip.startswith("10.0.0.")  # Verify IP is valid

assert_ip_configured(vm, handler_ip)  # Verify IP configured

response = make_request(handler_ip)  # Then test request
```

### 4. Print progress for long tests

```python
for i in range(100):
    make_request(...)
    if (i + 1) % 20 == 0:
        print(f"Progress: {i+1}/100")
```

### 5. Allow some failures in concurrent tests

```python
# Concurrent tests may have occasional failures
assert success_count >= total_count * 0.8  # 80% is acceptable
```

## Adding New Tests

### 1. Determine test type

- **Unit test**: No VM needed, test pure Python logic
- **Integration test**: Need VM for runc, networking, etc.

### 2. Create test file

```python
# tests/test_my_feature.py
import pytest
from helpers.faas_test_utils import FaaSTestHelper

@pytest.mark.vmtest
def test_my_feature(vm, vm_files):
    """
    Test description.

    Steps:
    1. Setup
    2. Action
    3. Assert
    """
    # Setup VM
    for dest_path, content in vm_files.items():
        vm.write_file(dest_path, content)

    vm.run("chmod +x /root/faasd.py /root/faas")
    vm.run("mkdir -p /var/lib/faasd")

    # Start faasd
    faasd_proc = vm.spawn("/root/faasd.py")
    time.sleep(2)

    # Test your feature
    helper = FaaSTestHelper(vm)
    # ...

    # Cleanup
    faasd_proc.kill()
```

### 3. Run locally

```bash
sudo pytest tests/test_my_feature.py -v
```

### 4. Add to CI

Tests in `tests/` directory are automatically discovered.

## Troubleshooting

### Tests fail with "Permission denied"

**Solution:** Run with sudo:
```bash
sudo pytest tests/ -m vmtest -v
```

### Tests timeout

**Cause:** Daemon not starting or slow VM boot.

**Solution:**
- Increase sleep times
- Check daemon logs
- Verify QEMU/KVM installation

### Tests pass locally but fail in CI

**Cause:** Timing differences, resource constraints.

**Solution:**
- Add more generous timeouts
- Check GitHub Actions logs
- Test with `--tb=short` for better error messages

## References

- **vmtest Guide**: `docs/VMTEST_GUIDE.md` - Detailed vmtest documentation
- **Test Examples**: `tests/test_*.py` - Working examples
- **pytest Docs**: https://docs.pytest.org
- **vmtest Docs**: https://github.com/danobi/vmtest

---

**Summary:**
- ✅ Unit tests for fast feedback
- ✅ vmtest for realistic integration testing
- ✅ Helper functions for common operations
- ✅ Stress tests for reliability
- ✅ CI/CD with GitHub Actions
- ✅ Comprehensive documentation

Start with unit tests, add integration tests for critical paths, and use stress tests to verify reliability under load.
