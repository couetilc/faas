#!/usr/bin/env python3
"""
Fibonacci FaaS Handler

This handler receives HTTP requests via a TCP socket passed through SCM_RIGHTS,
computes the Fibonacci sequence for n steps, and returns the result as an HTTP response.

Usage:
    python3 handler.py

The handler expects:
- A Unix domain socket at /control.sock
- HTTP GET requests with query parameter 'n' (e.g., GET /?n=10 HTTP/1.1)
- If n is not provided, defaults to 10
"""

import socket
import array
import sys
import os
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs


def calculate_fibonacci(n):
    """
    Calculate Fibonacci sequence for n steps.

    Args:
        n: Number of Fibonacci numbers to generate (must be >= 1)

    Returns:
        List of Fibonacci numbers
    """
    if n <= 0:
        return []
    elif n == 1:
        return [0]
    elif n == 2:
        return [0, 1]

    fib = [0, 1]
    for i in range(2, n):
        fib.append(fib[i-1] + fib[i-2])

    return fib


class FibonacciHandler(BaseHTTPRequestHandler):
    """HTTP request handler for Fibonacci calculations."""

    def do_GET(self):
        """Handle GET requests to compute Fibonacci sequence."""
        # Parse query parameters
        parsed_path = urlparse(self.path)
        query_params = parse_qs(parsed_path.query)

        # Extract 'n' parameter (parse_qs returns lists)
        n_str = query_params.get('n', ['10'])[0]

        try:
            n = int(n_str)
            if n < 0:
                raise ValueError("n must be non-negative")
            if n > 10000:
                raise ValueError("n is too large (max 10000)")
        except ValueError as e:
            self.send_error(400, f"Invalid parameter 'n': {str(e)}")
            return

        # Calculate Fibonacci sequence
        fib_sequence = calculate_fibonacci(n)

        # Format response
        if n == 0:
            response_body = "Fibonacci sequence (0 steps): []\n"
        else:
            fib_str = ", ".join(map(str, fib_sequence))
            response_body = f"Fibonacci sequence ({n} steps):\n{fib_str}\n"

        # Send response
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain')
        self.send_header('Content-Length', str(len(response_body)))
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(response_body.encode('utf-8'))
        self.wfile.flush()

    def log_message(self, format, *args):
        """Override to log to stderr."""
        sys.stderr.write(f"[fibonacci-handler] {format % args}\n")


def receive_socket_fd():
    """Connect to control socket and receive TCP socket FD via SCM_RIGHTS."""
    try:
        # Connect to Unix domain socket
        control_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        control_sock.connect('/control.sock')
        print(f"[Container {os.getpid()}] Connected to control socket", file=sys.stderr)
    except (FileNotFoundError, ConnectionRefusedError) as e:
        print(f"[Container {os.getpid()}] Error: Could not connect to /control.sock: {e}",
              file=sys.stderr)
        sys.exit(1)

    # Receive FD via SCM_RIGHTS
    fds = array.array('i')
    msg, ancdata, flags, addr = control_sock.recvmsg(
        1024,
        socket.CMSG_SPACE(array.array('i', [0]).itemsize)
    )

    # Extract FD from ancillary data
    for cmsg_level, cmsg_type, cmsg_data in ancdata:
        if (cmsg_level == socket.SOL_SOCKET and
            cmsg_type == socket.SCM_RIGHTS):
            fds.frombytes(cmsg_data)
            break

    control_sock.close()

    if len(fds) == 0:
        print(f"[Container {os.getpid()}] Error: No file descriptor received",
              file=sys.stderr)
        sys.exit(1)

    received_fd = fds[0]
    print(f"[Container {os.getpid()}] Received FD: {received_fd}", file=sys.stderr)
    return received_fd


def main():
    """
    Main handler loop:
    1. Connect to /control.sock
    2. Receive TCP socket FD via SCM_RIGHTS
    3. Handle HTTP request using BaseHTTPRequestHandler
    4. Close socket and exit
    """
    print(f"[Container {os.getpid()}] Fibonacci handler starting", file=sys.stderr)

    # Receive TCP socket FD from server
    tcp_fd = receive_socket_fd()

    # Reconstruct TCP socket from FD
    client_sock = socket.fromfd(tcp_fd, socket.AF_INET, socket.SOCK_STREAM)

    # Get client address for logging
    try:
        client_addr = client_sock.getpeername()
        print(f"[Container {os.getpid()}] Handling request from {client_addr}",
              file=sys.stderr)
    except OSError:
        client_addr = ('unknown', 0)

    # Handle HTTP request using BaseHTTPRequestHandler
    # Pass the socket directly - BaseHTTPRequestHandler will call makefile() internally
    try:
        FibonacciHandler(client_sock, client_addr, None)
        print(f"[Container {os.getpid()}] Request handled successfully", file=sys.stderr)
    except Exception as e:
        print(f"[Container {os.getpid()}] Error in handler: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
    finally:
        # Clean up - try to close socket if not already closed
        try:
            client_sock.close()
        except:
            pass
        print(f"[Container {os.getpid()}] Handler complete", file=sys.stderr)


if __name__ == '__main__':
    main()
