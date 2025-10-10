#!/usr/bin/env python3
"""
Test client for FaaS daemon.

Tests both IP addresses to verify the server is listening and responding
correctly on multiple IPs.
"""

import http.client
import sys


def test_endpoint(host, port, path='/'):
    """Test a single endpoint with GET and POST requests."""
    print(f"\n{'='*60}")
    print(f"Testing {host}:{port}")
    print('='*60)

    try:
        # Test GET request
        print(f"\n--- GET {path} ---")
        conn = http.client.HTTPConnection(host, port, timeout=5)
        conn.request('GET', path)
        response = conn.getresponse()
        body = response.read().decode('utf-8')

        print(f"Status: {response.status} {response.reason}")
        print(f"Response:\n{body}")
        conn.close()

        # Test POST request
        print(f"\n--- POST {path} ---")
        conn = http.client.HTTPConnection(host, port, timeout=5)
        post_data = "Hello from test client!"
        conn.request('POST', path, body=post_data.encode())
        response = conn.getresponse()
        body = response.read().decode('utf-8')

        print(f"Status: {response.status} {response.reason}")
        print(f"Response:\n{body}")
        conn.close()

        print(f"\n✓ {host}:{port} is working correctly")
        return True

    except ConnectionRefusedError:
        print(f"\n✗ Connection refused to {host}:{port}")
        print(f"  Make sure the server is running with: sudo python3 server.py")
        return False
    except OSError as e:
        print(f"\n✗ Network error connecting to {host}:{port}: {e}")
        print(f"  This may indicate the IP address is not configured on your system")
        return False
    except Exception as e:
        print(f"\n✗ Error testing {host}:{port}: {e}")
        return False


def main():
    print("FaaS Daemon Test Client")
    print("="*60)

    # Test endpoints
    endpoints = [
        ('10.0.0.1', 80),
        ('10.0.0.2', 80),
    ]

    results = []
    for host, port in endpoints:
        success = test_endpoint(host, port)
        results.append((host, port, success))

    # Summary
    print(f"\n\n{'='*60}")
    print("Test Summary")
    print('='*60)

    for host, port, success in results:
        status = "✓ PASS" if success else "✗ FAIL"
        print(f"{status}: {host}:{port}")

    # Exit code
    all_passed = all(success for _, _, success in results)
    if all_passed:
        print("\nAll tests passed!")
        sys.exit(0)
    else:
        print("\nSome tests failed.")
        print("\nTroubleshooting:")
        print("1. Make sure the server is running: sudo python3 server.py")
        print("2. Verify the IP addresses are configured on your system:")
        print("   - macOS: sudo ifconfig lo0 alias 10.0.0.1 netmask 255.255.255.0")
        print("   - macOS: sudo ifconfig lo0 alias 10.0.0.2 netmask 255.255.255.0")
        print("   - Linux: sudo ip addr add 10.0.0.1/24 dev lo")
        print("   - Linux: sudo ip addr add 10.0.0.2/24 dev lo")
        sys.exit(1)


if __name__ == '__main__':
    main()
