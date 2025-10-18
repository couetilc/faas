# FaaS with runc Implementation

## Overview

This document describes the runc-based implementation of the FaaS platform. Users submit Docker images which are extracted once into rootfs directories, then reused across all container invocations.

**Key insight:** Extract Docker image layers once when uploaded, store as rootfs directory, reuse read-only rootfs for every request.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│ User Machine                                            │
│                                                         │
│  docker build -t my-handler .                          │
│  docker save my-handler | faas new my-handler          │
│                                                         │
└────────────────────────┬────────────────────────────────┘
                         │ Tarball stream (HTTP)
                         ↓
┌─────────────────────────────────────────────────────────┐
│ Service Provider Machine                                │
│                                                         │
│  ┌──────────────────────────────────────────────────┐  │
│  │ faasd (single Python process, no daemon!)       │  │
│  │                                                  │  │
│  │  Control API (:8080)                            │  │
│  │    ↓                                            │  │
│  │  Extract Docker layers → rootfs (ONCE)          │  │
│  │    ↓                                            │  │
│  │  Store at /var/lib/faasd/images/X/rootfs/       │  │
│  │    ↓                                            │  │
│  │  Allocate IP, start listener                   │  │
│  │                                                  │  │
│  │  On HTTP request:                               │  │
│  │    1. Create /tmp/bundle/config.json            │  │
│  │    2. config points to existing rootfs          │  │
│  │    3. runc run (uses rootfs read-only)          │  │
│  │    4. Pass socket via SCM_RIGHTS                │  │
│  │    5. Delete bundle dir (rootfs stays!)         │  │
│  └────────────────────┬─────────────────────────────┘  │
│                       │                                 │
│                       ↓                                 │
│              ┌─────────────────┐                        │
│              │      runc       │                        │
│              │   (no daemon!)  │                        │
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
docker save my-handler | faas new my-handler
# → Streams tarball to faasd
# → faasd extracts layers to rootfs directory
# → faasd allocates IP
# → Returns: my-handler deployed at 10.0.0.10

# 3. Query assigned IP
faas ip my-handler
# → 10.0.0.10

# 4. Make requests
curl http://10.0.0.10/
# → faasd spawns runc container (reuses rootfs)
# → Container handles request
# → Container exits
# → Rootfs remains for next request
```

## Why runc Instead of containerd?

### The Key Insight

**With containerd:**
- Images stored in content-addressable format
- Layers unpacked on every container create
- Requires containerd daemon running
- Complex snapshot/overlay management

**With runc:**
- Extract Docker layers ONCE when image uploaded
- Store as simple directory tree (rootfs)
- No daemon needed
- Reuse same rootfs for ALL requests (read-only)

### Comparison

| Aspect | containerd | runc |
|--------|-----------|------|
| **Daemon** | Required | None |
| **Image storage** | Complex (content-addressable) | Simple (directory) |
| **Per-request overhead** | Unpack layers, create snapshot | Just create config.json |
| **Complexity** | gRPC API, proto definitions | JSON config + CLI |
| **Dependencies** | containerd daemon | Just runc binary |
| **Debugging** | Requires ctr/crictl tools | Standard Unix tools (ls, cat) |
| **Layer extraction** | Automatic | Manual (30 lines of code) |
| **Rootfs reuse** | No (creates snapshots) | Yes (direct reuse) |
| **Cold start** | ~100-200ms | ~10-50ms |

### Decision

**Use runc** because:
1. ✅ Simpler - no daemon to manage
2. ✅ Faster - rootfs extracted once, reused forever
3. ✅ Transparent - rootfs is just a directory tree
4. ✅ Educational - understand Docker image format
5. ✅ Self-contained - no runtime dependencies

The only "downside" (manual layer extraction) is trivial to implement.

## Storage Layout

```
/var/lib/faasd/
├── images/
│   ├── my-handler/
│   │   └── rootfs/              ← Extracted ONCE, reused forever
│   │       ├── bin/
│   │       ├── etc/
│   │       ├── lib/
│   │       ├── usr/
│   │       │   └── bin/python3
│   │       └── app/
│   │           └── handler.py
│   │
│   ├── api-service/
│   │   └── rootfs/              ← Different image, different rootfs
│   │       ├── bin/
│   │       ├── usr/bin/node
│   │       └── app/
│   │           └── server.js
│   │
│   └── ml-model/
│       └── rootfs/
│           ├── usr/bin/python3
│           └── app/
│               └── model.py
│
├── registry.json                ← Image → IP mappings
└── bundles/                     ← Temporary per-request
    ├── faas-abc123/             ← Created per request
    │   └── config.json          → Points to ../images/my-handler/rootfs
    └── faas-def456/             ← Different request
        └── config.json          → Points to ../images/my-handler/rootfs
```

**Key points:**
- Rootfs extracted once, lives at `/var/lib/faasd/images/{name}/rootfs/`
- Multiple bundles can point to same rootfs
- Bundles are temporary (created per request, deleted after)
- Rootfs is permanent (until image deleted)

## Docker Image Format

Understanding the Docker image tarball format is key to extraction.

### Tarball Structure

```
my-handler.tar
├── manifest.json              # Image metadata
├── config.json               # Image configuration
├── <sha256>.tar              # Layer 1 (base OS)
├── <sha256>.tar              # Layer 2 (Python install)
├── <sha256>.tar              # Layer 3 (dependencies)
└── <sha256>.tar              # Layer 4 (application code)
```

### manifest.json Example

```json
[
  {
    "Config": "a1b2c3d4...json",
    "RepoTags": ["my-handler:latest"],
    "Layers": [
      "e5f6g7h8.../layer.tar",
      "i9j0k1l2.../layer.tar",
      "m3n4o5p6.../layer.tar",
      "q7r8s9t0.../layer.tar"
    ]
  }
]
```

### Layer Application (Overlay Filesystem Simulation)

Layers are applied in order, later layers override earlier ones:

```
Layer 1 (base):
  /bin/sh
  /lib/libc.so

Layer 2 (python):
  /usr/bin/python3
  /usr/lib/python3.12/

Layer 3 (pip packages):
  /usr/lib/python3.12/site-packages/requests/

Layer 4 (application):
  /app/handler.py

Final rootfs = Layer 1 ∪ Layer 2 ∪ Layer 3 ∪ Layer 4
```

If a file exists in multiple layers, the **later layer wins**.

## Implementation

### 1. Image Extraction

```python
import tarfile
import json
import os
import shutil

def extract_docker_image(tar_stream, rootfs_path):
    """
    Extract Docker image tarball to rootfs directory.

    Args:
        tar_stream: File-like object containing Docker image tarball
        rootfs_path: Destination path for rootfs (e.g., /var/lib/faasd/images/X/rootfs)
    """
    temp_dir = "/tmp/faas-image-extract"

    try:
        # 1. Extract entire tarball to temp directory
        os.makedirs(temp_dir, exist_ok=True)
        with tarfile.open(fileobj=tar_stream, mode='r') as tar:
            tar.extractall(temp_dir)

        # 2. Read manifest to find layer order
        manifest_path = f"{temp_dir}/manifest.json"
        with open(manifest_path) as f:
            manifest = json.load(f)[0]  # Single image in tarball

        # 3. Create rootfs directory
        os.makedirs(rootfs_path, exist_ok=True)

        # 4. Extract each layer in order (simulates overlay filesystem)
        for layer_path in manifest['Layers']:
            layer_tar = f"{temp_dir}/{layer_path}"
            print(f"Extracting layer: {layer_path}")

            with tarfile.open(layer_tar, 'r') as layer:
                # Extract directly to rootfs (overlays on top of previous layers)
                layer.extractall(rootfs_path)

        print(f"✓ Image extracted to {rootfs_path}")

    finally:
        # Cleanup temp directory
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)


def get_image_entrypoint(tar_stream):
    """
    Extract CMD/ENTRYPOINT from Docker image config.

    Returns:
        List of command arguments (e.g., ["python3", "/app/handler.py"])
    """
    temp_dir = "/tmp/faas-image-inspect"

    try:
        os.makedirs(temp_dir, exist_ok=True)

        # Extract tarball
        with tarfile.open(fileobj=tar_stream, mode='r') as tar:
            tar.extractall(temp_dir)

        # Read manifest
        with open(f"{temp_dir}/manifest.json") as f:
            manifest = json.load(f)[0]

        # Read image config
        config_file = f"{temp_dir}/{manifest['Config']}"
        with open(config_file) as f:
            config = json.load(f)

        # Get entrypoint + cmd
        entrypoint = config['config'].get('Entrypoint', [])
        cmd = config['config'].get('Cmd', [])

        return entrypoint + cmd

    finally:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
```

### 2. OCI Bundle Creation (Per Request)

```python
import uuid
import json

def create_runc_bundle(rootfs_path, sock_path):
    """
    Create OCI bundle for runc.

    Args:
        rootfs_path: Path to pre-extracted rootfs
        sock_path: Path to Unix control socket

    Returns:
        (bundle_dir, container_id)
    """
    container_id = f"faas-{uuid.uuid4()}"
    bundle_dir = f"/var/lib/faasd/bundles/{container_id}"

    os.makedirs(bundle_dir, exist_ok=True)

    # OCI runtime spec config
    config = {
        "ociVersion": "1.0.0",
        "process": {
            "terminal": False,
            "user": {"uid": 0, "gid": 0},
            "args": ["python3", "/app/handler.py"],  # From image config or default
            "env": [
                "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            ],
            "cwd": "/",
            "noNewPrivileges": True
        },
        "root": {
            "path": rootfs_path,  # ← Points to shared rootfs
            "readonly": True       # ← Read-only (safe to share)
        },
        "mounts": [
            {
                "destination": "/control.sock",
                "type": "bind",
                "source": sock_path,
                "options": ["bind", "ro"]
            },
            {
                "destination": "/tmp",
                "type": "tmpfs",
                "source": "tmpfs",
                "options": ["nosuid", "nodev", "mode=1777"]
            },
            {
                "destination": "/proc",
                "type": "proc",
                "source": "proc"
            },
            {
                "destination": "/dev",
                "type": "tmpfs",
                "source": "tmpfs",
                "options": ["nosuid", "strictatime", "mode=755"]
            }
        ],
        "linux": {
            "namespaces": [
                {"type": "pid"},
                {"type": "network"},
                {"type": "ipc"},
                {"type": "uts"},
                {"type": "mount"}
            ],
            "resources": {
                "memory": {
                    "limit": 536870912  # 512MB
                },
                "cpu": {
                    "quota": 100000,
                    "period": 100000
                }
            },
            "maskedPaths": [
                "/proc/kcore",
                "/proc/latency_stats",
                "/sys/firmware"
            ],
            "readonlyPaths": [
                "/proc/bus",
                "/proc/fs",
                "/proc/irq",
                "/proc/sys",
                "/proc/sysrq-trigger"
            ]
        }
    }

    # Write config.json
    config_path = f"{bundle_dir}/config.json"
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)

    return bundle_dir, container_id
```

### 3. Container Lifecycle

```python
import subprocess
import socket
import array

def handle_request(client_sock, client_addr, rootfs_path):
    """
    Handle HTTP request by spawning runc container.

    Args:
        client_sock: Accepted TCP socket
        client_addr: Client address tuple
        rootfs_path: Path to image's rootfs
    """
    container_id = f"faas-{uuid.uuid4()}"
    sock_path = f"/tmp/{container_id}.sock"
    bundle_dir = None

    try:
        # 1. Create Unix control socket
        control_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        control_sock.bind(sock_path)
        control_sock.listen(1)

        # 2. Create OCI bundle
        bundle_dir, container_id = create_runc_bundle(rootfs_path, sock_path)

        # 3. Spawn container with runc
        print(f"Spawning container {container_id}")
        proc = subprocess.Popen(
            ['runc', 'run', container_id],
            cwd=bundle_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        # 4. Wait for container to connect to control socket
        control_sock.settimeout(5.0)
        conn, _ = control_sock.accept()
        print(f"Container connected to control socket")

        # 5. Pass TCP socket FD via SCM_RIGHTS
        tcp_fd = client_sock.fileno()
        conn.sendmsg(
            [b'SOCKET'],
            [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array('i', [tcp_fd]))]
        )
        print(f"Sent FD {tcp_fd} to container")

        # 6. Close our references (container owns socket now)
        client_sock.close()
        conn.close()
        control_sock.close()

        # 7. Wait for container to finish
        proc.wait(timeout=30)
        print(f"Container exited with code {proc.returncode}")

    except subprocess.TimeoutExpired:
        print(f"Container timeout, killing...")
        subprocess.run(['runc', 'kill', container_id, 'SIGKILL'])
        proc.wait()

    except Exception as e:
        print(f"Error handling request: {e}")
        import traceback
        traceback.print_exc()

    finally:
        # Cleanup
        try:
            subprocess.run(['runc', 'delete', '--force', container_id],
                          stderr=subprocess.DEVNULL)
        except:
            pass

        if bundle_dir and os.path.exists(bundle_dir):
            shutil.rmtree(bundle_dir)

        if os.path.exists(sock_path):
            os.unlink(sock_path)

        # Note: rootfs_path is NOT deleted - reused for next request!
```

## faasd Implementation

### Complete Server Structure

```python
#!/usr/bin/env python3
"""
faasd - FaaS daemon using runc
"""

import json
import os
import socket
import select
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

FAAS_ROOT = "/var/lib/faasd"
IMAGES_DIR = f"{FAAS_ROOT}/images"
BUNDLES_DIR = f"{FAAS_ROOT}/bundles"
REGISTRY_FILE = f"{FAAS_ROOT}/registry.json"


class Registry:
    """Manages image → IP mappings."""

    def __init__(self):
        self.file = REGISTRY_FILE
        self.data = self._load()

    def _load(self):
        if os.path.exists(self.file):
            with open(self.file) as f:
                return json.load(f)
        return {}

    def save(self):
        with open(self.file, 'w') as f:
            json.dump(self.data, f, indent=2)

    def allocate_ip(self):
        used = {m['ip'] for m in self.data.values()}
        for i in range(10, 255):
            ip = f"10.0.0.{i}"
            if ip not in used:
                return ip
        raise Exception("No IPs available")

    def register(self, name, rootfs_path, ip):
        self.data[name] = {
            'ip': ip,
            'rootfs': rootfs_path
        }
        self.save()

    def get(self, name):
        return self.data.get(name)

    def list_all(self):
        return self.data


class ControlAPI(BaseHTTPRequestHandler):
    """HTTP API for faas client."""

    def do_POST(self):
        if self.path == '/api/new':
            self._handle_new()
        else:
            self.send_error(404)

    def do_GET(self):
        if self.path.startswith('/api/ip/'):
            self._handle_ip()
        elif self.path == '/api/list':
            self._handle_list()
        else:
            self.send_error(404)

    def _handle_new(self):
        """Handle image upload."""
        name = self.headers.get('X-Image-Name')
        if not name:
            self.send_error(400, "Missing X-Image-Name")
            return

        # Read tarball
        length = int(self.headers.get('Content-Length', 0))
        tar_data = self.rfile.read(length)

        try:
            # Extract to rootfs
            rootfs_path = f"{IMAGES_DIR}/{name}/rootfs"

            import io
            extract_docker_image(io.BytesIO(tar_data), rootfs_path)

            # Allocate IP
            ip = self.server.registry.allocate_ip()

            # Register
            self.server.registry.register(name, rootfs_path, ip)

            # Start listener
            self.server.faas_server.add_listener(ip, name, rootfs_path)

            # Respond
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({
                'name': name,
                'ip': ip
            }).encode())

        except Exception as e:
            self.send_error(500, str(e))

    def _handle_ip(self):
        name = self.path.split('/')[-1]
        metadata = self.server.registry.get(name)

        if metadata:
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({
                'name': name,
                'ip': metadata['ip']
            }).encode())
        else:
            self.send_error(404, f"Image {name} not found")

    def _handle_list(self):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(
            self.server.registry.list_all(), indent=2
        ).encode())


class FaaSServer:
    """Handles HTTP requests on allocated IPs."""

    def __init__(self):
        self.sockets = {}  # socket → (image_name, rootfs_path)

    def add_listener(self, ip, image_name, rootfs_path):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((ip, 80))
        sock.listen(5)

        self.sockets[sock] = (image_name, rootfs_path)
        print(f"Listening on {ip}:80 for {image_name}")

    def run(self):
        print("FaaS server ready")

        while True:
            if not self.sockets:
                # No listeners yet, wait
                import time
                time.sleep(1)
                continue

            readable, _, _ = select.select(list(self.sockets.keys()), [], [])

            for sock in readable:
                client_sock, addr = sock.accept()
                image_name, rootfs_path = self.sockets[sock]

                print(f"Request from {addr} → {image_name}")

                # Handle in thread
                threading.Thread(
                    target=handle_request,
                    args=(client_sock, addr, rootfs_path),
                    daemon=True
                ).start()


def main():
    # Setup
    os.makedirs(FAAS_ROOT, exist_ok=True)
    os.makedirs(IMAGES_DIR, exist_ok=True)
    os.makedirs(BUNDLES_DIR, exist_ok=True)

    registry = Registry()
    faas_server = FaaSServer()

    # Restore listeners for existing images
    for name, metadata in registry.list_all().items():
        faas_server.add_listener(
            metadata['ip'],
            name,
            metadata['rootfs']
        )

    # Start control API in thread
    control_server = HTTPServer(('0.0.0.0', 8080), ControlAPI)
    control_server.registry = registry
    control_server.faas_server = faas_server

    threading.Thread(
        target=control_server.serve_forever,
        daemon=True
    ).start()

    print("faasd started")
    print("  Control API: http://0.0.0.0:8080")

    # Run main event loop
    faas_server.run()


if __name__ == '__main__':
    main()
```

## Handler Contract

User-provided Docker images must include code that:

1. **Connects to `/control.sock`** - Unix domain socket mounted by faasd
2. **Receives socket FD via SCM_RIGHTS** - TCP socket file descriptor
3. **Handles HTTP request** - Read from socket, write response
4. **Exits cleanly** - Container terminates when done

### Example Handler (Python)

```python
#!/usr/bin/env python3
import socket
import array
import os
import sys

def main():
    # Connect to control socket
    control_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

    try:
        control_sock.connect('/control.sock')
    except Exception as e:
        print(f"Error: Could not connect to /control.sock: {e}", file=sys.stderr)
        sys.exit(1)

    # Receive TCP socket FD via SCM_RIGHTS
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
        print("Error: No FD received", file=sys.stderr)
        sys.exit(1)

    tcp_fd = fds[0]
    control_sock.close()

    # Reconstruct TCP socket from FD
    client_sock = socket.fromfd(tcp_fd, socket.AF_INET, socket.SOCK_STREAM)

    # Read HTTP request (simplified - just read until blank line)
    request_data = b""
    while b"\r\n\r\n" not in request_data:
        chunk = client_sock.recv(1024)
        if not chunk:
            break
        request_data += chunk

    # Generate response
    response_body = b"Hello from FaaS handler!"
    response = (
        b"HTTP/1.1 200 OK\r\n"
        b"Content-Type: text/plain\r\n"
        f"Content-Length: {len(response_body)}\r\n"
        b"\r\n"
    ) + response_body

    # Send response
    client_sock.sendall(response)
    client_sock.close()

    print("Request handled successfully", file=sys.stderr)

if __name__ == '__main__':
    main()
```

### Example Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY handler.py /app/handler.py

CMD ["python3", "/app/handler.py"]
```

## Testing

### 1. Build Test Image

```bash
cat > handler.py <<'EOF'
#!/usr/bin/env python3
import socket, array, sys

control = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
control.connect('/control.sock')

fds = array.array('i')
msg, ancdata, _, _ = control.recvmsg(1024, socket.CMSG_SPACE(4))

for level, type, data in ancdata:
    if level == socket.SOL_SOCKET and type == socket.SCM_RIGHTS:
        fds.frombytes(data)

sock = socket.fromfd(fds[0], socket.AF_INET, socket.SOCK_STREAM)

# Read request
while True:
    data = sock.recv(1024)
    if b"\r\n\r\n" in data:
        break

# Send response
response = b"HTTP/1.1 200 OK\r\n\r\nHello from test handler!"
sock.sendall(response)
sock.close()
EOF

cat > Dockerfile <<'EOF'
FROM python:3.11-slim
COPY handler.py /app/handler.py
CMD ["python3", "/app/handler.py"]
EOF

docker build -t test-handler .
```

### 2. Start faasd

```bash
sudo python3 faasd.py
# → faasd started
# → Control API: http://0.0.0.0:8080
```

### 3. Publish Image

```bash
docker save test-handler | curl -X POST http://localhost:8080/api/new \
  -H "X-Image-Name: test-handler" \
  --data-binary @-

# → {"name": "test-handler", "ip": "10.0.0.10"}
```

### 4. Configure IP

```bash
sudo ip addr add 10.0.0.10/24 dev lo
```

### 5. Test Request

```bash
curl http://10.0.0.10/
# → Hello from test handler!
```

## Implementation Phases

### Phase 1: runc Setup ✅
- Install runc
- Test basic container creation
- Verify namespace isolation

### Phase 2: Image Extraction
- Implement Docker tarball parser
- Extract layers to rootfs
- Test with sample images

### Phase 3: faasd Core
- Registry implementation
- Control API
- IP allocation

### Phase 4: Request Handling
- Dynamic listeners
- Bundle creation per request
- Container spawning with runc

### Phase 5: SCM_RIGHTS Integration
- Control socket creation
- FD passing
- Cleanup

### Phase 6: faas CLI
- `faas new` - export and upload
- `faas ip` - query IP
- `faas list` - list deployments

## Advantages Over containerd

1. **No daemon** - Just runc binary, no background processes
2. **Simpler** - Rootfs is just a directory, config.json is just JSON
3. **Faster** - No layer unpacking per request
4. **Transparent** - Can inspect rootfs with standard tools
5. **Educational** - Understand Docker image format deeply
6. **Minimal dependencies** - Just runc + Python stdlib

## Production Considerations

### Security
- [ ] Enforce read-only rootfs
- [ ] Drop capabilities
- [ ] Seccomp profiles
- [ ] AppArmor/SELinux policies
- [ ] Resource limits (CPU, memory, PIDs)

### Reliability
- [ ] Container timeouts
- [ ] Automatic cleanup on crash
- [ ] Health checks
- [ ] Graceful shutdown

### Performance
- [ ] Container pooling (pre-spawned containers)
- [ ] Rootfs caching
- [ ] Concurrent request handling
- [ ] Request queueing

### Observability
- [ ] Structured logging
- [ ] Metrics (request count, latency, errors)
- [ ] Container stdout/stderr capture
- [ ] Request tracing

## References

- **OCI Runtime Spec:** https://github.com/opencontainers/runtime-spec
- **runc Documentation:** https://github.com/opencontainers/runc
- **Docker Image Spec:** https://github.com/opencontainers/image-spec
- **SCM_RIGHTS:** See `SOCKET_HANDOFF.md` in this repository
