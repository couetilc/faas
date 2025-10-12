# FaaS Runtime: User Experience and Implementation

## Overview

The FaaS runtime provides a base container image that handles the boilerplate of receiving socket file descriptors from the FaaS server, allowing function authors to focus on their application logic.

## TODO: Implementation Roadmap

### Phase 1: Core Infrastructure (Week 1-2)
- [ ] **Modify FaaS server** (`server.py`)
  - [ ] Replace `subprocess.Popen` with Docker container orchestration
  - [ ] Create Unix domain socket per connection (`/tmp/faas-<uuid>.sock`)
  - [ ] Send TCP socket FD via SCM_RIGHTS to container
  - [ ] Handle container lifecycle (start, cleanup, error recovery)
  - [ ] Implement socket file cleanup on container exit

- [ ] **Implement Python runtime** (`faas-init`)
  - [ ] Write init script that receives FD via SCM_RIGHTS
  - [ ] Set `FAAS_CLIENT_FD` environment variable
  - [ ] Exec user command with FD inherited
  - [ ] Add instrumentation for timing measurements

- [ ] **Create base runtime image** (`faas-runtime:latest`)
  - [ ] Dockerfile with Python base + faas-init
  - [ ] Test with minimal handler example
  - [ ] Document user-facing API

### Phase 2: Testing & Validation (Week 2-3)
- [ ] **Build test suite**
  - [ ] Unit tests for SCM_RIGHTS passing
  - [ ] Integration tests for end-to-end request flow
  - [ ] Error handling tests (container crash, socket failures)
  - [ ] Example handlers (Python, Node.js, Go)

- [ ] **Manual testing**
  - [ ] Deploy and run simple functions
  - [ ] Verify socket passing works correctly
  - [ ] Test concurrent requests
  - [ ] Validate error messages and logging

### Phase 3: Benchmarking & Profiling (Week 3-4)
- [ ] **Establish Python baseline**
  - [ ] Implement instrumented minimal handler
  - [ ] Run benchmark suite (100-1000 requests)
  - [ ] Profile with strace, docker stats, perf
  - [ ] Document baseline metrics (cold start, memory, throughput)

- [ ] **Decision point**: Evaluate if Python performance is adequate
  - [ ] If YES: Ship Python runtime, document for future
  - [ ] If NO: Proceed to Phase 4

### Phase 4: Optimization (If Needed)
- [ ] **Implement Go runtime** (alternative to Python)
  - [ ] Port faas-init to Go
  - [ ] Build static binary (~2-3MB)
  - [ ] Create minimal base image

- [ ] **Comparative benchmarking**
  - [ ] Run identical test suite on both runtimes
  - [ ] Calculate performance deltas
  - [ ] Perform cost-benefit analysis
  - [ ] Document decision rationale

### Phase 5: Polish & Documentation
- [ ] **Multi-language examples**
  - [ ] Python handler example with HTTP parsing
  - [ ] Node.js handler example
  - [ ] Go handler example

- [ ] **Documentation**
  - [ ] User guide for writing functions
  - [ ] API reference (`FAAS_CLIENT_FD` contract)
  - [ ] Deployment instructions
  - [ ] Troubleshooting guide

### Future Enhancements (Backlog)
- [ ] Container pooling for reduced cold starts
- [ ] Multi-architecture builds (arm64, amd64)
- [ ] Language-specific runtime variants
- [ ] Observability (metrics, tracing)
- [ ] Resource limits (CPU, memory quotas)

---

## User Experience

### For Function Authors

Function authors work with a simple, familiar interface:

#### 1. Write a Handler (Any Language)

**Python Example:**
```python
#!/usr/bin/env python3
# handler.py
import socket
import os
from http.server import BaseHTTPRequestHandler

class MyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        response = b"Hello from my function!\n"
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain')
        self.send_header('Content-Length', len(response))
        self.end_headers()
        self.wfile.write(response)

def main():
    # FaaS runtime provides socket FD via environment variable
    fd = int(os.environ['FAAS_CLIENT_FD'])
    sock = socket.fromfd(fd, socket.AF_INET, socket.SOCK_STREAM)

    client_addr = sock.getpeername()
    MyHandler(sock, client_addr, None)
    sock.close()

if __name__ == '__main__':
    main()
```

**Node.js Example:**
```javascript
// handler.js
const net = require('net');
const fd = parseInt(process.env.FAAS_CLIENT_FD);

// Construct socket from FD (requires native module or Node 18+)
const socket = new net.Socket({ fd: fd });

socket.on('data', (data) => {
    const response = 'HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n\r\nHello from Node!\n';
    socket.write(response);
    socket.end();
});
```

**Go Example:**
```go
// handler.go
package main

import (
    "fmt"
    "net"
    "net/http"
    "os"
    "strconv"
)

func main() {
    fdStr := os.Getenv("FAAS_CLIENT_FD")
    fd, _ := strconv.Atoi(fdStr)

    // Create net.Conn from FD
    file := os.NewFile(uintptr(fd), "socket")
    conn, _ := net.FileConn(file)
    defer conn.Close()

    // Handle HTTP request
    // (simplified - would need proper HTTP parsing)
    fmt.Fprintf(conn, "HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n\r\nHello from Go!\n")
}
```

#### 2. Create a Dockerfile

```dockerfile
FROM faas-runtime:latest

COPY handler.py /app/handler.py
RUN chmod +x /app/handler.py

CMD ["python3", "/app/handler.py"]
```

#### 3. Build and Deploy

```bash
docker build -t my-function:latest .
```

The FaaS server automatically orchestrates containers built on `faas-runtime`.

### What the Runtime Provides

1. **Automatic socket reception:** Connects to control socket, receives FD via SCM_RIGHTS
2. **Environment variable:** Sets `FAAS_CLIENT_FD` with the file descriptor number
3. **Clean execution:** Execs user's command so no extra process overhead
4. **Error handling:** Logs connection failures, handles missing control socket gracefully

## Implementation Approaches

### Approach 1: Python Implementation (Recommended for Development)

**Advantages:**
- Simple, readable code
- Easy to debug and modify
- Built-in socket handling
- Cross-platform

**Disadvantages:**
- ~50-100MB base image (python:3.11-slim)
- ~30-50ms Python interpreter startup
- Additional memory overhead (~20-30MB per container)

**Implementation:**

```python
#!/usr/bin/env python3
# /faas-init
import socket
import array
import os
import sys

def receive_socket_fd():
    """Connect to control socket and receive TCP socket FD."""
    control_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

    try:
        control_sock.connect('/control.sock')
    except (FileNotFoundError, ConnectionRefusedError) as e:
        print(f"Error: Could not connect to FaaS control socket: {e}", file=sys.stderr)
        sys.exit(1)

    # Receive FD via SCM_RIGHTS
    fds = array.array('i')
    msg, ancdata, flags, addr = control_sock.recvmsg(
        1024,
        socket.CMSG_LEN(fds.itemsize)
    )

    for cmsg_level, cmsg_type, cmsg_data in ancdata:
        if (cmsg_level == socket.SOL_SOCKET and
            cmsg_type == socket.SCM_RIGHTS):
            fds.frombytes(cmsg_data)
            break

    control_sock.close()

    if len(fds) == 0:
        print("Error: No file descriptor received", file=sys.stderr)
        sys.exit(1)

    return fds[0]

def main():
    if len(sys.argv) < 2:
        print("Usage: faas-init <command> [args...]", file=sys.stderr)
        sys.exit(1)

    # Receive socket FD from FaaS server
    fd = receive_socket_fd()

    # Set environment variable for child process
    os.environ['FAAS_CLIENT_FD'] = str(fd)

    # Exec user's command (replaces this process)
    # FD is inherited by exec'd process
    os.execvp(sys.argv[1], sys.argv[1:])

if __name__ == '__main__':
    main()
```

**Dockerfile:**
```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY faas-init /usr/local/bin/faas-init
RUN chmod +x /usr/local/bin/faas-init

ENTRYPOINT ["/usr/local/bin/faas-init"]
CMD ["python3", "-c", "print('No handler specified')"]
```

**Size:** ~120-150MB total

---

### Approach 2: Compiled C Binary (Minimal Overhead)

**Advantages:**
- Tiny binary (~20-50KB)
- Instant startup (<1ms)
- Minimal memory overhead (~1-2MB)
- No runtime dependencies

**Disadvantages:**
- More complex code
- Requires compilation toolchain
- Platform-specific (need multi-arch builds)

**Implementation:**

```c
// faas-init.c
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/socket.h>
#include <sys/un.h>

int receive_socket_fd() {
    int control_sock;
    struct sockaddr_un addr;
    struct msghdr msg;
    struct iovec iov[1];
    char buf[1];

    // Control message buffer for FD
    union {
        struct cmsghdr cm;
        char control[CMSG_SPACE(sizeof(int))];
    } control_un;
    struct cmsghdr *cmptr;

    // Create Unix domain socket
    control_sock = socket(AF_UNIX, SOCK_STREAM, 0);
    if (control_sock < 0) {
        perror("socket");
        return -1;
    }

    // Connect to control socket
    memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    strcpy(addr.sun_path, "/control.sock");

    if (connect(control_sock, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        perror("connect to /control.sock");
        close(control_sock);
        return -1;
    }

    // Prepare to receive FD
    iov[0].iov_base = buf;
    iov[0].iov_len = 1;

    msg.msg_name = NULL;
    msg.msg_namelen = 0;
    msg.msg_iov = iov;
    msg.msg_iovlen = 1;
    msg.msg_control = control_un.control;
    msg.msg_controllen = sizeof(control_un.control);

    // Receive message with FD
    if (recvmsg(control_sock, &msg, 0) <= 0) {
        perror("recvmsg");
        close(control_sock);
        return -1;
    }

    // Extract FD from control message
    cmptr = CMSG_FIRSTHDR(&msg);
    if (cmptr == NULL ||
        cmptr->cmsg_len != CMSG_LEN(sizeof(int)) ||
        cmptr->cmsg_level != SOL_SOCKET ||
        cmptr->cmsg_type != SCM_RIGHTS) {
        fprintf(stderr, "Invalid control message\n");
        close(control_sock);
        return -1;
    }

    int received_fd;
    memcpy(&received_fd, CMSG_DATA(cmptr), sizeof(int));

    close(control_sock);
    return received_fd;
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        fprintf(stderr, "Usage: faas-init <command> [args...]\n");
        return 1;
    }

    // Receive socket FD
    int fd = receive_socket_fd();
    if (fd < 0) {
        fprintf(stderr, "Failed to receive socket FD\n");
        return 1;
    }

    // Set environment variable
    char fd_str[32];
    snprintf(fd_str, sizeof(fd_str), "%d", fd);
    setenv("FAAS_CLIENT_FD", fd_str, 1);

    // Exec user's command (FD is inherited)
    execvp(argv[1], &argv[1]);

    // Only reached if exec fails
    perror("execvp");
    return 1;
}
```

**Build:**
```bash
gcc -static -O2 -o faas-init faas-init.c
strip faas-init  # ~20KB final size
```

**Dockerfile (Alpine):**
```dockerfile
FROM alpine:3.19

COPY faas-init /usr/local/bin/faas-init
RUN chmod +x /usr/local/bin/faas-init

ENTRYPOINT ["/faas-init"]
CMD ["/bin/sh", "-c", "echo 'No handler specified'"]
```

**Size:** ~10-15MB total (Alpine base)

**Dockerfile (Distroless):**
```dockerfile
FROM gcr.io/distroless/static-debian12

COPY faas-init /faas-init

ENTRYPOINT ["/faas-init"]
```

**Size:** ~2-3MB total (distroless)

**Dockerfile (Scratch - absolute minimum):**
```dockerfile
FROM scratch

COPY faas-init /faas-init

ENTRYPOINT ["/faas-init"]
```

**Size:** ~20KB total (just the binary!)

---

### Approach 3: Rust Implementation (Best of Both Worlds)

**Advantages:**
- Small binary (~500KB-2MB)
- Memory safe
- Fast startup (~1-2ms)
- Cross-compilation support
- Better error handling than C

**Disadvantages:**
- Requires Rust toolchain
- Slightly larger than C
- More complex build process

**Implementation:**

```rust
// src/main.rs
use std::os::unix::io::{FromRawFd, RawFd};
use std::os::unix::net::UnixStream;
use std::process::Command;
use std::{env, io, process};

fn receive_socket_fd() -> io::Result<RawFd> {
    use nix::sys::socket::{
        recvmsg, ControlMessageOwned, MsgFlags,
    };
    use std::os::unix::io::AsRawFd;

    // Connect to control socket
    let stream = UnixStream::connect("/control.sock")?;
    let fd = stream.as_raw_fd();

    // Receive FD via SCM_RIGHTS
    let mut iov = [io::IoSliceMut::new(&mut [0u8; 1])];
    let mut cmsg_space = nix::cmsg_space!([RawFd; 1]);

    let msg = recvmsg::<()>(
        fd,
        &mut iov,
        Some(&mut cmsg_space),
        MsgFlags::empty()
    )?;

    // Extract FD from control message
    for cmsg in msg.cmsgs() {
        if let ControlMessageOwned::ScmRights(fds) = cmsg {
            if let Some(&received_fd) = fds.first() {
                return Ok(received_fd);
            }
        }
    }

    Err(io::Error::new(
        io::ErrorKind::InvalidData,
        "No file descriptor received"
    ))
}

fn main() {
    let args: Vec<String> = env::args().collect();

    if args.len() < 2 {
        eprintln!("Usage: faas-init <command> [args...]");
        process::exit(1);
    }

    // Receive socket FD
    let fd = match receive_socket_fd() {
        Ok(fd) => fd,
        Err(e) => {
            eprintln!("Error receiving socket FD: {}", e);
            process::exit(1);
        }
    };

    // Set environment variable
    env::set_var("FAAS_CLIENT_FD", fd.to_string());

    // Exec user's command
    let err = Command::new(&args[1])
        .args(&args[2..])
        .exec();

    // Only reached if exec fails
    eprintln!("Failed to exec: {}", err);
    process::exit(1);
}
```

**Cargo.toml:**
```toml
[package]
name = "faas-init"
version = "0.1.0"
edition = "2021"

[dependencies]
nix = { version = "0.27", features = ["net"] }

[profile.release]
opt-level = 'z'     # Optimize for size
lto = true          # Link-time optimization
codegen-units = 1   # Better optimization
strip = true        # Strip symbols
```

**Build:**
```bash
cargo build --release
# Result: target/release/faas-init (~500KB)
```

**Dockerfile:**
```dockerfile
FROM scratch

COPY target/release/faas-init /faas-init

ENTRYPOINT ["/faas-init"]
```

**Size:** ~500KB total

---

### Approach 4: Go Implementation (Good Balance)

**Advantages:**
- Single static binary (~2-5MB)
- Fast startup (~2-5ms)
- Easy cross-compilation
- Good standard library

**Disadvantages:**
- Larger binary than C/Rust
- Slight runtime overhead (GC, goroutine scheduler)

**Implementation:**

```go
// main.go
package main

import (
    "fmt"
    "net"
    "os"
    "os/exec"
    "syscall"
)

func receiveSocketFD() (int, error) {
    // Connect to Unix domain socket
    conn, err := net.Dial("unix", "/control.sock")
    if err != nil {
        return -1, fmt.Errorf("connect: %w", err)
    }
    defer conn.Close()

    // Get underlying file descriptor
    unixConn := conn.(*net.UnixConn)
    file, err := unixConn.File()
    if err != nil {
        return -1, fmt.Errorf("get file: %w", err)
    }
    defer file.Close()

    // Receive FD via SCM_RIGHTS
    buf := make([]byte, 1)
    oob := make([]byte, syscall.CmsgSpace(4))

    _, oobn, _, _, err := syscall.Recvmsg(
        int(file.Fd()),
        buf,
        oob,
        0,
    )
    if err != nil {
        return -1, fmt.Errorf("recvmsg: %w", err)
    }

    // Parse control message
    msgs, err := syscall.ParseSocketControlMessage(oob[:oobn])
    if err != nil {
        return -1, fmt.Errorf("parse control msg: %w", err)
    }

    if len(msgs) == 0 {
        return -1, fmt.Errorf("no control messages received")
    }

    fds, err := syscall.ParseUnixRights(&msgs[0])
    if err != nil {
        return -1, fmt.Errorf("parse unix rights: %w", err)
    }

    if len(fds) == 0 {
        return -1, fmt.Errorf("no file descriptors received")
    }

    return fds[0], nil
}

func main() {
    if len(os.Args) < 2 {
        fmt.Fprintln(os.Stderr, "Usage: faas-init <command> [args...]")
        os.Exit(1)
    }

    // Receive socket FD
    fd, err := receiveSocketFD()
    if err != nil {
        fmt.Fprintf(os.Stderr, "Error: %v\n", err)
        os.Exit(1)
    }

    // Set environment variable
    os.Setenv("FAAS_CLIENT_FD", fmt.Sprintf("%d", fd))

    // Exec user's command
    binary, err := exec.LookPath(os.Args[1])
    if err != nil {
        fmt.Fprintf(os.Stderr, "Command not found: %v\n", err)
        os.Exit(1)
    }

    err = syscall.Exec(binary, os.Args[1:], os.Environ())
    fmt.Fprintf(os.Stderr, "Exec failed: %v\n", err)
    os.Exit(1)
}
```

**Build:**
```bash
CGO_ENABLED=0 go build -ldflags="-s -w" -o faas-init main.go
# Result: ~2-3MB
```

**Dockerfile:**
```dockerfile
FROM scratch

COPY faas-init /faas-init

ENTRYPOINT ["/faas-init"]
```

**Size:** ~2-3MB total

---

## Size and Performance Comparison

| Approach | Binary Size | Base Image | Total Size | Startup Time | Memory Overhead |
|----------|-------------|------------|------------|--------------|-----------------|
| Python   | N/A         | python:slim | ~120MB     | ~30-50ms     | ~20-30MB        |
| C (Alpine) | ~20KB     | alpine     | ~15MB      | <1ms         | ~1-2MB          |
| C (Scratch) | ~20KB    | scratch    | ~20KB      | <1ms         | ~1-2MB          |
| Rust     | ~500KB      | scratch    | ~500KB     | ~1-2ms       | ~1-3MB          |
| Go       | ~2-3MB      | scratch    | ~2-3MB     | ~2-5ms       | ~5-10MB         |

## Recommendations

### For Development and Prototyping
**Use Python implementation:**
- Easy to modify and debug
- Quick iteration cycle
- Good error messages
- Total size not critical in development

### For Production (Minimal Overhead)
**Use Rust or C implementation:**
- Sub-millisecond startup
- Minimal memory footprint
- Can use `scratch` base image
- Ideal for high-density FaaS workloads

### For Production (Easy Maintenance)
**Use Go implementation:**
- Good balance of size and simplicity
- Easy to build and maintain
- Static binary, no dependencies
- Fast enough for most workloads

## Multi-Language Runtime Strategy

Provide language-specific base images that include both the init runtime and language tooling:

```
faas-runtime:latest          → Python-based init + Python 3.11
faas-runtime:slim            → C-based init + minimal base
faas-runtime:python          → C-based init + Python 3.11
faas-runtime:node            → C-based init + Node.js 20
faas-runtime:go              → Minimal (Go compiles to static binary)
faas-runtime:rust            → Minimal (Rust compiles to static binary)
```

Function authors choose the appropriate base for their language.

## Future Optimizations

1. **Pre-warmed containers:** Keep pool of initialized containers to eliminate startup latency
2. **Shared base layers:** Optimize Dockerfile layers for maximum reuse across functions
3. **Custom init binary per-function:** Bundle minimal init directly into user's image
4. **Kernel bypass:** Use io_uring for even lower latency socket operations (Linux 5.19+)

## Profiling and Benchmarking: Choosing the Right Runtime

### Overview

Selecting the right runtime implementation requires balancing **ease of development** against **performance requirements**. This section describes a methodical approach to profiling runtime overhead and making data-driven language choices.

### The Decision Framework

```
Development Phase:
  Choose Python → Fast iteration, easy debugging
  ↓
  Implement working system
  ↓
  Profile and establish baseline metrics
  ↓
Performance Adequate? ──YES──> Ship Python runtime
  ↓ NO
  Identify bottlenecks
  ↓
  Implement optimized version (Go/Rust/C)
  ↓
  Benchmark and compare
  ↓
  Calculate cost/benefit of optimization
  ↓
  Make informed decision
```

### Key Metrics to Measure

#### 1. **Cold Start Latency** (Most Critical for FaaS)
Time from container start to first request handled.

**Components:**
- Container creation time
- Init binary startup
- Connect to control socket
- Receive FD via SCM_RIGHTS
- Exec user command
- User code initialization

**Target:** <100ms for acceptable UX, <10ms for high-performance

#### 2. **Runtime Overhead**
CPU and memory consumed by init process before exec.

**Components:**
- Language runtime initialization (interpreter, VM, etc.)
- Socket operation cost
- Memory allocation

**Target:** <5% CPU overhead, <10MB memory

#### 3. **Throughput**
Requests per second per core.

**Measurement:** Use load testing with multiple concurrent connections

**Target:** Depends on workload, but runtime should not be bottleneck

#### 4. **Resource Efficiency**
Cost per million requests (CPU + memory).

**Calculation:**
```
Cost = (CPU_seconds × CPU_price) + (Memory_GB_seconds × Memory_price)
```

**Target:** Minimize cost while maintaining acceptable latency

### Benchmarking Methodology

#### Phase 1: Establish Python Baseline

**1. Create Minimal Test Handler**

Create a no-op handler that measures only runtime overhead:

```python
# minimal_handler.py
import socket
import os
import sys
import time

start_time = time.perf_counter()

# This is where user code would start
fd = int(os.environ['FAAS_CLIENT_FD'])
sock = socket.fromfd(fd, socket.AF_INET, socket.SOCK_STREAM)

# Send minimal HTTP response
response = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK"
sock.sendall(response)
sock.close()

end_time = time.perf_counter()

# Log timing to stderr (won't interfere with response)
print(f"Handler time: {(end_time - start_time)*1000:.2f}ms", file=sys.stderr)
```

**2. Instrument Init Script**

Add timing to faas-init:

```python
#!/usr/bin/env python3
import socket
import array
import os
import sys
import time

start_time = time.perf_counter()

def receive_socket_fd():
    """Connect to control socket and receive TCP socket FD."""
    connect_start = time.perf_counter()

    control_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    control_sock.connect('/control.sock')

    connect_time = time.perf_counter() - connect_start

    # Receive FD via SCM_RIGHTS
    recv_start = time.perf_counter()
    fds = array.array('i')
    msg, ancdata, flags, addr = control_sock.recvmsg(
        1024,
        socket.CMSG_LEN(fds.itemsize)
    )

    for cmsg_level, cmsg_type, cmsg_data in ancdata:
        if (cmsg_level == socket.SOL_SOCKET and
            cmsg_type == socket.SCM_RIGHTS):
            fds.frombytes(cmsg_data)
            break

    control_sock.close()
    recv_time = time.perf_counter() - recv_start

    print(f"[faas-init] Connect: {connect_time*1000:.2f}ms, Recv: {recv_time*1000:.2f}ms",
          file=sys.stderr)

    return fds[0]

def main():
    fd = receive_socket_fd()
    os.environ['FAAS_CLIENT_FD'] = str(fd)

    init_time = time.perf_counter() - start_time
    print(f"[faas-init] Total init time: {init_time*1000:.2f}ms", file=sys.stderr)

    # Exec user's command
    os.execvp(sys.argv[1], sys.argv[1:])

if __name__ == '__main__':
    main()
```

**3. Measure End-to-End Latency**

Use a simple load testing tool:

```bash
# Single request measurement
time curl http://10.0.0.1:80/

# Multiple requests with timing
for i in {1..100}; do
    (time curl -s http://10.0.0.1:80/ > /dev/null) 2>&1 | grep real
done | awk '{sum+=$2; count++} END {print "Average:", sum/count "ms"}'
```

**4. Profile with System Tools**

```bash
# CPU profiling
docker stats <container_id>

# Memory profiling
docker exec <container_id> ps aux

# System call tracing (measure overhead of SCM_RIGHTS)
strace -T -e trace=socket,connect,sendmsg,recvmsg,execve \
    python3 faas-init python3 minimal_handler.py

# Python-specific profiling
python3 -m cProfile -o profile.stats faas-init python3 minimal_handler.py
```

**5. Collect Baseline Metrics**

Run benchmarks and record:

```
Python Baseline Results:
========================
Cold start latency (p50): _____ ms
Cold start latency (p99): _____ ms
Init overhead: _____ ms
Memory overhead: _____ MB
CPU usage (init phase): _____ %
Container image size: _____ MB
```

#### Phase 2: Implement and Benchmark Go Runtime

**1. Create Equivalent Go Init Binary**

Use the implementation from "Approach 4" section above.

**2. Add Instrumentation**

```go
package main

import (
    "fmt"
    "net"
    "os"
    "os/exec"
    "syscall"
    "time"
)

func receiveSocketFD() (int, error) {
    start := time.Now()

    conn, err := net.Dial("unix", "/control.sock")
    if err != nil {
        return -1, fmt.Errorf("connect: %w", err)
    }
    defer conn.Close()

    connectTime := time.Since(start)

    // ... (FD receiving code) ...

    recvTime := time.Since(start) - connectTime

    fmt.Fprintf(os.Stderr, "[faas-init-go] Connect: %.2fms, Recv: %.2fms\n",
        connectTime.Seconds()*1000, recvTime.Seconds()*1000)

    return fds[0], nil
}

func main() {
    start := time.Now()

    fd, err := receiveSocketFD()
    if err != nil {
        fmt.Fprintf(os.Stderr, "Error: %v\n", err)
        os.Exit(1)
    }

    os.Setenv("FAAS_CLIENT_FD", fmt.Sprintf("%d", fd))

    initTime := time.Since(start)
    fmt.Fprintf(os.Stderr, "[faas-init-go] Total init time: %.2fms\n",
        initTime.Seconds()*1000)

    // Exec user's command
    binary, _ := exec.LookPath(os.Args[1])
    syscall.Exec(binary, os.Args[1:], os.Environ())
}
```

**3. Run Same Benchmark Suite**

Use identical test methodology as Python baseline.

**4. Collect Go Metrics**

```
Go Implementation Results:
==========================
Cold start latency (p50): _____ ms
Cold start latency (p99): _____ ms
Init overhead: _____ ms
Memory overhead: _____ MB
CPU usage (init phase): _____ %
Container image size: _____ MB
Binary size: _____ MB
```

#### Phase 3: Comparative Analysis

**1. Calculate Deltas**

```
Metric                    | Python  | Go      | Delta    | % Change
--------------------------|---------|---------|----------|----------
Cold start (p50)          | 45ms    | 3ms     | -42ms    | -93%
Cold start (p99)          | 78ms    | 5ms     | -73ms    | -94%
Init overhead             | 35ms    | 1.5ms   | -33.5ms  | -96%
Memory (init)             | 25MB    | 3MB     | -22MB    | -88%
Image size                | 125MB   | 3MB     | -122MB   | -98%
Binary size               | N/A     | 2.8MB   | N/A      | N/A
Development time          | 2 hours | 6 hours | +4 hours | +200%
Code complexity (LoC)     | 40      | 80      | +40      | +100%
```

**2. Cost-Benefit Analysis**

**For high-volume workload (1M requests/day):**

```
Python runtime:
  - Average latency: 50ms
  - Memory per container: 25MB
  - Container density: 40 per host (1GB RAM)
  - Required hosts: 25 (to handle concurrency)
  - Monthly cost: $1,500 (AWS t3.medium × 25)

Go runtime:
  - Average latency: 5ms
  - Memory per container: 3MB
  - Container density: 330 per host (1GB RAM)
  - Required hosts: 3 (to handle concurrency)
  - Monthly cost: $180 (AWS t3.medium × 3)

Savings: $1,320/month ($15,840/year)
Development cost: 4 hours × $150/hour = $600
ROI: 18 days
```

**For low-volume workload (1K requests/day):**

```
Python runtime:
  - User-perceivable latency: Acceptable
  - Infrastructure: Minimal (1 host)
  - Monthly cost: $60

Go runtime:
  - User-perceivable latency: Slightly better
  - Infrastructure: Minimal (1 host)
  - Monthly cost: $60

Savings: $0/month
Development cost: $600
ROI: Never
```

**3. Decision Matrix**

| Factor | Weight | Python | Go | Weighted Score |
|--------|--------|--------|----|----|
| Development speed | 0.3 | 10 | 6 | Python: 3.0, Go: 1.8 |
| Cold start latency | 0.25 | 3 | 10 | Python: 0.75, Go: 2.5 |
| Memory efficiency | 0.2 | 3 | 10 | Python: 0.6, Go: 2.0 |
| Maintainability | 0.15 | 9 | 7 | Python: 1.35, Go: 1.05 |
| Binary size | 0.1 | 2 | 9 | Python: 0.2, Go: 0.9 |
| **Total** | 1.0 | | | **Python: 5.9, Go: 8.25** |

**Interpretation:**
- **Early stage / low volume:** Python wins (faster iteration)
- **Production / high volume:** Go wins (better resource efficiency)
- **Enterprise / long-term:** Go wins (lower operational costs)

### Tools and Techniques

#### Linux perf for Detailed Profiling

```bash
# Profile container startup
perf record -g -p <container_pid> -- sleep 5
perf report

# Generate flame graph
perf script | stackcollapse-perf.pl | flamegraph.pl > flamegraph.svg
```

#### Docker Stats for Resource Monitoring

```bash
# Real-time monitoring
docker stats --no-stream --format \
    "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}"

# Continuous monitoring
docker stats --format "{{.Name}},{{.CPUPerc}},{{.MemUsage}}" >> metrics.csv
```

#### SystemTap for Kernel-Level Tracing

```bash
# Trace SCM_RIGHTS operations
stap -e 'probe kernel.function("scm_detach_fds") {
    printf("SCM_RIGHTS transfer: PID %d\n", pid())
}'
```

#### Custom Benchmark Harness

```python
#!/usr/bin/env python3
# benchmark_runtime.py
import subprocess
import time
import statistics

def run_single_request():
    """Run single request and measure end-to-end latency."""
    start = time.perf_counter()

    subprocess.run([
        'curl', '-s', 'http://10.0.0.1:80/'
    ], capture_output=True, check=True)

    return (time.perf_counter() - start) * 1000  # ms

def benchmark(n_requests=100):
    """Run benchmark suite."""
    print(f"Running {n_requests} requests...")

    latencies = []
    for i in range(n_requests):
        latency = run_single_request()
        latencies.append(latency)

        if (i + 1) % 10 == 0:
            print(f"  Progress: {i+1}/{n_requests}")

    print(f"\nResults:")
    print(f"  Mean:   {statistics.mean(latencies):.2f}ms")
    print(f"  Median: {statistics.median(latencies):.2f}ms")
    print(f"  P95:    {sorted(latencies)[int(n_requests*0.95)]:.2f}ms")
    print(f"  P99:    {sorted(latencies)[int(n_requests*0.99)]:.2f}ms")
    print(f"  Min:    {min(latencies):.2f}ms")
    print(f"  Max:    {max(latencies):.2f}ms")

if __name__ == '__main__':
    benchmark(100)
```

### Pedagogical Takeaways

#### 1. **Always Measure First**
Don't optimize prematurely. Python might be "fast enough" for your workload.

#### 2. **Consider Total Cost of Ownership**
Faster runtime ≠ better choice. Factor in:
- Development time
- Maintenance burden
- Operational complexity
- Team expertise

#### 3. **Performance is a Feature**
Like any feature, it has a cost. Determine if users are willing to pay for it.

#### 4. **Optimize the Right Thing**
Profile to find actual bottlenecks. Runtime overhead might be <1% of total latency if user code is slow.

#### 5. **Incremental Optimization**
1. Start with simplest implementation (Python)
2. Measure and identify bottlenecks
3. Optimize specific hot paths
4. Re-measure to confirm improvement
5. Repeat until performance adequate

#### 6. **Context Matters**
- **Internal tool:** Python probably fine
- **User-facing API:** Go might be necessary
- **High-frequency trading:** C/Rust required
- **Prototype:** Definitely Python

### Real-World Example: AWS Lambda Cold Starts

AWS Lambda demonstrates these trade-offs:

| Runtime | Cold Start (p50) | Popularity |
|---------|------------------|------------|
| Python 3.11 | ~150ms | Very High |
| Node.js 20 | ~120ms | Very High |
| Go 1.x | ~80ms | Medium |
| Java 21 | ~600ms | High (despite worse cold start) |
| Rust | ~5ms | Low (despite best cold start) |

**Lesson:** Developer experience often trumps raw performance. Python remains most popular despite slower cold starts.

### Recommended Workflow for This Project

```bash
# Week 1: Python implementation
Implement Python runtime
Build test suite
Deploy and iterate rapidly
Gather user feedback

# Week 2: Establish baseline
Run benchmarks
Profile overhead
Document findings
Calculate acceptable thresholds

# Week 3: Decision point
IF (Python meets requirements):
    Ship Python runtime
    Document profiling for future reference
ELSE:
    Implement Go runtime
    Run comparative benchmarks
    Make data-driven decision

# Week 4: Optimization (if needed)
Implement optimized runtime
Validate performance improvements
Document trade-offs
Provide both options (let users choose)
```

### Conclusion

The choice between Python and Go (or any language) should be driven by:

1. **Measured performance data**, not assumptions
2. **Business requirements**, not theoretical maximums
3. **Team capabilities**, not language popularity
4. **Total cost**, not just runtime speed

Start with Python. Measure. Optimize only if necessary. This approach maximizes learning while delivering value quickly.

---

## Implementation Priority

1. **Phase 1:** Python implementation (ease of development)
2. **Phase 2:** Establish baseline metrics and profiling methodology
3. **Phase 3:** Decision point - evaluate if optimization needed
4. **Phase 4:** (If needed) Go/Rust implementation with comparative benchmarks
5. **Phase 5:** Multi-language base images
6. **Phase 6:** Advanced optimizations (container pooling, etc.)
