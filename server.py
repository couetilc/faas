#!/usr/bin/env python3
"""
FaaS daemon - Multi-IP HTTP server with child process spawning.

Listens on multiple IP addresses using select() for socket multiplexing.
Spawns a child process for each incoming connection and passes the client
socket file descriptor to the child.
"""

import socket
import select
import subprocess
import sys
import os


def create_server_socket(host, port):
    """Create and bind a server socket to the specified host:port."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    try:
        sock.bind((host, port))
        sock.listen(5)
        print(f"Listening on {host}:{port}")
        return sock
    except PermissionError:
        print(f"Error: Permission denied to bind to {host}:{port}")
        print("Note: Binding to port 80 requires root/sudo privileges")
        sys.exit(1)
    except OSError as e:
        print(f"Error binding to {host}:{port}: {e}")
        sys.exit(1)


def handle_connection(client_sock, client_addr, handler_script):
    """Spawn a child process to handle the client connection."""
    fd = client_sock.fileno()

    print(f"Connection from {client_addr}, spawning child with FD {fd}")

    # Spawn child process, passing the socket file descriptor
    try:
        proc = subprocess.Popen(
            [sys.executable, handler_script, '--fd', str(fd)],
            pass_fds=(fd,)
        )

        # Parent must close its reference to the socket
        # The child now owns it
        client_sock.close()

        # Optionally wait for child (for POC, we'll just let it run)
        # In production, you'd want proper child process management

    except Exception as e:
        print(f"Error spawning child process: {e}")
        client_sock.close()


def main():
    # Configuration
    listen_ips = [
        ('10.0.0.1', 80),
        ('10.0.0.2', 80),
    ]
    handler_script = os.path.join(os.path.dirname(__file__), 'handler.py')

    # Verify handler exists
    if not os.path.exists(handler_script):
        print(f"Error: Handler script not found: {handler_script}")
        sys.exit(1)

    # Create server sockets
    server_sockets = []
    socket_map = {}

    for host, port in listen_ips:
        sock = create_server_socket(host, port)
        server_sockets.append(sock)
        socket_map[sock] = (host, port)

    print(f"\nFaaS daemon ready. Monitoring {len(server_sockets)} addresses.")
    print("Press Ctrl+C to stop.\n")

    # Main event loop - single-threaded select-based multiplexing
    try:
        while True:
            # Wait for activity on any server socket
            readable, _, _ = select.select(server_sockets, [], [])

            # Handle each ready socket
            for server_sock in readable:
                host, port = socket_map[server_sock]
                client_sock, client_addr = server_sock.accept()

                print(f"[{host}:{port}] Accepted connection from {client_addr}")
                handle_connection(client_sock, client_addr, handler_script)

    except KeyboardInterrupt:
        print("\n\nShutting down...")
    finally:
        for sock in server_sockets:
            sock.close()


if __name__ == '__main__':
    main()
