# Socket Handoff to Docker Containers via Unix Domain Sockets

## Overview

This document describes how to pass TCP socket file descriptors from a parent process to containerized child processes using Unix domain sockets and the `SCM_RIGHTS` control message mechanism.

## The Problem

When moving from fork/exec to Docker containers, we lose the ability to pass file descriptors directly:
- `subprocess.Popen(..., pass_fds=(fd,))` works for native processes
- Docker containers run in separate namespaces and cannot inherit file descriptors from the host

## The Solution

Use **Unix domain sockets** with **SCM_RIGHTS** to pass file descriptors between processes, even across container boundaries.

### Architecture Flow

```
1. Server accepts TCP connection → FD 5 (example)
2. Server creates Unix domain socket → /tmp/faas-<uuid>.sock
3. Server starts container with volume mount → -v /tmp/faas-<uuid>.sock:/control.sock
4. Container connects to /control.sock and waits
5. Server sends FD 5 over Unix socket using SCM_RIGHTS
6. Container receives FD → becomes FD 3 in container's namespace
7. Container reconstructs TCP socket from FD 3
8. Container handles HTTP request on TCP socket
9. Container exits, server cleans up
```

## Understanding SCM_RIGHTS

### What is SCM_RIGHTS?

`SCM_RIGHTS` is a **Socket Control Message** type that allows passing open file descriptors between processes over Unix domain sockets. It's part of the POSIX specification for "ancillary data" (control messages).

### Why is it called SCM_RIGHTS?

- **SCM** = Socket Control Message (or Socket-level Control Message)
- **RIGHTS** = "Access rights" - you're transferring the *right* to access a file descriptor

The name dates back to early Unix systems where this mechanism was designed to transfer access rights (file descriptors) between processes, even across privilege boundaries.

### How SCM_RIGHTS Works

When you send a file descriptor via `SCM_RIGHTS`:

1. **Sender side:**
   ```python
   control_sock.sendmsg(
       [b'x'],  # Regular data (can be anything, often just a marker byte)
       [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array('i', [fd]))]
       #  ^socket level      ^control msg type   ^file descriptor(s)
   )
   ```

2. **Kernel action:**
   - Kernel extracts the file descriptor number from the sender's file descriptor table
   - Kernel finds the underlying kernel object (e.g., `struct socket` for a TCP socket)
   - Kernel increments the reference count on that object
   - Kernel prepares the FD to be inserted into the receiver's FD table

3. **Receiver side:**
   ```python
   msg, ancdata, flags, addr = control_sock.recvmsg(1, socket.CMSG_LEN(4))
   for cmsg_level, cmsg_type, cmsg_data in ancdata:
       if cmsg_level == socket.SOL_SOCKET and cmsg_type == socket.SCM_RIGHTS:
           fds.frombytes(cmsg_data)
           received_fd = fds[0]  # New FD number in receiver's process
   ```

4. **Kernel action:**
   - Kernel finds the lowest available FD number in receiver's process
   - Kernel inserts a reference to the kernel object into receiver's FD table
   - Receiver now has a valid FD pointing to the same underlying object

### Key Properties of SCM_RIGHTS

1. **File descriptor numbers change:** FD 5 in process A might become FD 3 in process B
2. **Underlying object stays the same:** Both FDs point to the same kernel socket object
3. **Reference counting:** Kernel increments refcount when passing, decrements when closed
4. **Works across containers:** Container boundaries don't prevent FD passing via Unix sockets
5. **Requires Unix domain socket:** Cannot use SCM_RIGHTS over TCP/UDP

## Kernel Mechanisms for Container Socket Passing

### How Containers Work (Relevant Parts)

Docker containers use Linux namespaces for isolation:
- **PID namespace:** Container has its own PID 1
- **Network namespace:** Container has its own network stack (unless `--network host`)
- **Mount namespace:** Container has its own filesystem view
- **IPC namespace:** Container has its own System V IPC

Critically: **File descriptor tables are per-process, NOT per-namespace**

### Unix Domain Sockets and Namespaces

Unix domain sockets are special:
- They exist in the **filesystem namespace**
- When you mount `/tmp/control.sock` into a container, both processes see the **same inode**
- This creates a communication channel that **crosses namespace boundaries**

### The Socket Passing Mechanism

When passing a TCP socket FD to a containerized process:

```
Host Process                          Container Process
-----------                           -----------------
FD Table:                             FD Table:
  3: stdin                              0: stdin
  4: stdout                             1: stdout
  5: TCP socket (10.0.0.1:80)          2: stderr
  6: Unix socket (/tmp/control.sock)   3: Unix socket (/control.sock)

Kernel Socket Objects:
  Socket Object A: [TCP connection to 192.168.1.100:12345]
    - refcount: 1 (host process FD 5)
    - state: ESTABLISHED
    - recv buffer: [HTTP request data...]
    - send buffer: empty
```

**After sendmsg with SCM_RIGHTS:**

```
Host Process                          Container Process
-----------                           -----------------
FD Table:                             FD Table:
  3: stdin                              0: stdin
  4: stdout                             1: stdout
  5: TCP socket (10.0.0.1:80)          2: stderr
  6: Unix socket (/tmp/control.sock)   3: Unix socket (/control.sock)
                                        4: TCP socket (inherited)

Kernel Socket Objects:
  Socket Object A: [TCP connection to 192.168.1.100:12345]
    - refcount: 2 (host FD 5 + container FD 4)
    - state: ESTABLISHED
    - recv buffer: [HTTP request data...]
    - send buffer: empty
```

**After host closes FD 5:**

```
Host Process                          Container Process
-----------                           -----------------
FD Table:                             FD Table:
  3: stdin                              0: stdin
  4: stdout                             1: stdout
  6: Unix socket (/tmp/control.sock)   2: stderr
                                        3: Unix socket (/control.sock)
                                        4: TCP socket (sole owner now)

Kernel Socket Objects:
  Socket Object A: [TCP connection to 192.168.1.100:12345]
    - refcount: 1 (container FD 4)
    - state: ESTABLISHED
    - recv buffer: [HTTP request data...]
    - send buffer: empty
```

### Network Namespace Considerations

Even though the container has its own network namespace, the **TCP socket object lives in the kernel** and is namespace-agnostic:

- The socket was created in the host's network namespace
- The socket's connection state (ESTABLISHED) is maintained by the kernel
- The container receives a **reference** to this kernel object
- The socket continues to use the host's network namespace for routing
- Data can be read/written from either namespace (whoever holds an FD)

This is different from creating a new socket inside the container, which would use the container's network namespace.

## Implementation Details

### Server Side (Python)

```python
import socket
import array
import subprocess
import tempfile
import os
import uuid

def handle_connection(client_sock, client_addr):
    """Pass TCP socket to a Docker container."""

    # Create Unix domain socket for control channel
    sock_path = f"/tmp/faas-{uuid.uuid4()}.sock"
    control_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    control_sock.bind(sock_path)
    control_sock.listen(1)

    # Start container with volume mount
    container_name = f"faas-{uuid.uuid4()}"
    subprocess.Popen([
        'docker', 'run', '--rm',
        '--name', container_name,
        '-v', f'{sock_path}:/control.sock',
        'faas-handler:latest'
    ])

    # Accept connection from container
    conn, _ = control_sock.accept()

    # Send TCP socket FD over Unix socket
    tcp_fd = client_sock.fileno()
    conn.sendmsg(
        [b'SOCKET'],  # Marker byte(s)
        [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array('i', [tcp_fd]))]
    )

    # Close our reference to the TCP socket
    # Container now owns it
    client_sock.close()
    conn.close()
    control_sock.close()

    # Clean up socket file
    os.unlink(sock_path)
```

### Container Side (Python)

```python
#!/usr/bin/env python3
import socket
import array
from http.server import BaseHTTPRequestHandler
import os

def main():
    # Connect to control socket
    control_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    control_sock.connect('/control.sock')

    # Receive file descriptor via SCM_RIGHTS
    fds = array.array('i')
    msg, ancdata, flags, addr = control_sock.recvmsg(
        1024,  # Buffer size for regular data
        socket.CMSG_LEN(fds.itemsize)  # Ancillary data size
    )

    # Extract FD from ancillary data
    for cmsg_level, cmsg_type, cmsg_data in ancdata:
        if (cmsg_level == socket.SOL_SOCKET and
            cmsg_type == socket.SCM_RIGHTS):
            fds.frombytes(cmsg_data)
            break

    if len(fds) == 0:
        print("Error: No file descriptor received")
        return

    # Reconstruct TCP socket from FD
    tcp_fd = fds[0]
    client_sock = socket.fromfd(tcp_fd, socket.AF_INET, socket.SOCK_STREAM)

    # Get client address for logging
    try:
        client_addr = client_sock.getpeername()
    except OSError:
        client_addr = ('unknown', 0)

    # Handle HTTP request
    FaaSRequestHandler(client_sock, client_addr, None)

    # Clean up
    client_sock.close()
    control_sock.close()

if __name__ == '__main__':
    main()
```

### Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY handler.py /app/handler.py

CMD ["python3", "handler.py"]
```

## Why This Works Across Container Boundaries

### The Key Insight

File descriptors are **per-process**, not per-namespace. The kernel maintains:

1. **Per-process FD tables** (maps FD number → kernel object)
2. **Global kernel objects** (sockets, files, pipes, etc.)
3. **Namespace restrictions** (network, filesystem, etc.)

When you pass an FD via SCM_RIGHTS:
- You're copying a **reference** to a kernel object
- The kernel object itself exists **outside** all namespaces
- Both processes (host and container) can access it via their own FDs

### Analogy

Think of it like shared memory:
- Each process has its own address space (like FD tables)
- But they can both map the same physical memory page (like a kernel socket object)
- Changes by one process are visible to the other (data written/read from socket)

## Advantages Over HTTP Proxy Approach

1. **Zero-copy data path:** Client TCP data flows directly to container
2. **Maintains connection state:** Container has the real TCP socket
3. **Simpler protocol:** No need to parse/rewrite HTTP headers
4. **Lower latency:** No extra network hop
5. **Preserves client address:** Container sees real client IP/port

## Disadvantages and Considerations

1. **Container startup overhead:** ~100-500ms to start container (mitigated with pooling)
2. **Unix socket lifecycle:** Need to create/cleanup socket files
3. **Error handling complexity:** Container crash = hung client connection
4. **Platform-specific:** Requires Unix domain socket support (Linux/macOS)
5. **Security:** Container has direct access to TCP socket (good or bad depending on trust model)

## Alternative: Container Pooling

To reduce startup overhead:

1. Pre-start N containers listening on Unix sockets
2. Assign incoming connections to idle containers round-robin
3. After handling request, container returns to pool
4. Replenish pool when containers exit/crash

This reduces per-request latency from ~500ms to ~1-5ms.

## References

- `man 7 unix` - Unix domain socket documentation
- `man 3 sendmsg` - sendmsg() system call
- `man 3 recvmsg` - recvmsg() system call
- `man 7 socket` - Socket control messages (SCM_RIGHTS)
- Stevens, W. Richard. "Unix Network Programming, Volume 1" - Chapter 15 (Unix Domain Protocols)
