# FaaS with containerd Implementation

## Overview

This document describes the containerd-based implementation of the FaaS platform, where users submit Docker images and receive dedicated IP addresses for their functions.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│ User Machine                                            │
│                                                         │
│  faas CLI                                              │
│    ↓                                                    │
│  Docker (local)                                        │
│    ↓                                                    │
│  Export image tarball                                  │
│    ↓                                                    │
│  HTTP POST to faasd                                    │
└────────────────────────┬────────────────────────────────┘
                         │ HTTP
                         ↓
┌─────────────────────────────────────────────────────────┐
│ Service Provider Machine                                │
│                                                         │
│  ┌──────────────────────────────────────────────────┐  │
│  │ faasd (single Python process)                    │  │
│  │                                                  │  │
│  │  • Control API (:8080)                          │  │
│  │  • Image registry (in-memory + disk)            │  │
│  │  • IP allocator                                 │  │
│  │  • HTTP listeners (select-based multiplexing)   │  │
│  │  • Container spawner                            │  │
│  └────────────────────┬─────────────────────────────┘  │
│                       ↓                                 │
│              ┌─────────────────┐                        │
│              │   containerd    │                        │
│              │   (daemon)      │                        │
│              │                 │                        │
│              │  • Image store  │                        │
│              │  • Container    │                        │
│              │    lifecycle    │                        │
│              └────────┬────────┘                        │
│                       ↓                                 │
│              ┌─────────────────┐                        │
│              │      runc       │                        │
│              │                 │                        │
│              │  • Namespaces   │                        │
│              │  • SCM_RIGHTS   │                        │
│              └─────────────────┘                        │
└─────────────────────────────────────────────────────────┘
```

## User Workflow

```bash
# 1. Build Docker image locally
docker build -t my-handler .

# 2. Publish to FaaS platform
faas new my-handler
# → Exports image as tarball
# → Uploads to faasd
# → faasd imports into containerd
# → faasd allocates IP address
# → Returns: {"name": "my-handler", "ip": "10.0.0.10"}

# 3. Query assigned IP
faas ip my-handler
# → 10.0.0.10

# 4. List all deployments
faas list
# → IMAGE           IP              STATUS
#   my-handler      10.0.0.10       active
#   api-service     10.0.0.11       active

# 5. Make requests to the function
curl http://10.0.0.10/
# → Request handled by containerized function
```

## Design Decisions

### 1. No Separate Container Registry

**Decision:** Use containerd's built-in image store as the registry.

**Rationale:**
- Simpler architecture - one less service to manage
- containerd already handles image storage efficiently
- No need for Docker Registry, Harbor, etc.
- Images imported directly via containerd API

**How it works:**
```python
# Import OCI tarball directly into containerd
containerd.images.import(tar_path)
# Image now stored in /var/lib/containerd/io.containerd.content.v1.content/
```

### 2. One IP Per Image

**Decision:** Each deployed image gets a unique IP address.

**Rationale:**
- Simple routing - no need for hostname/path routing
- Isolation - each function has its own network endpoint
- IP range: 10.0.0.0/24 provides 254 usable addresses

**IP Allocation:**
```python
def allocate_ip():
    used_ips = {metadata['ip'] for metadata in registry.values()}
    for i in range(10, 255):
        ip = f"10.0.0.{i}"
        if ip not in used_ips:
            return ip
    raise Exception("No available IPs")
```

### 3. Container-per-Request Model

**Decision:** Spawn a new container for each incoming HTTP request.

**Rationale:**
- Stateless - each request gets clean environment
- Isolation - requests cannot interfere with each other
- Simple lifecycle - container exits when request completes
- Security - no state persists between requests

**Flow:**
1. HTTP request arrives on allocated IP
2. faasd spawns container from image
3. Container handles request via passed socket
4. Container exits
5. faasd cleans up

**Future optimization:** Container pooling/warm containers for reduced latency

### 4. Handler Contract

**Decision:** User-provided images must handle socket FD from `/control.sock`.

**Contract:**
- Container must connect to Unix socket at `/control.sock`
- Receive TCP socket FD via SCM_RIGHTS
- Handle HTTP request on that socket
- Exit when done

**Example handler (Python):**
```python
import socket
import array
import os

# Connect to control socket
control_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
control_sock.connect('/control.sock')

# Receive TCP socket FD
fds = array.array('i')
msg, ancdata, flags, addr = control_sock.recvmsg(
    1024,
    socket.CMSG_SPACE(array.array('i', [0]).itemsize)
)

for level, type, data in ancdata:
    if level == socket.SOL_SOCKET and type == socket.SCM_RIGHTS:
        fds.frombytes(data)

tcp_fd = fds[0]
client_sock = socket.fromfd(tcp_fd, socket.AF_INET, socket.SOCK_STREAM)

# Handle HTTP request
response = b"HTTP/1.1 200 OK\r\n\r\nHello World!"
client_sock.sendall(response)
client_sock.close()
```

### 5. Network Isolation

**Decision:** Full network namespace isolation with SCM_RIGHTS socket passing.

**Rationale:**
- Security - untrusted user code cannot create network connections
- Container only has access to the passed socket FD
- Socket created in host namespace, FD passed to container namespace
- Container isolated but functional

**Container configuration:**
```json
{
  "linux": {
    "namespaces": [
      {"type": "pid"},      // Process isolation
      {"type": "mount"},    // Filesystem isolation
      {"type": "network"},  // Network isolation (!)
      {"type": "ipc"},      // IPC isolation
      {"type": "uts"}       // Hostname isolation
    ]
  }
}
```

**Key insight:** Passed socket FD works even though container is in separate network namespace, because the socket was created in the host's network namespace and the FD is just a reference to the kernel socket object.

## faasd Components

### 1. Control API

HTTP server listening on port 8080 for management operations.

**Endpoints:**

```
POST /api/new
  Headers: X-Image-Name: <name>
  Body: OCI image tarball
  Response: {"name": "<name>", "ip": "10.0.0.X"}

  Imports image into containerd, allocates IP, starts listener

GET /api/ip/<name>
  Response: {"name": "<name>", "ip": "10.0.0.X"}

  Returns allocated IP for image

GET /api/list
  Response: {
    "<name>": {"ip": "10.0.0.X", "image_ref": "..."},
    ...
  }

  Lists all deployed images
```

### 2. Image Registry

In-memory + disk-persisted mapping of image names to metadata.

**File:** `/var/lib/faasd/registry.json`

**Structure:**
```json
{
  "my-handler": {
    "ip": "10.0.0.10",
    "image_ref": "my-handler:latest"
  },
  "api-service": {
    "ip": "10.0.0.11",
    "image_ref": "api-service:latest"
  }
}
```

**Operations:**
- Load from disk on startup
- Save to disk on changes
- Allocate next available IP
- Register new image

### 3. HTTP Request Handlers

Multi-IP listener using select-based socket multiplexing.

**Implementation:**
```python
server_sockets = []  # List of listening sockets
socket_map = {}      # socket → image_ref

# Main event loop
while True:
    readable, _, _ = select.select(server_sockets, [], [])

    for sock in readable:
        client_sock, addr = sock.accept()
        image_ref = socket_map[sock]

        # Handle in thread to avoid blocking select
        threading.Thread(
            target=handle_request,
            args=(client_sock, addr, image_ref),
            daemon=True
        ).start()
```

**Benefits:**
- Single-threaded select loop (efficient)
- One socket per allocated IP
- Scales to hundreds of IPs
- Request handling in threads (parallelism)

### 4. Container Spawner

Creates and manages container lifecycle per request.

**Flow:**
```python
def handle_request(client_sock, client_addr, image_ref):
    container_id = f"faas-{uuid.uuid4()}"
    sock_path = f"/tmp/{container_id}.sock"

    # 1. Create control socket
    control_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    control_sock.bind(sock_path)
    control_sock.listen(1)

    # 2. Spawn container via containerd
    container = containerd.create_container(
        container_id,
        image_ref,
        mounts=[{
            'source': sock_path,
            'destination': '/control.sock',
            'type': 'bind'
        }]
    )

    task = container.start()

    # 3. Wait for container to connect
    control_sock.settimeout(5.0)
    conn, _ = control_sock.accept()

    # 4. Pass TCP socket FD via SCM_RIGHTS
    tcp_fd = client_sock.fileno()
    conn.sendmsg(
        [b'SOCKET'],
        [(socket.SOL_SOCKET, socket.SCM_RIGHTS,
          array.array('i', [tcp_fd]))]
    )

    # 5. Close our references
    client_sock.close()
    conn.close()
    control_sock.close()

    # 6. Wait for container to finish
    task.wait()

    # 7. Cleanup
    container.delete()
    os.unlink(sock_path)
```

### 5. Containerd Client

Wrapper around containerd's gRPC API.

**Operations:**
- Import OCI image tarball
- Create container with mounts
- Start container task
- Wait for task completion
- Delete container

**gRPC services used:**
```python
from containerd.services.images.v1 import images_pb2_grpc
from containerd.services.containers.v1 import containers_pb2_grpc
from containerd.services.tasks.v1 import tasks_pb2_grpc

# Connect to containerd
channel = grpc.insecure_channel('unix:///run/containerd/containerd.sock')
images_client = images_pb2_grpc.ImagesStub(channel)
containers_client = containers_pb2_grpc.ContainersStub(channel)
tasks_client = tasks_pb2_grpc.TasksStub(channel)
```

## Why containerd vs Docker vs runc?

### Docker
**What it is:** Full container platform with daemon, CLI, registry, networking, volumes, etc.

**Cons for our use case:**
- Heavy - includes features we don't need
- Requires Docker daemon running
- CLI-based, not programmatic
- Images stored in Docker-specific format

**Verdict:** Too heavy, not needed

### runc
**What it is:** Low-level OCI runtime - just runs containers from bundles

**Pros:**
- Minimal overhead
- Direct control
- No daemon

**Cons:**
- Manual image management (extract layers, create rootfs)
- No image registry
- No lifecycle management
- More work for us

**Verdict:** Too low-level, would reinvent containerd

### containerd
**What it is:** High-level container runtime with image management

**Pros:**
- ✅ Image import/export (handles OCI tarballs)
- ✅ Image storage (content-addressable store)
- ✅ Layer management (deduplication, caching)
- ✅ Container lifecycle (create, start, stop, delete)
- ✅ gRPC API (programmatic control)
- ✅ Used by Kubernetes, Docker (battle-tested)
- ✅ Manages runc for us

**Cons:**
- Requires daemon (but lightweight)
- More complex than raw runc

**Verdict:** Perfect fit - handles image management without Docker's weight

## Container vs Image vs Rootfs - Clarified

### Image (in containerd)
- Stored in `/var/lib/containerd/io.containerd.content.v1.content/`
- Consists of layers (blobs)
- Metadata (manifest, config)
- Can be shared across multiple containers
- Imported once, used many times

### Rootfs
- Unpacked filesystem from image layers
- Created by containerd when starting container
- Uses overlayfs (base layers + writable layer)
- One per container instance
- Deleted when container deleted

### Container
- Running instance of an image
- Has own namespaces (PID, network, mount, etc.)
- Has own rootfs (overlay of image layers)
- Ephemeral - created per request, deleted after

**Example:**
```
Image: my-handler:latest
  → stored once in containerd

Request 1 arrives:
  → containerd creates Container A
  → Container A gets rootfs (overlay of image layers)
  → Container A runs, handles request, exits
  → rootfs deleted

Request 2 arrives:
  → containerd creates Container B (from same image!)
  → Container B gets new rootfs (overlay of same image layers)
  → Container B runs, handles request, exits
  → rootfs deleted
```

**No multiple rootfs needed** - containerd handles this with overlayfs automatically.

## Implementation Phases

### Phase 1: containerd Setup ✅
**Goal:** Get containerd running and test basic operations

**Steps:**
1. Install containerd: `sudo apt-get install containerd`
2. Start daemon: `sudo systemctl start containerd`
3. Test import: `sudo ctr images import alpine.tar`
4. Test run: `sudo ctr run --rm alpine:latest test echo hello`

**Success criteria:** Can import and run containers with `ctr` CLI

---

### Phase 2: faasd Core Structure
**Goal:** Basic Python skeleton with containerd integration

**Components:**
- Registry (load/save JSON)
- ContainerdClient (gRPC wrapper)
- Main loop structure

**Files:**
- `faasd.py` - Main daemon
- `/var/lib/faasd/registry.json` - Persistent registry

**Success criteria:** faasd starts, connects to containerd, loads registry

---

### Phase 3: Image Import API
**Goal:** Accept image tarballs via HTTP

**Endpoint:** `POST /api/new`

**Flow:**
1. Receive tarball in HTTP body
2. Save to temp file
3. Import into containerd via gRPC
4. Allocate IP
5. Register in registry
6. Return IP to client

**Test:**
```bash
docker save alpine:latest -o alpine.tar
curl -X POST http://localhost:8080/api/new \
  -H "X-Image-Name: test" \
  --data-binary @alpine.tar
# → {"name": "test", "ip": "10.0.0.10"}
```

**Success criteria:** Image imported, IP allocated, registry persisted

---

### Phase 4: Dynamic HTTP Listeners
**Goal:** Listen on allocated IPs

**Implementation:**
- select-based multiplexing
- One socket per allocated IP
- Thread-per-request handling

**Test:**
```bash
# After publishing test image to 10.0.0.10
sudo ip addr add 10.0.0.10/24 dev lo
curl http://10.0.0.10/
# Should accept connection (even if no response yet)
```

**Success criteria:** faasd accepts connections on allocated IPs

---

### Phase 5: Container Spawning + SCM_RIGHTS
**Goal:** Spawn containers and pass sockets

**Components:**
- Create Unix control socket
- Spawn container with mount
- Accept connection from container
- Pass TCP socket FD via SCM_RIGHTS
- Wait for container completion
- Cleanup

**Test:**
```bash
# Build test handler image
docker build -t test-handler .
faas new test-handler
# → "10.0.0.10"

curl http://10.0.0.10/
# → "Hello from test handler!"
```

**Success criteria:** End-to-end request → container → response

---

### Phase 6: faas Client CLI
**Goal:** User-friendly CLI tool

**Commands:**
```bash
faas new <image>      # Export and upload image
faas ip <image>       # Query allocated IP
faas list             # List all deployments
faas delete <image>   # Remove deployment (future)
faas logs <image>     # Stream logs (future)
```

**Implementation:**
```python
#!/usr/bin/env python3
import subprocess, requests, sys

FAASD_API = "http://faasd:8080"

def new(image):
    # Export Docker image
    tar = f"/tmp/{image}.tar"
    subprocess.run(['docker', 'save', image, '-o', tar])

    # Upload
    with open(tar, 'rb') as f:
        resp = requests.post(
            f"{FAASD_API}/api/new",
            headers={'X-Image-Name': image},
            data=f
        )

    print(resp.json()['ip'])
```

---

## Production Considerations

### Security
- [ ] Authentication for Control API (API keys, mTLS)
- [ ] Authorization (per-user image quotas)
- [ ] Container resource limits (CPU, memory via cgroups)
- [ ] Seccomp/AppArmor profiles for containers
- [ ] Read-only rootfs enforcement
- [ ] Drop capabilities

### Scalability
- [ ] Container pooling (pre-warmed containers)
- [ ] Multi-host deployment (distributed faasd)
- [ ] Load balancing across replicas
- [ ] Image cache warming
- [ ] Metrics and monitoring (Prometheus)

### Reliability
- [ ] Health checks for containers
- [ ] Automatic retries on failure
- [ ] Circuit breakers
- [ ] Request timeouts
- [ ] Graceful shutdown

### Observability
- [ ] Structured logging
- [ ] Request tracing (OpenTelemetry)
- [ ] Container metrics (CPU, memory, network)
- [ ] Application metrics export

## References

- **containerd documentation:** https://containerd.io/docs/
- **OCI Runtime Spec:** https://github.com/opencontainers/runtime-spec
- **OCI Image Spec:** https://github.com/opencontainers/image-spec
- **containerd gRPC API:** https://github.com/containerd/containerd/tree/main/api
- **SCM_RIGHTS:** See `SOCKET_HANDOFF.md` in this repository

## Related Documentation

- `SOCKET_HANDOFF.md` - Deep dive into SCM_RIGHTS mechanism
- `FAAS_RUNTIME.md` - Alternative runtime implementation approaches
- `DOCKER_IMPLEMENTATION.md` - Previous Docker-based implementation (deprecated)
