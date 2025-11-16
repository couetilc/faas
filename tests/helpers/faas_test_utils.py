"""
Test utilities for FaaS platform testing.

This module provides helper functions for common testing operations
like deploying handlers, making requests, and asserting VM state.
"""

import re
import json
from typing import Optional, Dict, List


class FaaSTestHelper:
    """
    Helper class for interacting with FaaS platform in tests.

    This class provides high-level methods for common testing operations
    like deploying handlers, making requests, and checking system state.
    """

    def __init__(self, vm):
        """
        Initialize helper with VM instance.

        Args:
            vm: vmtest VM instance
        """
        self.vm = vm

    def deploy_handler(self, image_tar_path: str, handler_name: str) -> str:
        """
        Deploy a handler and return its assigned IP.

        Args:
            image_tar_path: Path to Docker image tarball in VM
            handler_name: Name for the handler

        Returns:
            Assigned IP address as string (e.g., "10.0.0.10")

        Raises:
            AssertionError: If deployment fails
        """
        result = self.vm.run(
            f"cat {image_tar_path} | /root/faas new {handler_name}",
            check=False
        )

        if result.returncode != 0:
            raise AssertionError(
                f"Handler deployment failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
            )

        # Parse IP from output
        ip = self._parse_ip(result.stdout)
        return ip

    def get_handler_ip(self, handler_name: str) -> str:
        """
        Get IP address for deployed handler.

        Args:
            handler_name: Name of the handler

        Returns:
            IP address as string
        """
        result = self.vm.run(f"/root/faas ip {handler_name}")
        return result.stdout.strip()

    def list_handlers(self) -> List[Dict[str, str]]:
        """
        List all deployed handlers.

        Returns:
            List of dicts with keys: name, ip, command
        """
        result = self.vm.run("/root/faas list")
        # Parse output (skip header lines)
        handlers = []
        lines = result.stdout.strip().split('\n')

        for line in lines:
            if line.startswith('-') or line.startswith('Name'):
                continue
            parts = line.split()
            if len(parts) >= 3:
                handlers.append({
                    'name': parts[0],
                    'ip': parts[1],
                    'command': ' '.join(parts[2:])
                })

        return handlers

    def make_request(self, ip: str, path: str = "/", timeout: int = 5) -> str:
        """
        Make HTTP request to handler.

        Args:
            ip: Handler IP address
            path: HTTP path
            timeout: Request timeout in seconds

        Returns:
            Response body as string

        Raises:
            AssertionError: If request fails
        """
        result = self.vm.run(
            f"curl -s --max-time {timeout} http://{ip}{path}",
            check=False
        )

        if result.returncode != 0:
            raise AssertionError(
                f"Request to {ip}{path} failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
            )

        return result.stdout

    def check_ip_configured(self, ip: str) -> bool:
        """
        Check if IP is configured on loopback interface.

        Args:
            ip: IP address to check

        Returns:
            True if IP is configured, False otherwise
        """
        result = self.vm.run(f"ip addr show lo | grep {ip}", check=False)
        return result.returncode == 0 and ip in result.stdout

    def check_ip_has_label(self, ip: str, label: str) -> bool:
        """
        Check if IP has specific label.

        Args:
            ip: IP address to check
            label: Expected label (e.g., "lo:faas")

        Returns:
            True if IP has the label
        """
        result = self.vm.run(f"ip addr show lo", check=False)
        if result.returncode != 0:
            return False

        # Look for line with both IP and label
        for line in result.stdout.split('\n'):
            if ip in line and label in line:
                return True
        return False

    def check_rootfs_exists(self, handler_name: str) -> bool:
        """
        Check if rootfs directory exists for handler.

        Args:
            handler_name: Name of the handler

        Returns:
            True if rootfs exists
        """
        result = self.vm.run(
            f"test -d /var/lib/faasd/images/{handler_name}/rootfs",
            check=False
        )
        return result.returncode == 0

    def count_bundles(self) -> int:
        """
        Count number of bundle directories.

        Returns:
            Number of bundles in /var/lib/faasd/bundles/
        """
        result = self.vm.run(
            "ls -1 /var/lib/faasd/bundles/ 2>/dev/null | wc -l",
            check=False
        )
        if result.returncode != 0:
            return 0
        return int(result.stdout.strip())

    def read_registry(self) -> Dict:
        """
        Read and parse registry.json.

        Returns:
            Registry data as dict
        """
        result = self.vm.run("cat /var/lib/faasd/registry.json")
        return json.loads(result.stdout)

    def get_process_count(self, process_name: str) -> int:
        """
        Count number of running processes with given name.

        Args:
            process_name: Process name to search for

        Returns:
            Number of matching processes
        """
        result = self.vm.run(
            f"ps aux | grep '{process_name}' | grep -v grep | wc -l",
            check=False
        )
        if result.returncode != 0:
            return 0
        return int(result.stdout.strip())

    def wait_for_cleanup(self, timeout: int = 5) -> bool:
        """
        Wait for all bundles to be cleaned up.

        Args:
            timeout: Maximum time to wait in seconds

        Returns:
            True if cleanup completed, False if timeout
        """
        import time
        start = time.time()
        while time.time() - start < timeout:
            if self.count_bundles() == 0:
                return True
            time.sleep(0.1)
        return False

    def _parse_ip(self, output: str) -> str:
        """Parse IP address from CLI output."""
        match = re.search(r'\d+\.\d+\.\d+\.\d+', output)
        if match:
            return match.group(0)
        raise ValueError(f"No IP address found in output: {output}")


def assert_handler_responds(vm, ip: str, expected_substring: str, timeout: int = 5):
    """
    Assert that handler responds with expected content.

    Args:
        vm: vmtest VM instance
        ip: Handler IP address
        expected_substring: String that should appear in response
        timeout: Request timeout

    Raises:
        AssertionError: If request fails or response doesn't contain expected content
    """
    helper = FaaSTestHelper(vm)
    response = helper.make_request(ip, timeout=timeout)
    assert expected_substring in response, \
        f"Expected '{expected_substring}' in response, got: {response}"


def assert_ip_configured(vm, ip: str, should_exist: bool = True):
    """
    Assert IP configuration state on loopback interface.

    Args:
        vm: vmtest VM instance
        ip: IP address to check
        should_exist: True to assert IP exists, False to assert it doesn't

    Raises:
        AssertionError: If IP state doesn't match expected
    """
    helper = FaaSTestHelper(vm)
    exists = helper.check_ip_configured(ip)

    if should_exist:
        assert exists, f"IP {ip} should be configured on loopback interface"
    else:
        assert not exists, f"IP {ip} should NOT be configured on loopback interface"


def assert_rootfs_exists(vm, handler_name: str):
    """
    Assert that rootfs directory exists for handler.

    Args:
        vm: vmtest VM instance
        handler_name: Name of the handler

    Raises:
        AssertionError: If rootfs doesn't exist
    """
    helper = FaaSTestHelper(vm)
    assert helper.check_rootfs_exists(handler_name), \
        f"Rootfs for {handler_name} should exist at /var/lib/faasd/images/{handler_name}/rootfs"


def assert_bundles_cleaned_up(vm, timeout: int = 5):
    """
    Assert that all bundle directories have been cleaned up.

    Args:
        vm: vmtest VM instance
        timeout: Maximum time to wait for cleanup

    Raises:
        AssertionError: If bundles still exist after timeout
    """
    helper = FaaSTestHelper(vm)
    cleaned = helper.wait_for_cleanup(timeout)
    assert cleaned, f"Bundles not cleaned up after {timeout}s"
