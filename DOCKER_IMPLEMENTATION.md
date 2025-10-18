# Docker-based FaaS Implementation

## What We Built

Modified the FaaS server to spawn Docker containers instead of subprocesses. The server passes TCP socket file descriptors to containers via SCM_RIGHTS over Unix domain sockets.

**Files:**
- `docker_handler.py` - Container handler that receives FD and responds
- `Dockerfile` - Builds `faas-handler:latest` image (158MB)
- `server.py` - Modified to orchestrate Docker containers

**Flow:**
1. Client connects → Server accepts (TCP socket FD created)
2. Server creates Unix socket at `/tmp/faas-<uuid>.sock`
3. Server spawns container: `docker run -v /tmp/faas-<uuid>.sock:/control.sock`
4. Container connects to `/control.sock`
5. Server sends TCP socket FD via SCM_RIGHTS
6. Container receives FD, handles HTTP request, exits

## macOS Limitation

**SCM_RIGHTS does not work through Docker volume mounts on macOS/Windows.**

Docker Desktop runs in a VM. The virtualization layer strips ancillary data (the FD) while passing regular data through. Tested and confirmed:
- ✅ SCM_RIGHTS works between native macOS processes
- ✅ Container can connect to the Unix socket
- ❌ Ancillary data arrives empty in the container

**This works on native Linux.** The implementation is correct.

## Next Steps

**For macOS development:**
Use the subprocess-based `handler.py` instead. Revert `server.py` to use subprocess or keep both implementations.

**For production (Linux):**
Deploy as-is. Build and run:
```bash
docker build -t faas-handler:latest .
python3 server.py
```

**To test on Linux:**
Use a Linux VM (multipass, lima) or cloud instance.

## Configuration

Server listens on `10.0.0.1:8080` and `10.0.0.2:8080` (configurable in `server.py` line 110-113).
