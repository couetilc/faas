#!/usr/bin/env python3
"""
Test FaaS Handler

Implements the FaaS handler protocol:
1. Connect to /control.sock
2. Receive TCP socket FD via SCM_RIGHTS
3. Handle HTTP request
4. Exit cleanly
"""

import socket
import array
import sys

def main():
    print("[handler] Starting FaaS handler", file=sys.stderr)

    # 1. Connect to control socket
    control_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

    try:
        print("[handler] Connecting to /control.sock", file=sys.stderr)
        control_sock.connect('/control.sock')
        print("[handler] Connected to control socket", file=sys.stderr)
    except Exception as e:
        print(f"[handler] Error: Could not connect to /control.sock: {e}", file=sys.stderr)
        sys.exit(1)

    # 2. Receive TCP socket FD via SCM_RIGHTS
    print("[handler] Waiting for socket FD via SCM_RIGHTS", file=sys.stderr)
    fds = array.array('i')
    msg, ancdata, flags, addr = control_sock.recvmsg(
        1024,
        socket.CMSG_SPACE(array.array('i', [0]).itemsize)
    )

    for level, type, data in ancdata:
        if level == socket.SOL_SOCKET and type == socket.SCM_RIGHTS:
            fds.frombytes(data)
            break

    if len(fds) == 0:
        print("[handler] Error: No FD received", file=sys.stderr)
        sys.exit(1)

    tcp_fd = fds[0]
    print(f"[handler] Received FD: {tcp_fd}", file=sys.stderr)
    control_sock.close()

    # 3. Reconstruct TCP socket from FD
    client_sock = socket.fromfd(tcp_fd, socket.AF_INET, socket.SOCK_STREAM)
    print("[handler] Reconstructed TCP socket", file=sys.stderr)

    # 4. Read HTTP request
    print("[handler] Reading HTTP request", file=sys.stderr)
    request_data = b""
    while b"\r\n\r\n" not in request_data:
        chunk = client_sock.recv(1024)
        if not chunk:
            break
        request_data += chunk

    # Parse request line
    request_lines = request_data.decode('utf-8', errors='ignore').split('\r\n')
    request_line = request_lines[0] if request_lines else "GET / HTTP/1.1"
    print(f"[handler] Request: {request_line}", file=sys.stderr)

    # 5. Generate response
    response_body = f"Hello from FaaS handler!\n\nRequest: {request_line}\n".encode()
    response_header = (
        f"HTTP/1.1 200 OK\r\n"
        f"Content-Type: text/plain\r\n"
        f"Content-Length: {len(response_body)}\r\n"
        f"\r\n"
    ).encode()
    response = response_header + response_body

    # 6. Send response
    print("[handler] Sending response", file=sys.stderr)
    client_sock.sendall(response)
    client_sock.close()

    print("[handler] Request handled successfully", file=sys.stderr)

if __name__ == '__main__':
    main()
