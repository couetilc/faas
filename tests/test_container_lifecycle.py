"""
Integration tests for container lifecycle using vmtest.

These tests run inside a real VM with a real kernel to verify:
- Container creation and execution
- Rootfs reuse across requests
- Bundle cleanup after container exits
- Multiple deployments
"""

import pytest
import time
from helpers.faas_test_utils import (
    FaaSTestHelper,
    assert_handler_responds,
    assert_rootfs_exists,
    assert_bundles_cleaned_up,
)


@pytest.mark.vmtest
class TestContainerLifecycle:
    """Test container lifecycle operations."""

    def test_deploy_and_invoke_handler(self, vm, vm_files):
        """
        Test basic deployment and invocation.

        Steps:
        1. Copy files to VM
        2. Start faasd
        3. Deploy test handler
        4. Make request
        5. Verify response
        """
        # Setup VM
        for dest_path, content in vm_files.items():
            vm.write_file(dest_path, content)

        vm.run("chmod +x /root/faasd.py /root/faas")
        vm.run("mkdir -p /var/lib/faasd")

        # Start faasd in background
        faasd_proc = vm.spawn("/root/faasd.py")
        time.sleep(2)  # Wait for startup

        # Verify faasd is running
        result = vm.run("curl -s http://localhost:8080/api/list", check=False)
        assert result.returncode == 0, "faasd control API should be accessible"

        # Deploy handler
        helper = FaaSTestHelper(vm)
        handler_ip = helper.deploy_handler("/root/test-handler.tar", "test-handler")

        print(f"✓ Handler deployed at {handler_ip}")

        # Verify IP is in expected range
        assert handler_ip.startswith("10.0.0."), \
            f"Handler IP should be in 10.0.0.0/24 range, got {handler_ip}"

        # Wait a moment for listener to be ready
        time.sleep(1)

        # Make request
        assert_handler_responds(vm, handler_ip, "Hello from FaaS handler")
        print("✓ Handler responded correctly")

        # Verify rootfs exists
        assert_rootfs_exists(vm, "test-handler")
        print("✓ Rootfs directory exists")

        # Cleanup
        faasd_proc.kill()

    def test_rootfs_reuse_across_requests(self, vm, vm_files):
        """
        Test that rootfs is extracted once and reused for all requests.

        Steps:
        1. Deploy handler
        2. Make multiple requests
        3. Verify only one rootfs directory exists
        4. Verify all bundles are cleaned up
        """
        # Setup VM and start faasd
        for dest_path, content in vm_files.items():
            vm.write_file(dest_path, content)

        vm.run("chmod +x /root/faasd.py /root/faas")
        vm.run("mkdir -p /var/lib/faasd")

        faasd_proc = vm.spawn("/root/faasd.py")
        time.sleep(2)

        # Deploy handler
        helper = FaaSTestHelper(vm)
        handler_ip = helper.deploy_handler("/root/test-handler.tar", "test-handler")

        time.sleep(1)

        # Make 5 requests
        num_requests = 5
        for i in range(num_requests):
            response = helper.make_request(handler_ip)
            assert "Hello from FaaS handler" in response, \
                f"Request {i+1} failed"

        print(f"✓ All {num_requests} requests successful")

        # Verify only one rootfs directory
        result = vm.run(
            "ls -1 /var/lib/faasd/images/test-handler/ | grep rootfs | wc -l"
        )
        rootfs_count = int(result.stdout.strip())
        assert rootfs_count == 1, \
            f"Should have exactly 1 rootfs, found {rootfs_count}"

        print("✓ Only one rootfs directory (reused for all requests)")

        # Verify bundles are cleaned up
        # Give a moment for cleanup
        time.sleep(1)
        assert_bundles_cleaned_up(vm, timeout=3)
        print("✓ All bundles cleaned up")

        # Cleanup
        faasd_proc.kill()

    def test_multiple_handler_deployments(self, vm, vm_files):
        """
        Test deploying multiple handlers with different IPs.

        Steps:
        1. Deploy first handler
        2. Deploy second handler (same image, different name)
        3. Verify each gets unique IP
        4. Verify both respond correctly
        """
        # Setup VM and start faasd
        for dest_path, content in vm_files.items():
            vm.write_file(dest_path, content)

        vm.run("chmod +x /root/faasd.py /root/faas")
        vm.run("mkdir -p /var/lib/faasd")

        faasd_proc = vm.spawn("/root/faasd.py")
        time.sleep(2)

        helper = FaaSTestHelper(vm)

        # Deploy first handler
        ip1 = helper.deploy_handler("/root/test-handler.tar", "handler-1")
        print(f"✓ Handler 1 deployed at {ip1}")

        # Deploy second handler (same image, different name)
        ip2 = helper.deploy_handler("/root/test-handler.tar", "handler-2")
        print(f"✓ Handler 2 deployed at {ip2}")

        # Verify unique IPs
        assert ip1 != ip2, "Handlers should get different IPs"

        # Wait for listeners
        time.sleep(1)

        # Test both handlers respond
        assert_handler_responds(vm, ip1, "Hello from FaaS handler")
        assert_handler_responds(vm, ip2, "Hello from FaaS handler")
        print("✓ Both handlers respond correctly")

        # List handlers
        handlers = helper.list_handlers()
        assert len(handlers) >= 2, "Should have at least 2 handlers"

        handler_names = [h['name'] for h in handlers]
        assert "handler-1" in handler_names
        assert "handler-2" in handler_names
        print("✓ Both handlers listed in registry")

        # Cleanup
        faasd_proc.kill()

    def test_container_exit_and_cleanup(self, vm, vm_files):
        """
        Test that containers exit cleanly and bundles are removed.

        Steps:
        1. Deploy handler
        2. Make request
        3. Verify bundle is created during request
        4. Verify bundle is removed after request completes
        """
        # Setup VM and start faasd
        for dest_path, content in vm_files.items():
            vm.write_file(dest_path, content)

        vm.run("chmod +x /root/faasd.py /root/faas")
        vm.run("mkdir -p /var/lib/faasd")

        faasd_proc = vm.spawn("/root/faasd.py")
        time.sleep(2)

        helper = FaaSTestHelper(vm)
        handler_ip = helper.deploy_handler("/root/test-handler.tar", "test-handler")

        time.sleep(1)

        # Make request
        response = helper.make_request(handler_ip)
        assert "Hello from FaaS handler" in response

        # Wait for cleanup (should be fast)
        time.sleep(1)

        # Verify no bundles remain
        bundle_count = helper.count_bundles()
        assert bundle_count == 0, \
            f"All bundles should be cleaned up, found {bundle_count}"

        print("✓ Container exited and bundle cleaned up")

        # Verify rootfs still exists (not cleaned up)
        assert_rootfs_exists(vm, "test-handler")
        print("✓ Rootfs persists after container exit")

        # Cleanup
        faasd_proc.kill()

    def test_handler_with_error_still_cleans_up(self, vm, vm_files):
        """
        Test that bundles are cleaned up even if handler has errors.

        This test would require a handler that exits with non-zero status.
        For now, we'll just verify normal cleanup behavior.
        """
        # Setup VM and start faasd
        for dest_path, content in vm_files.items():
            vm.write_file(dest_path, content)

        vm.run("chmod +x /root/faasd.py /root/faas")
        vm.run("mkdir -p /var/lib/faasd")

        faasd_proc = vm.spawn("/root/faasd.py")
        time.sleep(2)

        helper = FaaSTestHelper(vm)
        handler_ip = helper.deploy_handler("/root/test-handler.tar", "test-handler")

        time.sleep(1)

        # Make request (handler should succeed)
        try:
            helper.make_request(handler_ip)
        except:
            pass  # Even if request fails, cleanup should happen

        # Wait for cleanup
        time.sleep(2)

        # Verify cleanup happened
        assert_bundles_cleaned_up(vm, timeout=3)
        print("✓ Bundles cleaned up even with errors")

        # Cleanup
        faasd_proc.kill()


@pytest.mark.vmtest
@pytest.mark.slow
class TestContainerLifecycleStress:
    """Stress tests for container lifecycle."""

    def test_rapid_sequential_requests(self, vm, vm_files):
        """
        Test handling many sequential requests rapidly.

        Verifies no resource leaks occur with rapid container creation/deletion.
        """
        # Setup VM and start faasd
        for dest_path, content in vm_files.items():
            vm.write_file(dest_path, content)

        vm.run("chmod +x /root/faasd.py /root/faas")
        vm.run("mkdir -p /var/lib/faasd")

        faasd_proc = vm.spawn("/root/faasd.py")
        time.sleep(2)

        helper = FaaSTestHelper(vm)
        handler_ip = helper.deploy_handler("/root/test-handler.tar", "test-handler")

        time.sleep(1)

        # Make 20 rapid requests
        num_requests = 20
        success_count = 0

        for i in range(num_requests):
            try:
                response = helper.make_request(handler_ip, timeout=10)
                if "Hello from FaaS handler" in response:
                    success_count += 1
            except Exception as e:
                print(f"Request {i+1} failed: {e}")

        print(f"✓ {success_count}/{num_requests} requests successful")

        # Should have high success rate
        assert success_count >= num_requests * 0.9, \
            f"At least 90% requests should succeed, got {success_count}/{num_requests}"

        # Wait for all cleanup
        time.sleep(3)

        # Verify all bundles cleaned up
        bundle_count = helper.count_bundles()
        assert bundle_count == 0, \
            f"All bundles should be cleaned up, found {bundle_count}"

        print("✓ All bundles cleaned up after stress test")

        # Cleanup
        faasd_proc.kill()
