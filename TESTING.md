# Testing Guide for runc-based FaaS

This guide walks through testing the complete FaaS implementation.

## Prerequisites

1. **Root access** - faasd must run as root
2. **runc installed** - Already verified (version 1.3.0)
3. **Docker installed** - For building test images
4. **Python 3.11+** - For running faasd and handlers (uses only standard library)

## Quick Start

### 1. Build test handler image

```bash
docker build -f Dockerfile.test-handler -t test-handler .
```

### 2. Start faasd (in one terminal)

```bash
sudo ./faasd.py
```

You should see:
```
============================================================
faasd - FaaS daemon using runc
============================================================
[init] Setting up /var/lib/faasd
[init] Loaded 0 images from registry
[init] Starting control API on :8080

============================================================
faasd started successfully
============================================================
  Control API: http://0.0.0.0:8080
  Registry:    /var/lib/faasd/registry.json

[server] FaaS server ready
```

### 3. Deploy test handler (in another terminal)

```bash
docker save test-handler | ./faas new test-handler
```

Expected output:
```
Uploading image 'test-handler' to FaaS platform...
Read 12345678 bytes from stdin
✓ Deployed test-handler at 10.0.0.10
  Command: ['python3', '/app/handler.py']
```

### 4. Test the handler (IP is configured automatically by faasd)

```bash
curl http://10.0.0.10/
```

Expected output:
```
Hello from FaaS handler!

Request: GET / HTTP/1.1
```

Note: faasd automatically configured 10.0.0.10/24 on the loopback interface with label `lo:faas`. You can verify this with:
```bash
ip addr show dev lo | grep faas
```

### 5. Query deployment info

```bash
# Get IP for specific handler
./faas ip test-handler

# List all deployments
./faas list
```

## Step-by-Step Testing

### Test 1: Verify runc installation

```bash
runc --version
```

Should show version 1.3.0 or higher with OCI spec 1.0+.

### Test 2: Build handler image

```bash
# Build the test handler
docker build -f Dockerfile.test-handler -t test-handler .

# Verify image was created
docker images test-handler
```

### Test 3: Test Docker image extraction locally

Create a test script to verify layer extraction:

```bash
python3 << 'EOF'
import io
import subprocess

# Save Docker image
result = subprocess.run(['docker', 'save', 'test-handler'], capture_output=True)
tar_data = result.stdout

print(f"Image size: {len(tar_data)} bytes")

# Test extraction
import sys
sys.path.insert(0, '.')
from faasd import extract_docker_image, get_image_entrypoint

# Extract
rootfs_path = '/tmp/test-rootfs'
extract_docker_image(io.BytesIO(tar_data), rootfs_path)

# Check rootfs
import os
print(f"Rootfs created: {os.path.exists(rootfs_path)}")
print(f"Handler exists: {os.path.exists(f'{rootfs_path}/app/handler.py')}")

# Get entrypoint
cmd = get_image_entrypoint(io.BytesIO(tar_data))
print(f"Command: {cmd}")

# Cleanup
import shutil
shutil.rmtree(rootfs_path)
EOF
```

### Test 4: Start faasd

```bash
# Start faasd (requires root)
sudo ./faasd.py
```

Leave this running in a terminal.

### Test 5: Deploy handler

In a new terminal:

```bash
docker save test-handler | ./faas new test-handler
```

Check faasd logs for:
```
[api] Uploading image: test-handler
[extract] Extracting tarball to /tmp/faas-image-extract-...
[extract] Found X layers
[extract] ✓ Image extracted to /var/lib/faasd/images/test-handler/rootfs
[listener] Listening on 10.0.0.10:80 for test-handler
[api] ✓ Deployed test-handler at 10.0.0.10
```

### Test 6: Configure IP

```bash
# Add IP to loopback interface
sudo ip addr add 10.0.0.10/24 dev lo

# Verify
ip addr show lo | grep 10.0.0.10
```

### Test 7: Make request

```bash
curl http://10.0.0.10/
```

Check faasd logs for:
```
[server] Request from ('10.0.0.10', XXXX) → test-handler
[request] Handling request from ('10.0.0.10', XXXX)
[request] Created bundle at /var/lib/faasd/bundles/faas-...
[request] Spawning container faas-...
[request] Container connected to control socket
[request] Sent FD XX to container
[request] Container exited with code 0
[request] Container stderr: [handler] Starting FaaS handler
[handler] Connected to control socket
[handler] Received FD: 4
[handler] Request: GET / HTTP/1.1
[handler] Request handled successfully
```

### Test 8: Multiple requests

Test that rootfs is reused:

```bash
# Make multiple requests
for i in {1..5}; do
  echo "Request $i:"
  curl http://10.0.0.10/
  echo
done
```

Each request should spawn a new container but reuse the same rootfs.

### Test 9: Deploy multiple handlers

Create a second handler:

```bash
# Modify test handler slightly
cat > test_handler2.py << 'EOF'
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
data = sock.recv(4096)

# Send response
response = b"HTTP/1.1 200 OK\r\n\r\nHello from handler #2!"
sock.sendall(response)
sock.close()
EOF

chmod +x test_handler2.py

# Build second image
cat > Dockerfile.handler2 << 'EOF'
FROM python:3.11-slim
COPY test_handler2.py /app/handler.py
CMD ["python3", "/app/handler.py"]
EOF

docker build -f Dockerfile.handler2 -t test-handler-2 .

# Deploy
docker save test-handler-2 | ./faas new test-handler-2

# Configure IP
sudo ip addr add 10.0.0.11/24 dev lo

# Test
curl http://10.0.0.11/
```

### Test 10: List deployments

```bash
./faas list
```

Should show both handlers:
```
Name                 IP              Command
------------------------------------------------------------
test-handler         10.0.0.10       python3 /app/handler.py
test-handler-2       10.0.0.11       python3 /app/handler.py
```

## Troubleshooting

### Issue: "faasd must be run as root"

**Solution:** Run with sudo:
```bash
sudo ./faasd.py
```

### Issue: "Error binding to 10.0.0.10:80: [Errno 99] Cannot assign requested address"

**Solution:** Add IP to loopback interface:
```bash
sudo ip addr add 10.0.0.10/24 dev lo
```

### Issue: Container timeout when making request

**Possible causes:**
1. Handler not connecting to control socket
2. Handler not reading from socket correctly
3. Handler crashed

**Debug:**
- Check faasd logs for container stderr
- Test handler locally
- Verify handler implements protocol correctly

### Issue: "No FD received" in handler

**Solution:** Verify faasd is sending FD via SCM_RIGHTS. Check logs for:
```
[request] Sent FD XX to container
```

### Issue: "Invalid Docker image: manifest.json not found"

**Solution:** Ensure you're using `docker save`, not `docker export`:
```bash
# Correct
docker save my-image | ./faas new my-image

# Wrong
docker export container-id | ./faas new my-image
```

## Cleanup

### Remove deployed images

```bash
# Stop faasd (Ctrl+C)

# Remove faasd data
sudo rm -rf /var/lib/faasd

# Remove loopback IPs
sudo ip addr del 10.0.0.10/24 dev lo
sudo ip addr del 10.0.0.11/24 dev lo
```

### Remove Docker images

```bash
docker rmi test-handler
docker rmi test-handler-2
```

## Next Steps

After successful testing:

1. **Add security features**
   - Seccomp profiles
   - AppArmor/SELinux
   - Capability dropping

2. **Performance optimizations**
   - Container pooling
   - Request queueing
   - Metrics collection

3. **Build production handlers**
   - API handlers
   - ML model serving
   - Data processing

4. **Monitoring and observability**
   - Structured logging
   - Metrics export
   - Request tracing

## Architecture Verification

After testing, verify the architecture:

1. **Image extraction** - Rootfs should exist at `/var/lib/faasd/images/{name}/rootfs/`
2. **Rootfs reuse** - Same rootfs used for all requests (check with `ls -la /var/lib/faasd/images/`)
3. **Bundle cleanup** - Bundles should be deleted after request (check `/var/lib/faasd/bundles/`)
4. **No daemon** - Only faasd process running (no containerd, dockerd)
5. **Direct execution** - runc spawned per request, no pool

```bash
# Verify rootfs
sudo ls -la /var/lib/faasd/images/test-handler/rootfs/

# Verify bundles are cleaned up
sudo ls -la /var/lib/faasd/bundles/  # Should be empty after requests

# Verify registry
sudo cat /var/lib/faasd/registry.json
```
