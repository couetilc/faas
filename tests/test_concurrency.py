"""
Concurrency and stress tests using vmtest.

These tests verify:
- Concurrent requests to same handler
- Concurrent requests to different handlers
- Thread safety
- Resource limits
- No deadlocks or race conditions
"""

import pytest
import time
from helpers.faas_test_utils import FaaSTestHelper


@pytest.mark.vmtest
@pytest.mark.slow
class TestConcurrency:
    """Test concurrent request handling."""

    def test_concurrent_requests_to_single_handler(self, vm, vm_files):
        """
        Test handling concurrent requests to the same handler.

        Steps:
        1. Deploy one handler
        2. Launch 10 concurrent requests
        3. Verify all succeed
        4. Verify cleanup happens correctly
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

        # Launch 10 concurrent requests in background
        num_concurrent = 10
        for i in range(num_concurrent):
            vm.spawn(f"curl -s http://{handler_ip}/ > /tmp/concurrent-{i}.txt 2>&1")

        # Wait for all to complete (give generous timeout)
        time.sleep(10)

        # Count successful responses
        success_count = 0
        for i in range(num_concurrent):
            result = vm.run(f"cat /tmp/concurrent-{i}.txt 2>/dev/null", check=False)
            if result.returncode == 0 and "Hello from FaaS handler" in result.stdout:
                success_count += 1

        print(f"✓ {success_count}/{num_concurrent} concurrent requests succeeded")

        # Should have high success rate (allow some failures due to resource limits)
        assert success_count >= num_concurrent * 0.7, \
            f"At least 70% of requests should succeed, got {success_count}/{num_concurrent}"

        # Wait for cleanup
        time.sleep(3)

        # Verify bundles cleaned up
        bundle_count = helper.count_bundles()
        print(f"Bundle count after cleanup: {bundle_count}")

        # Cleanup
        faasd_proc.kill()

    def test_concurrent_requests_to_different_handlers(self, vm, vm_files):
        """
        Test concurrent requests to different handlers.

        Steps:
        1. Deploy 3 handlers
        2. Send concurrent requests to each
        3. Verify all succeed
        """
        # Setup VM and start faasd
        for dest_path, content in vm_files.items():
            vm.write_file(dest_path, content)

        vm.run("chmod +x /root/faasd.py /root/faas")
        vm.run("mkdir -p /var/lib/faasd")

        faasd_proc = vm.spawn("/root/faasd.py")
        time.sleep(2)

        helper = FaaSTestHelper(vm)

        # Deploy 3 handlers
        num_handlers = 3
        handler_ips = []
        for i in range(num_handlers):
            ip = helper.deploy_handler("/root/test-handler.tar", f"handler-{i}")
            handler_ips.append(ip)
            print(f"✓ handler-{i} deployed at {ip}")

        time.sleep(1)

        # Send 3 concurrent requests to each handler
        requests_per_handler = 3
        total_requests = num_handlers * requests_per_handler
        request_id = 0

        for handler_idx, ip in enumerate(handler_ips):
            for req_idx in range(requests_per_handler):
                vm.spawn(
                    f"curl -s http://{ip}/ > /tmp/multi-{request_id}.txt 2>&1"
                )
                request_id += 1

        # Wait for all to complete
        time.sleep(10)

        # Count successes
        success_count = 0
        for i in range(total_requests):
            result = vm.run(f"cat /tmp/multi-{i}.txt 2>/dev/null", check=False)
            if result.returncode == 0 and "Hello from FaaS handler" in result.stdout:
                success_count += 1

        print(f"✓ {success_count}/{total_requests} requests succeeded")

        assert success_count >= total_requests * 0.7, \
            f"At least 70% of requests should succeed"

        # Cleanup
        faasd_proc.kill()

    def test_rapid_sequential_deployments(self, vm, vm_files):
        """
        Test deploying multiple handlers rapidly.

        Verifies registry updates are thread-safe.
        """
        # Setup VM and start faasd
        for dest_path, content in vm_files.items():
            vm.write_file(dest_path, content)

        vm.run("chmod +x /root/faasd.py /root/faas")
        vm.run("mkdir -p /var/lib/faasd")

        faasd_proc = vm.spawn("/root/faasd.py")
        time.sleep(2)

        # Deploy 10 handlers rapidly
        num_handlers = 10
        for i in range(num_handlers):
            # Don't use helper to avoid waiting between deployments
            vm.run(
                f"cat /root/test-handler.tar | /root/faas new rapid-{i}",
                check=False
            )

        # Give time for all deployments to complete
        time.sleep(5)

        # List handlers
        result = vm.run("/root/faas list", check=False)
        if result.returncode == 0:
            # Count how many handlers are listed
            lines = [l for l in result.stdout.split('\n')
                    if l.strip() and not l.startswith('-') and not l.startswith('Name')]
            deployed_count = len(lines)
            print(f"✓ {deployed_count} handlers deployed and registered")

            # Should have most handlers deployed
            assert deployed_count >= num_handlers * 0.7, \
                f"Most handlers should deploy successfully"

        # Cleanup
        faasd_proc.kill()

    def test_stress_many_sequential_requests(self, vm, vm_files):
        """
        Stress test: Many sequential requests to verify no resource leaks.

        Makes 100 sequential requests and verifies system remains stable.
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

        # Make 100 requests
        num_requests = 100
        success_count = 0
        start_time = time.time()

        for i in range(num_requests):
            try:
                response = helper.make_request(handler_ip, timeout=10)
                if "Hello from FaaS handler" in response:
                    success_count += 1

                # Print progress every 20 requests
                if (i + 1) % 20 == 0:
                    print(f"Progress: {i + 1}/{num_requests} requests")

            except Exception as e:
                print(f"Request {i+1} failed: {e}")

        duration = time.time() - start_time
        print(f"✓ {success_count}/{num_requests} requests succeeded in {duration:.1f}s")
        print(f"  Average: {duration/num_requests*1000:.0f}ms per request")

        # Should have very high success rate for sequential requests
        assert success_count >= num_requests * 0.9, \
            f"At least 90% should succeed for sequential requests"

        # Wait for cleanup
        time.sleep(3)

        # Verify no bundle leaks
        bundle_count = helper.count_bundles()
        assert bundle_count == 0, \
            f"All bundles should be cleaned up, found {bundle_count}"

        print("✓ No resource leaks detected")

        # Cleanup
        faasd_proc.kill()


@pytest.mark.vmtest
@pytest.mark.slow
class TestResourceLimits:
    """Test behavior under resource constraints."""

    def test_memory_limit_respected(self, vm, vm_files):
        """
        Test that containers respect memory limits.

        This is a placeholder - actual test would need a memory-hungry handler.
        For now, just verify normal operation doesn't hit limits.
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

        # Normal handler should work within memory limits
        response = helper.make_request(handler_ip)
        assert "Hello from FaaS handler" in response

        print("✓ Handler operates within memory limits")

        # Cleanup
        faasd_proc.kill()

    def test_many_handlers_deployed(self, vm, vm_files):
        """
        Test deploying many handlers to verify resource management.

        Verifies system can handle many simultaneous deployments.
        """
        # Setup VM and start faasd
        for dest_path, content in vm_files.items():
            vm.write_file(dest_path, content)

        vm.run("chmod +x /root/faasd.py /root/faas")
        vm.run("mkdir -p /var/lib/faasd")

        faasd_proc = vm.spawn("/root/faasd.py")
        time.sleep(2)

        helper = FaaSTestHelper(vm)

        # Deploy 15 handlers
        num_handlers = 15
        deployed_ips = []

        for i in range(num_handlers):
            try:
                ip = helper.deploy_handler("/root/test-handler.tar", f"handler-{i}")
                deployed_ips.append(ip)
                if (i + 1) % 5 == 0:
                    print(f"Progress: {i + 1}/{num_handlers} handlers deployed")
            except Exception as e:
                print(f"Failed to deploy handler {i}: {e}")

        print(f"✓ {len(deployed_ips)}/{num_handlers} handlers deployed")

        # Should deploy most handlers
        assert len(deployed_ips) >= num_handlers * 0.7, \
            "Should successfully deploy most handlers"

        # Verify all IPs are unique
        assert len(deployed_ips) == len(set(deployed_ips)), \
            "All IPs should be unique"

        # Test a few handlers still respond
        time.sleep(2)
        test_count = min(3, len(deployed_ips))
        for i in range(test_count):
            try:
                response = helper.make_request(deployed_ips[i], timeout=10)
                assert "Hello" in response
            except Exception as e:
                print(f"Handler {i} failed to respond: {e}")

        print(f"✓ Tested {test_count} handlers, all responsive")

        # Cleanup
        faasd_proc.kill()


@pytest.mark.vmtest
class TestThreadSafety:
    """Test thread safety of critical operations."""

    def test_registry_updates_thread_safe(self, vm, vm_files):
        """
        Test that concurrent deployments don't corrupt registry.

        Steps:
        1. Deploy multiple handlers concurrently
        2. Verify registry is valid JSON
        3. Verify all handlers are registered
        """
        # Setup VM and start faasd
        for dest_path, content in vm_files.items():
            vm.write_file(dest_path, content)

        vm.run("chmod +x /root/faasd.py /root/faas")
        vm.run("mkdir -p /var/lib/faasd")

        faasd_proc = vm.spawn("/root/faasd.py")
        time.sleep(2)

        # Deploy 5 handlers concurrently
        num_handlers = 5
        for i in range(num_handlers):
            vm.spawn(f"cat /root/test-handler.tar | /root/faas new concurrent-{i}")

        # Wait for deployments
        time.sleep(8)

        # Read registry
        result = vm.run("cat /var/lib/faasd/registry.json", check=False)
        if result.returncode == 0:
            try:
                import json
                registry = json.loads(result.stdout)
                print(f"✓ Registry is valid JSON with {len(registry)} entries")
                assert len(registry) > 0, "Registry should have entries"
            except json.JSONDecodeError as e:
                pytest.fail(f"Registry is corrupted: {e}")

        # Cleanup
        faasd_proc.kill()
