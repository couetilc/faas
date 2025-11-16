# FaaS Platform Tests

Comprehensive test suite for the educational FaaS platform using pytest and vmtest.

## Quick Start

```bash
# Install dependencies
pip install -r requirements-dev.txt

# Run unit tests (fast, no VM)
pytest tests/ -m "not vmtest" -v

# Run integration tests (requires sudo)
sudo pytest tests/ -m "vmtest and not slow" -v
```

## Test Files

| File | Type | Description |
|------|------|-------------|
| `test_image_extraction.py` | Unit | Docker image extraction and parsing |
| `test_container_lifecycle.py` | Integration (vmtest) | Container creation, execution, cleanup |
| `test_network_management.py` | Integration (vmtest) | IP allocation and network configuration |
| `test_socket_passing.py` | Integration (vmtest) | SCM_RIGHTS FD passing |
| `test_concurrency.py` | Stress (vmtest) | Concurrent requests and resource limits |

## Test Infrastructure

### Fixtures (conftest.py)

Common fixtures for all tests:

- `project_root` - Path to FaaS project root
- `test_handler_image` - Pre-built Docker image (session-scoped)
- `temp_dir` - Temporary directory with auto-cleanup
- `vm_files` - Files to copy into VM
- `setup_vm` - Setup VM environment
- `faasd_daemon` - Running faasd instance

### Helpers (helpers/faas_test_utils.py)

Helper classes and functions:

- `FaaSTestHelper` - High-level operations (deploy, request, assertions)
- `assert_handler_responds()` - Assert HTTP response
- `assert_ip_configured()` - Assert IP network state
- `assert_rootfs_exists()` - Assert filesystem state
- `assert_bundles_cleaned_up()` - Assert cleanup

## Running Tests

### By Type

```bash
# Unit tests only
pytest tests/ -m "not vmtest" -v

# Integration tests only
sudo pytest tests/ -m "vmtest and not slow" -v

# Stress tests only
sudo pytest tests/ -m "slow" -v

# Everything
sudo pytest tests/ -v
```

### Specific Tests

```bash
# Single test file
sudo pytest tests/test_container_lifecycle.py -v

# Single test class
sudo pytest tests/test_container_lifecycle.py::TestContainerLifecycle -v

# Single test function
sudo pytest tests/test_container_lifecycle.py::TestContainerLifecycle::test_deploy_and_invoke_handler -v
```

### With Options

```bash
# Stop on first failure
sudo pytest tests/ -v -x

# Show all output (including print statements)
sudo pytest tests/ -v -s

# Show local variables on failure
sudo pytest tests/ -v -l

# Run in parallel (careful with resource limits)
sudo pytest tests/ -n 4

# With coverage
sudo pytest tests/ --cov=faasd --cov-report=html
```

## Test Markers

Tests use markers for categorization:

```python
@pytest.mark.vmtest      # Requires VM (use sudo to run)
@pytest.mark.slow        # Takes >30 seconds
@pytest.mark.unit        # Unit test
@pytest.mark.integration # Integration test
@pytest.mark.stress      # Stress/load test
```

Run by marker:
```bash
sudo pytest -m "vmtest and not slow"  # Fast integration tests
sudo pytest -m "not stress"            # All except stress tests
```

## Writing Tests

### Unit Test Example

```python
def test_extract_simple_image(temp_dir):
    """Test Docker image extraction (no VM needed)."""
    image_tar = create_test_image(...)
    rootfs_path = temp_dir / "rootfs"

    with open(image_tar, 'rb') as f:
        faasd.extract_docker_image(f, str(rootfs_path))

    assert rootfs_path.exists()
```

### Integration Test Example

```python
import pytest
from helpers.faas_test_utils import FaaSTestHelper

@pytest.mark.vmtest
def test_my_feature(vm, vm_files):
    """Test description."""
    # Setup VM
    for dest_path, content in vm_files.items():
        vm.write_file(dest_path, content)

    vm.run("chmod +x /root/faasd.py /root/faas")
    vm.run("mkdir -p /var/lib/faasd")

    # Start faasd
    faasd_proc = vm.spawn("/root/faasd.py")
    time.sleep(2)

    # Test
    helper = FaaSTestHelper(vm)
    handler_ip = helper.deploy_handler("/root/test-handler.tar", "test")

    response = helper.make_request(handler_ip)
    assert "expected content" in response

    # Cleanup
    faasd_proc.kill()
```

## Debugging

### View output

```bash
# Show print statements
sudo pytest tests/ -v -s

# Enter debugger on failure
sudo pytest tests/ -v --pdb
```

### Inspect VM state

```python
@pytest.mark.vmtest
def test_debug(vm):
    # ... setup ...

    # Check processes
    result = vm.run("ps aux")
    print(f"Processes:\n{result.stdout}")

    # Check network
    result = vm.run("ip addr show")
    print(f"Network:\n{result.stdout}")

    # Check files
    result = vm.run("ls -la /var/lib/faasd/")
    print(f"Files:\n{result.stdout}")
```

## Documentation

- **`docs/VMTEST_GUIDE.md`** - Detailed vmtest documentation
- **`docs/TESTING_STRATEGY.md`** - Complete testing strategy
- **`pytest.ini`** - pytest configuration
- **`.github/workflows/test.yml`** - CI/CD configuration

## CI/CD

Tests automatically run on GitHub Actions:
- **Unit tests** - Every push/PR
- **Integration tests** - Every push/PR
- **Stress tests** - Main branch only

See `.github/workflows/test.yml` for details.

## Requirements

### System Dependencies

```bash
# Ubuntu/Debian
sudo apt-get install -y runc qemu-system-x86 qemu-utils docker.io
```

### Python Dependencies

```bash
# Install standard dependencies
pip install -r requirements-dev.txt

# Install vmtest from GitHub (not on PyPI)
pip install git+https://github.com/danobi/vmtest.git
```

Includes:
- `pytest` - Test framework
- `vmtest` - Run tests in VMs (install from GitHub)
- `pytest-xdist` - Parallel execution
- `pytest-timeout` - Test timeouts
- `pytest-cov` - Coverage reporting

## Troubleshooting

### Permission denied

Run vmtest tests with sudo:
```bash
sudo pytest tests/ -m vmtest -v
```

### Tests timeout

Increase timeouts in test code or check VM boot:
```python
time.sleep(3)  # Increase from 2 to 3 seconds
```

### QEMU not found

Install QEMU:
```bash
sudo apt-get install qemu-system-x86_64
```

---

For more information, see:
- `docs/VMTEST_GUIDE.md` - Comprehensive vmtest guide
- `docs/TESTING_STRATEGY.md` - Testing strategy and patterns
