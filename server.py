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
import signal
import uuid
import array


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


def handle_connection(client_sock, client_addr, docker_image):
    """Spawn a Docker container and pass the TCP socket via SCM_RIGHTS."""
    tcp_fd = client_sock.fileno()

    print(f"Connection from {client_addr}, spawning Docker container")

    # Create Unix domain socket for control channel
    sock_path = f"/tmp/faas-{uuid.uuid4()}.sock"
    control_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

    try:
        control_sock.bind(sock_path)
        control_sock.listen(1)
        print(f"Control socket created at {sock_path}")

        # Start Docker container with volume mount
        container_name = f"faas-{uuid.uuid4()}"
        proc = subprocess.Popen([
            'docker', 'run', '--rm',
            '--name', container_name,
            '-v', f'{sock_path}:/control.sock',
            docker_image
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        print(f"Container {container_name} started, waiting for connection...")

        # Wait for container to connect (with timeout)
        control_sock.settimeout(5.0)
        conn, _ = control_sock.accept()
        print(f"Container connected to control socket")

        # Send TCP socket FD over Unix socket using SCM_RIGHTS
        conn.sendmsg(
            [b'SOCKET'],  # Regular data (marker)
            [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array('i', [tcp_fd]))]
        )
        print(f"Sent FD {tcp_fd} to container via SCM_RIGHTS")

        # Close our references - container now owns the TCP socket
        client_sock.close()
        conn.close()
        control_sock.close()

        print(f"Handoff complete for {client_addr}")

    except socket.timeout:
        print(f"Error: Container did not connect to control socket within timeout")
        client_sock.close()
        control_sock.close()
    except Exception as e:
        print(f"Error handling connection: {e}")
        import traceback
        traceback.print_exc()
        client_sock.close()
        try:
            control_sock.close()
        except OSError:
            pass
    finally:
        # Clean up Unix socket file
        try:
            os.unlink(sock_path)
            print(f"Cleaned up {sock_path}")
        except FileNotFoundError:
            pass
        except Exception as e:
            print(f"Warning: Could not remove {sock_path}: {e}")


def main():
    # Configuration
    listen_ips = [
        ('10.0.0.1', 8080),
        ('10.0.0.2', 8080),
    ]
    docker_image = 'faas-handler:latest'

    # Set up automatic zombie process reaping
    # When a child process exits, the OS will automatically reap it
    signal.signal(signal.SIGCHLD, signal.SIG_IGN)

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
                handle_connection(client_sock, client_addr, docker_image)

    except KeyboardInterrupt:
        print("\n\nShutting down...")
    finally:
        for sock in server_sockets:
            sock.close()


if __name__ == '__main__':
    main()
