#!/usr/bin/env python3
"""
faasd - FaaS daemon using runc

A serverless function platform that uses runc for container execution.
Extracts Docker images once to rootfs directories and reuses them for all requests.
"""

import json
import os
import socket
import select
import threading
import tarfile
import io
import shutil
import uuid
import subprocess
import array
import sys
import signal
import atexit
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

# Configuration
FAAS_ROOT = "/var/lib/faasd"
IMAGES_DIR = f"{FAAS_ROOT}/images"
BUNDLES_DIR = f"{FAAS_ROOT}/bundles"
REGISTRY_FILE = f"{FAAS_ROOT}/registry.json"


# =============================================================================
# Docker Image Extraction
# =============================================================================

def extract_docker_image(tar_stream, rootfs_path):
    """
    Extract Docker image tarball to rootfs directory.

    Reads Docker image format, extracts layers in order, and overlays them
    to create the final rootfs (simulating overlay filesystem).

    Args:
        tar_stream: File-like object containing Docker image tarball
        rootfs_path: Destination path for rootfs (e.g., /var/lib/faasd/images/X/rootfs)
    """
    temp_dir = f"/tmp/faas-image-extract-{uuid.uuid4()}"

    try:
        # 1. Extract entire tarball to temp directory
        print(f"[extract] Extracting tarball to {temp_dir}")
        os.makedirs(temp_dir, exist_ok=True)
        with tarfile.open(fileobj=tar_stream, mode='r') as tar:
            tar.extractall(temp_dir)

        # 2. Read manifest to find layer order
        manifest_path = f"{temp_dir}/manifest.json"
        if not os.path.exists(manifest_path):
            raise Exception("Invalid Docker image: manifest.json not found")

        with open(manifest_path) as f:
            manifest = json.load(f)[0]  # Single image in tarball

        # 3. Create rootfs directory
        print(f"[extract] Creating rootfs at {rootfs_path}")
        os.makedirs(rootfs_path, exist_ok=True)

        # 4. Extract each layer in order (simulates overlay filesystem)
        layers = manifest.get('Layers', [])
        print(f"[extract] Found {len(layers)} layers")

        for i, layer_path in enumerate(layers):
            layer_tar = f"{temp_dir}/{layer_path}"
            print(f"[extract] Extracting layer {i+1}/{len(layers)}: {layer_path}")

            with tarfile.open(layer_tar, 'r') as layer:
                # Extract directly to rootfs (overlays on top of previous layers)
                layer.extractall(rootfs_path)

        print(f"[extract] ✓ Image extracted to {rootfs_path}")

    except Exception as e:
        print(f"[extract] Error: {e}")
        raise
    finally:
        # Cleanup temp directory
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)


def get_image_entrypoint(tar_stream):
    """
    Extract CMD/ENTRYPOINT from Docker image config.

    Args:
        tar_stream: File-like object containing Docker image tarball

    Returns:
        List of command arguments (e.g., ["python3", "/app/handler.py"])
    """
    temp_dir = f"/tmp/faas-image-inspect-{uuid.uuid4()}"

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
        entrypoint = config.get('config', {}).get('Entrypoint', []) or []
        cmd = config.get('config', {}).get('Cmd', []) or []

        result = entrypoint + cmd
        print(f"[entrypoint] Extracted: {result}")
        return result

    finally:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)


# =============================================================================
# Registry
# =============================================================================

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
        """Allocate next available IP in 10.0.0.0/24 range."""
        used = {m['ip'] for m in self.data.values()}
        for i in range(10, 255):
            ip = f"10.0.0.{i}"
            if ip not in used:
                return ip
        raise Exception("No IPs available")

    def register(self, name, rootfs_path, cmd, ip):
        """Register new image deployment."""
        self.data[name] = {
            'ip': ip,
            'rootfs': rootfs_path,
            'cmd': cmd
        }
        self.save()

    def get(self, name):
        """Get image metadata by name."""
        return self.data.get(name)

    def list_all(self):
        """List all registered images."""
        return self.data


# =============================================================================
# OCI Bundle Creation
# =============================================================================

def create_runc_bundle(rootfs_path, sock_path, cmd):
    """
    Create OCI bundle for runc.

    Args:
        rootfs_path: Path to pre-extracted rootfs
        sock_path: Path to Unix control socket
        cmd: Command to run in container

    Returns:
        (bundle_dir, container_id)
    """
    container_id = f"faas-{uuid.uuid4()}"
    bundle_dir = f"{BUNDLES_DIR}/{container_id}"

    os.makedirs(bundle_dir, exist_ok=True)

    # OCI runtime spec config
    config = {
        "ociVersion": "1.0.0",
        "process": {
            "terminal": False,
            "user": {"uid": 0, "gid": 0},
            "args": cmd,
            "env": [
                "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            ],
            "cwd": "/",
            "noNewPrivileges": True
        },
        "root": {
            "path": rootfs_path,  # Points to shared rootfs
            "readonly": True       # Read-only (safe to share)
        },
        "mounts": [
            # Control socket for FaaS communication
            {
                "destination": "/control.sock",
                "type": "bind",
                "source": sock_path,
                "options": ["bind", "ro"]
            },
            # Standard container mounts (from runc spec)
            {
                "destination": "/proc",
                "type": "proc",
                "source": "proc"
            },
            {
                "destination": "/dev",
                "type": "tmpfs",
                "source": "tmpfs",
                "options": ["nosuid", "strictatime", "mode=755", "size=65536k"]
            },
            {
                "destination": "/dev/pts",
                "type": "devpts",
                "source": "devpts",
                "options": ["nosuid", "noexec", "newinstance", "ptmxmode=0666", "mode=0620", "gid=5"]
            },
            {
                "destination": "/dev/shm",
                "type": "tmpfs",
                "source": "shm",
                "options": ["nosuid", "noexec", "nodev", "mode=1777", "size=65536k"]
            },
            {
                "destination": "/dev/mqueue",
                "type": "mqueue",
                "source": "mqueue",
                "options": ["nosuid", "noexec", "nodev"]
            },
            {
                "destination": "/sys",
                "type": "sysfs",
                "source": "sysfs",
                "options": ["nosuid", "noexec", "nodev", "ro"]
            },
            {
                "destination": "/sys/fs/cgroup",
                "type": "cgroup",
                "source": "cgroup",
                "options": ["nosuid", "noexec", "nodev", "relatime", "ro"]
            },
            {
                "destination": "/tmp",
                "type": "tmpfs",
                "source": "tmpfs",
                "options": ["nosuid", "nodev", "mode=1777"]
            }
        ],
        "linux": {
            "namespaces": [
                {"type": "pid"},
                {"type": "network"},
                {"type": "ipc"},
                {"type": "uts"},
                {"type": "mount"},
                {"type": "cgroup"}
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


# =============================================================================
# Container Lifecycle
# =============================================================================

def handle_request(client_sock, client_addr, rootfs_path, cmd):
    """
    Handle HTTP request by spawning runc container.

    Args:
        client_sock: Accepted TCP socket
        client_addr: Client address tuple
        rootfs_path: Path to image's rootfs
        cmd: Command to run in container
    """
    container_id = f"faas-{uuid.uuid4()}"
    sock_path = f"/tmp/{container_id}.sock"
    bundle_dir = None

    try:
        print(f"[request] Handling request from {client_addr}")

        # 1. Create Unix control socket
        control_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        control_sock.bind(sock_path)
        control_sock.listen(1)

        # 2. Create OCI bundle
        bundle_dir, container_id = create_runc_bundle(rootfs_path, sock_path, cmd)
        print(f"[request] Created bundle at {bundle_dir}")

        # 3. Spawn container with runc
        print(f"[request] Spawning container {container_id}")
        proc = subprocess.Popen(
            ['runc', 'run', container_id],
            cwd=bundle_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        # 4. Wait for container to connect to control socket
        control_sock.settimeout(5.0)
        try:
            conn, _ = control_sock.accept()
            print(f"[request] Container connected to control socket")
        except socket.timeout:
            print(f"[request] *** TIMEOUT EXCEPTION CAUGHT ***", flush=True)
            print(f"[request] Timeout waiting for container connection", flush=True)
            # Get container stderr to see what went wrong
            try:
                stdout, stderr = proc.communicate(timeout=1)
                if stderr:
                    print(f"[request] Container stderr: {stderr.decode()}")
                if stdout:
                    print(f"[request] Container stdout: {stdout.decode()}")
            except subprocess.TimeoutExpired:
                print(f"[request] Container still running, can't get output yet")
                # Try to kill it to get output
                proc.kill()
                stdout, stderr = proc.communicate()
                if stderr:
                    print(f"[request] Container stderr (after kill): {stderr.decode()}")
                if stdout:
                    print(f"[request] Container stdout (after kill): {stdout.decode()}")
            raise

        # 5. Pass TCP socket FD via SCM_RIGHTS
        tcp_fd = client_sock.fileno()
        conn.sendmsg(
            [b'SOCKET'],
            [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array('i', [tcp_fd]))]
        )
        print(f"[request] Sent FD {tcp_fd} to container")

        # 6. Close our references (container owns socket now)
        client_sock.close()
        conn.close()
        control_sock.close()

        # 7. Wait for container to finish
        proc.wait(timeout=30)
        stdout, stderr = proc.communicate()
        print(f"[request] Container exited with code {proc.returncode}")

        if stderr:
            print(f"[request] Container stderr: {stderr.decode()}")

    except subprocess.TimeoutExpired:
        print(f"[request] Container timeout, killing...")
        subprocess.run(['runc', 'kill', container_id, 'SIGKILL'])
        proc.wait()

    except Exception as e:
        print(f"[request] Error handling request: {e}")
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


# =============================================================================
# FaaS Server
# =============================================================================

class FaaSServer:
    """Handles HTTP requests on allocated IPs."""

    def __init__(self):
        self.sockets = {}  # socket → (image_name, rootfs_path, cmd)
        self.configured_ips = set()  # Track IPs we configured
        self.lock = threading.Lock()

    def add_listener(self, ip, image_name, rootfs_path, cmd):
        """Start listening on IP for image requests."""

        # Automatically configure IP on loopback interface with FaaS label
        # All FaaS IPs share the same label for easy cleanup
        label = "lo:faas"
        try:
            result = subprocess.run(
                ['ip', 'addr', 'add', f'{ip}/24', 'dev', 'lo', 'label', label],
                capture_output=True,
                text=True
            )

            # Check if it worked or if IP already exists (which is fine)
            if result.returncode != 0:
                stderr = result.stderr.lower()
                if 'file exists' not in stderr and 'cannot assign' not in stderr:
                    print(f"[listener] Warning: Failed to add {ip} to loopback: {result.stderr.strip()}")
                else:
                    print(f"[listener] IP {ip} already configured on loopback")
            else:
                print(f"[listener] Configured {ip}/24 on loopback interface (label: {label})")
                # Track that we configured this IP
                with self.lock:
                    self.configured_ips.add(ip)

        except Exception as e:
            print(f"[listener] Warning: Could not configure IP {ip}: {e}")
            # Continue anyway - maybe IP is already configured

        # Create and bind socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        try:
            sock.bind((ip, 80))
            sock.listen(5)

            with self.lock:
                self.sockets[sock] = (image_name, rootfs_path, cmd)

            print(f"[listener] Listening on {ip}:80 for {image_name}")
        except Exception as e:
            print(f"[listener] Error binding to {ip}:80: {e}")
            raise

    def run(self):
        """Main event loop for handling requests."""
        print("[server] FaaS server ready")

        while True:
            with self.lock:
                sockets_list = list(self.sockets.keys())

            if not sockets_list:
                # No listeners yet, wait
                import time
                time.sleep(1)
                continue

            readable, _, _ = select.select(sockets_list, [], [], 1.0)

            for sock in readable:
                try:
                    client_sock, addr = sock.accept()

                    with self.lock:
                        image_name, rootfs_path, cmd = self.sockets[sock]

                    print(f"[server] Request from {addr} → {image_name}")

                    # Handle in thread
                    threading.Thread(
                        target=handle_request,
                        args=(client_sock, addr, rootfs_path, cmd),
                        daemon=True
                    ).start()

                except Exception as e:
                    print(f"[server] Error accepting connection: {e}")

    def cleanup(self):
        """Clean up network configuration on shutdown."""
        print("[shutdown] Cleaning up network configuration...")

        # Find all IPs with faas- label prefix
        try:
            result = subprocess.run(
                ['ip', 'addr', 'show', 'dev', 'lo'],
                capture_output=True,
                text=True
            )

            # Parse output to find IPs with faas labels
            import re
            faas_ips = []
            for line in result.stdout.split('\n'):
                # Look for lines like: inet 10.0.0.10/24 scope global lo:faas
                match = re.search(r'inet\s+(\S+)/\d+.*lo:faas', line)
                if match:
                    ip_with_mask = match.group(1)
                    faas_ips.append(ip_with_mask)

            # Remove all FaaS-labeled IPs
            for ip in faas_ips:
                try:
                    # Need to include the /24 when deleting
                    subprocess.run(
                        ['ip', 'addr', 'del', f'{ip}/24', 'dev', 'lo'],
                        capture_output=True,
                        text=True,
                        check=True
                    )
                    print(f"[shutdown] Removed {ip} from loopback interface")
                except subprocess.CalledProcessError as e:
                    print(f"[shutdown] Warning: Could not remove IP {ip}: {e.stderr}")
                except Exception as e:
                    print(f"[shutdown] Warning: Could not remove IP {ip}: {e}")

            if not faas_ips:
                print("[shutdown] No FaaS-labeled IPs found to clean up")

        except Exception as e:
            print(f"[shutdown] Warning: Could not query/clean up IPs: {e}")


# =============================================================================
# Control API
# =============================================================================

class ControlAPI(BaseHTTPRequestHandler):
    """HTTP API for faas client."""

    def log_message(self, format, *args):
        """Override to customize logging."""
        print(f"[api] {self.address_string()} - {format % args}")

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
            self.send_error(400, "Missing X-Image-Name header")
            return

        print(f"[api] Uploading image: {name}")

        # Read tarball
        length = int(self.headers.get('Content-Length', 0))
        tar_data = self.rfile.read(length)

        print(f"[api] Received {length} bytes")

        try:
            # Extract to rootfs
            rootfs_path = f"{IMAGES_DIR}/{name}/rootfs"

            # Extract image
            tar_stream = io.BytesIO(tar_data)
            extract_docker_image(tar_stream, rootfs_path)

            # Get entrypoint/cmd
            tar_stream.seek(0)
            cmd = get_image_entrypoint(tar_stream)

            if not cmd:
                cmd = ["/bin/sh"]  # Default if no CMD/ENTRYPOINT

            # Allocate IP
            ip = self.server.registry.allocate_ip()

            # Register
            self.server.registry.register(name, rootfs_path, cmd, ip)

            # Start listener
            self.server.faas_server.add_listener(ip, name, rootfs_path, cmd)

            # Respond
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            response = json.dumps({
                'name': name,
                'ip': ip,
                'cmd': cmd
            })
            self.wfile.write(response.encode())

            print(f"[api] ✓ Deployed {name} at {ip}")

        except Exception as e:
            print(f"[api] Error: {e}")
            import traceback
            traceback.print_exc()
            self.send_error(500, str(e))

    def _handle_ip(self):
        """Query IP for image name."""
        name = self.path.split('/')[-1]
        metadata = self.server.registry.get(name)

        if metadata:
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            response = json.dumps({
                'name': name,
                'ip': metadata['ip']
            })
            self.wfile.write(response.encode())
        else:
            self.send_error(404, f"Image {name} not found")

    def _handle_list(self):
        """List all deployed images."""
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        response = json.dumps(
            self.server.registry.list_all(), indent=2
        )
        self.wfile.write(response.encode())


# =============================================================================
# Main
# =============================================================================

def main():
    """Main entry point for faasd."""

    print("=" * 60)
    print("faasd - FaaS daemon using runc")
    print("=" * 60)

    # Check if running as root
    if os.geteuid() != 0:
        print("ERROR: faasd must be run as root")
        print("Use: sudo python3 faasd.py")
        sys.exit(1)

    # Setup directories
    print(f"[init] Setting up {FAAS_ROOT}")
    os.makedirs(FAAS_ROOT, exist_ok=True)
    os.makedirs(IMAGES_DIR, exist_ok=True)
    os.makedirs(BUNDLES_DIR, exist_ok=True)

    # Initialize registry
    registry = Registry()
    print(f"[init] Loaded {len(registry.list_all())} images from registry")

    # Initialize FaaS server
    faas_server = FaaSServer()

    # Register cleanup handlers
    def cleanup_handler(signum=None, frame=None):
        print("\n[shutdown] Shutting down faasd...")
        faas_server.cleanup()
        sys.exit(0)

    signal.signal(signal.SIGTERM, cleanup_handler)
    signal.signal(signal.SIGINT, cleanup_handler)
    atexit.register(lambda: faas_server.cleanup())

    # Restore listeners for existing images
    for name, metadata in registry.list_all().items():
        print(f"[init] Restoring listener for {name} at {metadata['ip']}")
        faas_server.add_listener(
            metadata['ip'],
            name,
            metadata['rootfs'],
            metadata['cmd']
        )

    # Start control API in thread
    print("[init] Starting control API on :8080")
    control_server = HTTPServer(('0.0.0.0', 8080), ControlAPI)
    control_server.registry = registry
    control_server.faas_server = faas_server

    threading.Thread(
        target=control_server.serve_forever,
        daemon=True
    ).start()

    print()
    print("=" * 60)
    print("faasd started successfully")
    print("=" * 60)
    print("  Control API: http://0.0.0.0:8080")
    print("  Registry:    /var/lib/faasd/registry.json")
    print()

    # Run main event loop (cleanup handled by signal handlers)
    faas_server.run()


if __name__ == '__main__':
    main()
