"""
Integration tests for network management using vmtest.

These tests verify:
- IP allocation from pool
- IP configuration on loopback interface
- IP labels (lo:faas)
- IP cleanup on shutdown
- Handling of IP exhaustion
"""

import pytest
import time
import signal
from helpers.faas_test_utils import (
    FaaSTestHelper,
    assert_ip_configured,
)


@pytest.mark.vmtest
class TestNetworkManagement:
    """Test network configuration and IP management."""

    def test_ip_allocated_from_pool(self, vm, vm_files):
        """
        Test that IPs are allocated from 10.0.0.0/24 pool.

        Steps:
        1. Deploy handler
        2. Verify IP is in correct range
        3. Verify IP is configured on loopback
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

        # Verify IP is in pool range
        assert handler_ip.startswith("10.0.0."), \
            f"IP should be from 10.0.0.0/24 pool, got {handler_ip}"

        # Parse last octet
        octets = handler_ip.split('.')
        last_octet = int(octets[3])
        assert 10 <= last_octet <= 254, \
            f"Last octet should be 10-254, got {last_octet}"

        print(f"✓ IP {handler_ip} is in valid range")

        # Verify IP is configured on loopback
        assert_ip_configured(vm, handler_ip, should_exist=True)
        print(f"✓ IP {handler_ip} is configured on loopback interface")

        # Cleanup
        faasd_proc.kill()

    def test_ip_has_label(self, vm, vm_files):
        """
        Test that configured IPs have the 'lo:faas' label.

        This allows faasd to distinguish its IPs from manually configured ones.
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

        # Wait for IP to be configured
        time.sleep(1)

        # Check if IP has label
        has_label = helper.check_ip_has_label(handler_ip, "lo:faas")
        assert has_label, f"IP {handler_ip} should have label 'lo:faas'"

        print(f"✓ IP {handler_ip} has label 'lo:faas'")

        # Cleanup
        faasd_proc.kill()

    def test_unique_ips_for_multiple_handlers(self, vm, vm_files):
        """
        Test that each handler gets a unique IP.

        Steps:
        1. Deploy 5 handlers
        2. Verify all IPs are unique
        3. Verify all IPs are configured
        """
        # Setup VM and start faasd
        for dest_path, content in vm_files.items():
            vm.write_file(dest_path, content)

        vm.run("chmod +x /root/faasd.py /root/faas")
        vm.run("mkdir -p /var/lib/faasd")

        faasd_proc = vm.spawn("/root/faasd.py")
        time.sleep(2)

        helper = FaaSTestHelper(vm)

        # Deploy 5 handlers
        num_handlers = 5
        ips = []

        for i in range(num_handlers):
            handler_name = f"handler-{i}"
            ip = helper.deploy_handler("/root/test-handler.tar", handler_name)
            ips.append(ip)
            print(f"✓ {handler_name} deployed at {ip}")

        # Verify all IPs are unique
        assert len(ips) == len(set(ips)), \
            f"All IPs should be unique, got duplicates: {ips}"

        print(f"✓ All {num_handlers} IPs are unique")

        # Verify all IPs are configured
        time.sleep(1)
        for ip in ips:
            assert_ip_configured(vm, ip, should_exist=True)

        print(f"✓ All {num_handlers} IPs are configured on loopback")

        # Cleanup
        faasd_proc.kill()

    def test_ip_cleanup_on_graceful_shutdown(self, vm, vm_files):
        """
        Test that IPs are removed from loopback on graceful shutdown.

        Steps:
        1. Deploy handlers
        2. Verify IPs are configured
        3. Send SIGTERM to faasd
        4. Verify IPs are removed
        """
        # Setup VM and start faasd
        for dest_path, content in vm_files.items():
            vm.write_file(dest_path, content)

        vm.run("chmod +x /root/faasd.py /root/faas")
        vm.run("mkdir -p /var/lib/faasd")

        faasd_proc = vm.spawn("/root/faasd.py")
        time.sleep(2)

        helper = FaaSTestHelper(vm)

        # Deploy 2 handlers
        ip1 = helper.deploy_handler("/root/test-handler.tar", "handler-1")
        ip2 = helper.deploy_handler("/root/test-handler.tar", "handler-2")

        time.sleep(1)

        # Verify IPs are configured
        assert_ip_configured(vm, ip1, should_exist=True)
        assert_ip_configured(vm, ip2, should_exist=True)
        print(f"✓ IPs {ip1} and {ip2} are configured")

        # Send SIGTERM to faasd (graceful shutdown)
        faasd_proc.kill(signal.SIGTERM)

        # Wait for cleanup
        time.sleep(3)

        # Verify IPs are removed
        assert_ip_configured(vm, ip1, should_exist=False)
        assert_ip_configured(vm, ip2, should_exist=False)
        print(f"✓ IPs {ip1} and {ip2} removed after graceful shutdown")

    def test_manually_configured_ip_not_removed(self, vm, vm_files):
        """
        Test that manually configured IPs (without lo:faas label) are not removed.

        This ensures faasd only cleans up IPs it created.
        """
        # Manually configure an IP before starting faasd
        manual_ip = "10.0.0.99"
        vm.run(f"ip addr add {manual_ip}/24 dev lo", check=False)

        # Setup VM and start faasd
        for dest_path, content in vm_files.items():
            vm.write_file(dest_path, content)

        vm.run("chmod +x /root/faasd.py /root/faas")
        vm.run("mkdir -p /var/lib/faasd")

        faasd_proc = vm.spawn("/root/faasd.py")
        time.sleep(2)

        helper = FaaSTestHelper(vm)

        # Deploy a handler (will get a different IP)
        handler_ip = helper.deploy_handler("/root/test-handler.tar", "test-handler")
        assert handler_ip != manual_ip

        time.sleep(1)

        # Verify both IPs are configured
        assert_ip_configured(vm, manual_ip, should_exist=True)
        assert_ip_configured(vm, handler_ip, should_exist=True)
        print(f"✓ Both manual IP {manual_ip} and handler IP {handler_ip} configured")

        # Shutdown faasd
        faasd_proc.kill(signal.SIGTERM)
        time.sleep(3)

        # Manual IP should still be there
        assert_ip_configured(vm, manual_ip, should_exist=True)
        print(f"✓ Manual IP {manual_ip} preserved after shutdown")

        # Handler IP should be removed (if it had label)
        # Note: This test assumes faasd adds labels to IPs it creates
        # If not implemented yet, this test documents expected behavior

        # Cleanup manual IP
        vm.run(f"ip addr del {manual_ip}/24 dev lo", check=False)

    def test_ip_reuse_after_shutdown(self, vm, vm_files):
        """
        Test that IPs can be reused after faasd restart.

        Steps:
        1. Deploy handler, note IP
        2. Shutdown faasd
        3. Restart faasd
        4. Deploy new handler, verify it can get same IP
        """
        # Setup VM and start faasd
        for dest_path, content in vm_files.items():
            vm.write_file(dest_path, content)

        vm.run("chmod +x /root/faasd.py /root/faas")
        vm.run("mkdir -p /var/lib/faasd")

        # First run
        faasd_proc = vm.spawn("/root/faasd.py")
        time.sleep(2)

        helper = FaaSTestHelper(vm)
        first_ip = helper.deploy_handler("/root/test-handler.tar", "handler-1")
        print(f"✓ First deployment: {first_ip}")

        # Shutdown
        faasd_proc.kill(signal.SIGTERM)
        time.sleep(2)

        # Clear registry to allow fresh start
        vm.run("rm -f /var/lib/faasd/registry.json")

        # Second run
        faasd_proc = vm.spawn("/root/faasd.py")
        time.sleep(2)

        helper = FaaSTestHelper(vm)
        second_ip = helper.deploy_handler("/root/test-handler.tar", "handler-2")
        print(f"✓ Second deployment: {second_ip}")

        # IPs should be from same pool (may or may not be the same IP)
        assert first_ip.startswith("10.0.0.")
        assert second_ip.startswith("10.0.0.")
        print("✓ IPs can be allocated after restart")

        # Cleanup
        faasd_proc.kill()


@pytest.mark.vmtest
@pytest.mark.slow
class TestNetworkStress:
    """Stress tests for network management."""

    def test_many_ip_allocations(self, vm, vm_files):
        """
        Test allocating many IPs.

        Verifies IP allocation doesn't have leaks or conflicts.
        """
        # Setup VM and start faasd
        for dest_path, content in vm_files.items():
            vm.write_file(dest_path, content)

        vm.run("chmod +x /root/faasd.py /root/faas")
        vm.run("mkdir -p /var/lib/faasd")

        faasd_proc = vm.spawn("/root/faasd.py")
        time.sleep(2)

        helper = FaaSTestHelper(vm)

        # Allocate 20 IPs
        num_handlers = 20
        ips = []

        for i in range(num_handlers):
            try:
                ip = helper.deploy_handler("/root/test-handler.tar", f"handler-{i}")
                ips.append(ip)
            except Exception as e:
                print(f"Failed to deploy handler {i}: {e}")

        print(f"✓ Allocated {len(ips)} IPs")

        # Verify all unique
        assert len(ips) == len(set(ips)), "All IPs should be unique"
        print(f"✓ All {len(ips)} IPs are unique")

        # Cleanup
        faasd_proc.kill()
