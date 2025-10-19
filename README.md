# FaaS - Function as a Service Runtime

A minimal, fast, and transparent serverless platform using **runc** (no containerd, no docker daemon).

## Key Features

- 🚀 **Fast cold starts** (~10-50ms)
- 🎯 **Simple architecture** - No daemon required
- 🔒 **Secure** - Full container isolation with namespaces
- 📦 **Standard Docker images** - Deploy any Docker image
- 🔧 **Pure Python** - Standard library only, no dependencies
- 🎓 **Educational** - Easy to understand and modify

## Quick Start

```bash
# 1. Build a test handler
docker build -f Dockerfile.test-handler -t test-handler .

# 2. Start the FaaS daemon (requires root for runc)
sudo ./faasd.py

# 3. Deploy your handler (in another terminal)
docker save test-handler | ./faas new test-handler
# → ✓ Deployed test-handler at 10.0.0.10

# 4. Test it! (IP is configured automatically)
curl http://10.0.0.10/
# → Hello from FaaS handler!
```

## How It Works

1. **Deploy:** Upload Docker image → Extract layers to rootfs directory (once)
2. **Request:** HTTP request arrives → Spawn runc container → Pass socket via SCM_RIGHTS
3. **Execute:** Container handles request → Exits → Rootfs stays for next request

```
┌──────────────┐
│ Docker Image │  Extract once
└──────┬───────┘
       ↓
┌──────────────┐
│    Rootfs    │  Reuse forever (read-only)
└──────┬───────┘
       ↓
┌──────────────┐
│  Per Request │  Create bundle → runc run → Cleanup
└──────────────┘
```

## Commands

```bash
# Deploy an image
docker save my-image | ./faas new my-image

# Get assigned IP
./faas ip my-image

# List all deployments
./faas list

# Make requests
curl http://$(./faas ip my-image)/
```

## Requirements

- Python 3.11+ (standard library only!)
- runc 1.3.0+
- Docker (for building images)
- Root access (for runc)

## Project Structure

- `faasd.py` - Main daemon (image extraction, container lifecycle, HTTP API)
- `faas` - CLI client (deploy, query, list)
- `test_handler.py` - Example handler implementation
- `RUNC.md` - Architecture and design documentation
- `TESTING.md` - Comprehensive testing guide
- `IMPLEMENTATION_STATUS.md` - Current status and features

## Architecture

See [RUNC.md](RUNC.md) for the complete architecture and implementation details.

**Key insight:** Extract Docker image layers **once** when uploaded, store as rootfs directory, reuse read-only rootfs for every request.

## Handler Protocol

Your Docker image must implement this protocol:

1. Connect to `/control.sock` (Unix domain socket)
2. Receive TCP socket FD via SCM_RIGHTS
3. Handle the HTTP request
4. Exit cleanly

See `test_handler.py` for a complete example.

## Testing

```bash
# Automated test
sudo ./test.sh

# Manual testing
See TESTING.md for step-by-step guide
```

## Why runc Instead of containerd?

| Aspect | containerd | runc (this project) |
|--------|-----------|---------------------|
| Daemon | Required | None |
| Image storage | Complex (content-addressable) | Simple (directory) |
| Per-request overhead | Unpack layers + snapshot | Just create config.json |
| Cold start | ~100-200ms | ~10-50ms |
| Complexity | gRPC API, proto definitions | JSON config + CLI |
| Debugging | Requires ctr/crictl tools | Standard Unix tools |

**Decision:** Use runc for simplicity, speed, and transparency.

## Current Status

✅ **Implemented:**
- Docker image extraction and layer parsing
- OCI bundle creation
- Container lifecycle management
- SCM_RIGHTS socket passing
- HTTP Control API
- IP-based request routing
- Automatic IP configuration with labels (lo:faas)
- Automatic cleanup on shutdown
- Registry persistence

🔜 **Future enhancements:**
- Container pooling
- Metrics and monitoring
- Advanced security (seccomp, AppArmor)
- Request queueing

See [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) for complete details.

## License

This is an educational project exploring FaaS implementation with runc.

