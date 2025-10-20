# FaaS Platform Deployment Guide

## Overview

This document describes the complete dependency chain, system requirements, and deployment process for a production faasd server with IPv6 networking, WireGuard VPN, and CoreDNS.

---

## System Architecture Dependencies

```
┌─────────────────────────────────────────────────────────────┐
│                    FaaS Platform Server                      │
│                                                              │
│  ┌────────────────────────────────────────────────────┐    │
│  │ Application Layer                                  │    │
│  │  - faasd.py (main daemon)                          │    │
│  │  - dns_manager.py (AAAA record management)         │    │
│  │  - vpn_manager.py (peer management)                │    │
│  │  - function containers (runc)                      │    │
│  └──────────────────┬─────────────────────────────────┘    │
│                     │                                        │
│  ┌──────────────────┴─────────────────────────────────┐    │
│  │ Service Layer                                      │    │
│  │  - CoreDNS (DNS resolver)                          │    │
│  │  - WireGuard (VPN server)                          │    │
│  │  - HTTP API (function deployment, VPN management)  │    │
│  └──────────────────┬─────────────────────────────────┘    │
│                     │                                        │
│  ┌──────────────────┴─────────────────────────────────┐    │
│  │ Container Runtime Layer                            │    │
│  │  - runc (OCI container runtime)                    │    │
│  │  - Docker (image extraction)                       │    │
│  └──────────────────┬─────────────────────────────────┘    │
│                     │                                        │
│  ┌──────────────────┴─────────────────────────────────┐    │
│  │ Kernel Layer                                       │    │
│  │  - Linux kernel (network namespaces, cgroups)      │    │
│  │  - IPv6 stack (forwarding, routing)                │    │
│  │  - WireGuard kernel module (or userspace)          │    │
│  │  - netfilter/ip6tables (firewall)                  │    │
│  └────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

---

## Dependencies by Layer

### 1. Operating System Requirements

**Linux Kernel:**
- Version: 5.6+ (for native WireGuard support)
- Kernel modules required:
  - `wireguard` (VPN)
  - `ip6_tables` (IPv6 firewall)
  - `nf_conntrack` (connection tracking)
  - Network namespace support
  - cgroups v2 (for runc resource limits)

**Supported Distributions:**
- Ubuntu 20.04 LTS or newer
- Debian 11 (Bullseye) or newer
- Fedora 32 or newer
- Arch Linux (rolling)

**Why:** Need modern kernel for WireGuard and good IPv6 support.

---

### 2. System Packages

#### Core Runtime

**Python 3.8+**
```bash
sudo apt install python3 python3-pip
```
- **Why:** faasd.py, dns_manager.py, vpn_manager.py are Python
- **Version requirement:** 3.8+ for socket.AF_INET6 improvements

**runc (OCI Runtime)**
```bash
sudo apt install runc
# Or install from GitHub releases
wget https://github.com/opencontainers/runc/releases/download/v1.1.12/runc.amd64
sudo install -m 755 runc.amd64 /usr/local/sbin/runc
```
- **Why:** Executes function containers
- **Usage:** Spawns isolated processes with namespaces

**Docker (Image Handling Only)**
```bash
sudo apt install docker.io
# Or use Docker CE
curl -fsSL https://get.docker.com | sh
```
- **Why:** Extract Docker image tarballs to rootfs
- **Usage:** `docker save` to export images, not for running containers
- **Note:** Could be replaced with custom tar extraction, but Docker makes it easy

#### Networking

**WireGuard**
```bash
sudo apt install wireguard wireguard-tools
```
- **Provides:** `wg`, `wg-quick` commands, kernel module
- **Why:** VPN server and client connectivity
- **Version:** 1.0.20210424 or newer

**iproute2**
```bash
sudo apt install iproute2
```
- **Provides:** `ip` command (ip link, ip addr, ip route)
- **Why:** Configure WireGuard interface, assign IPv6 addresses, set up routing
- **Usage:**
  - `ip link add wg0 type wireguard`
  - `ip -6 addr add fd00:faa5:0:100::1/64 dev wg0`
  - `ip -6 route add fd00:faa5::/32 dev wg0`

**iptables/ip6tables**
```bash
sudo apt install iptables
```
- **Why:** IPv6 firewall rules for WireGuard forwarding
- **Usage:**
  - `ip6tables -A FORWARD -i wg0 -j ACCEPT`
- **Optional:** Can use nftables instead on newer systems

#### DNS

**CoreDNS**
```bash
# Download binary
wget https://github.com/coredns/coredns/releases/download/v1.11.1/coredns_1.11.1_linux_amd64.tgz
tar xzf coredns_1.11.1_linux_amd64.tgz
sudo mv coredns /usr/local/bin/
sudo chmod +x /usr/local/bin/coredns
```
- **Why:** DNS resolver for `*.faas` domains
- **Version:** 1.10.0+ (any recent version works)
- **Plugins used:** `file` (zone files), `forward` (upstream DNS)

**resolvconf (Optional)**
```bash
sudo apt install resolvconf
```
- **Why:** DNS configuration management for VPN clients
- **Alternative:** systemd-resolved (built into systemd-based distros)
- **Usage:** Clients use this to set DNS server on VPN connection

#### Utilities

**curl**
```bash
sudo apt install curl
```
- **Why:** Testing HTTP endpoints, client downloads
- **Used by:** `./faas` client, testing scripts

**dig (dnsutils)**
```bash
sudo apt install dnsutils
```
- **Why:** DNS testing and troubleshooting
- **Usage:** `dig fibonacci.faas AAAA @fd00:faa5:0:100::1`

---

### 3. Python Dependencies

**Standard Library Only!**

The design intentionally uses **only Python standard library** to minimize dependencies:

- `socket` - Network programming (AF_INET6)
- `subprocess` - Run system commands (ip, wg, runc)
- `http.server` - HTTP API server
- `json` - Configuration and API payloads
- `pathlib` - File path handling
- `threading` - Concurrent request handling
- `select` - Multiplex socket connections
- `tarfile` - Extract Docker images
- `shutil` - File operations
- `uuid` - Generate unique IDs
- `argparse` - CLI argument parsing
- `os`, `sys` - System interface

**Optional (for client prettiness):**
```bash
pip3 install requests  # HTTP client (could use urllib instead)
```

**Why minimal dependencies?**
- ✅ Easy deployment (no pip install needed on server)
- ✅ Reproducible builds
- ✅ No dependency conflicts
- ✅ Works in restricted environments

---

## Privilege Requirements

### Root Access Needed For

1. **WireGuard configuration**
   - Create network interfaces: `ip link add wg0 type wireguard`
   - Assign IPv6 addresses: `ip -6 addr add ...`
   - Configure WireGuard: `wg setconf wg0 ...`

2. **Network configuration**
   - Enable IPv6 forwarding: `sysctl -w net.ipv6.conf.all.forwarding=1`
   - Configure firewall: `ip6tables -A FORWARD ...`
   - Add routes: `ip -6 route add ...`

3. **runc container execution**
   - Create namespaces (PID, network, mount, etc.)
   - Set up cgroups for resource limits
   - Mount filesystems in container namespace

4. **Listening on privileged ports**
   - Port 53 (DNS) - privileged port < 1024
   - Port 80 (HTTP) - privileged port < 1024
   - Alternative: Use capabilities or port forwarding

### Running as Non-Root (Advanced)

**Option 1: Capabilities**
```bash
# Allow binding to privileged ports without full root
sudo setcap 'cap_net_bind_service=+ep' /usr/bin/python3
sudo setcap 'cap_net_admin=+ep' $(which ip)
sudo setcap 'cap_net_admin=+ep' $(which wg)
```

**Option 2: Rootless containers**
- Use rootless runc (complex setup)
- Requires user namespaces
- Beyond scope of initial implementation

**Recommendation:** Run as root initially, add privilege separation later.

---

## Network Requirements

### Firewall Rules

**Inbound (Public):**
```bash
# WireGuard VPN
sudo ufw allow 51820/udp comment 'WireGuard VPN'

# Control API (localhost only - no public access needed!)
# Port 8080 should NOT be exposed publicly
```

**Outbound:**
```bash
# DNS queries (for CoreDNS upstream)
sudo ufw allow out 53/udp
sudo ufw allow out 53/tcp

# Docker image pulls (optional, for deployment)
sudo ufw allow out 443/tcp
```

**IPv6 Forwarding:**
```bash
# Enable in kernel
sudo sysctl -w net.ipv6.conf.all.forwarding=1
sudo sysctl -w net.ipv6.conf.default.forwarding=1

# Persist across reboots
echo "net.ipv6.conf.all.forwarding=1" | sudo tee -a /etc/sysctl.conf
```

**ip6tables Rules:**
```bash
# Allow WireGuard forwarding
sudo ip6tables -A FORWARD -i wg0 -j ACCEPT
sudo ip6tables -A FORWARD -o wg0 -j ACCEPT
sudo ip6tables -A FORWARD -m state --state RELATED,ESTABLISHED -j ACCEPT

# Save rules (Debian/Ubuntu)
sudo apt install iptables-persistent
sudo netfilter-persistent save
```

### DNS Configuration

**Server needs:**
- Public DNS resolution (for Docker pulls, updates)
- Should have working `/etc/resolv.conf`

**Server provides:**
- DNS server at `fd00:faa5:0:100::1` (VPN clients only)
- Does NOT need to be a public DNS server

### Public IP/Domain (for VPN Endpoint)

**Required:**
- Public IPv4 or IPv6 address (for WireGuard endpoint)
- OR: Dynamic DNS hostname

**Set via environment variable:**
```bash
export FAAS_VPN_ENDPOINT=faas.example.com
# Or
export FAAS_VPN_ENDPOINT=203.0.113.10
```

**Why:** Clients need to know where to connect to WireGuard server.

---

## Deployment Steps

### Phase 1: System Preparation

#### 1.1 Install Base Dependencies

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install core packages
sudo apt install -y \
    python3 \
    python3-pip \
    runc \
    docker.io \
    wireguard \
    wireguard-tools \
    iproute2 \
    iptables \
    curl \
    dnsutils

# Enable Docker (if needed for image extraction)
sudo systemctl enable docker
sudo systemctl start docker
```

#### 1.2 Verify Kernel Support

```bash
# Check WireGuard module
sudo modprobe wireguard
lsmod | grep wireguard
# Expected: wireguard module loaded

# Check IPv6 support
ip -6 addr show
# Expected: IPv6 addresses on interfaces

# Check network namespace support
unshare --net true
echo $?
# Expected: 0 (success)
```

#### 1.3 Configure IPv6 Forwarding

```bash
# Enable IPv6 forwarding
sudo sysctl -w net.ipv6.conf.all.forwarding=1
sudo sysctl -w net.ipv6.conf.default.forwarding=1

# Persist across reboots
echo "net.ipv6.conf.all.forwarding=1" | sudo tee -a /etc/sysctl.conf
echo "net.ipv6.conf.default.forwarding=1" | sudo tee -a /etc/sysctl.conf
```

---

### Phase 2: Service Installation

#### 2.1 Install CoreDNS

```bash
# Download CoreDNS
cd /tmp
wget https://github.com/coredns/coredns/releases/download/v1.11.1/coredns_1.11.1_linux_amd64.tgz
tar xzf coredns_1.11.1_linux_amd64.tgz

# Install binary
sudo mv coredns /usr/local/bin/
sudo chmod +x /usr/local/bin/coredns

# Verify installation
coredns -version
# Expected: CoreDNS-1.11.1
```

#### 2.2 Setup WireGuard Server

```bash
# Create directories
sudo mkdir -p /etc/wireguard/peers

# Generate server keypair
wg genkey | sudo tee /etc/wireguard/server_private.key | wg pubkey | sudo tee /etc/wireguard/server_public.key
sudo chmod 600 /etc/wireguard/server_private.key

# Create server config
sudo tee /etc/wireguard/wg0.conf > /dev/null <<'EOF'
[Interface]
Address = fd00:faa5:0:100::1/64
ListenPort = 51820
PrivateKey = $(cat /etc/wireguard/server_private.key)

# IPv6 forwarding and firewall
PostUp = sysctl -w net.ipv6.conf.all.forwarding=1
PostUp = ip6tables -A FORWARD -i wg0 -j ACCEPT
PostUp = ip6tables -A FORWARD -o wg0 -j ACCEPT

PostDown = ip6tables -D FORWARD -i wg0 -j ACCEPT
PostDown = ip6tables -D FORWARD -o wg0 -j ACCEPT

# Peer configs will be in /etc/wireguard/peers/*.conf
EOF

# Replace private key placeholder
sudo sed -i "s|\$(cat /etc/wireguard/server_private.key)|$(sudo cat /etc/wireguard/server_private.key)|" /etc/wireguard/wg0.conf

# Enable and start WireGuard
sudo systemctl enable wg-quick@wg0
sudo systemctl start wg-quick@wg0

# Verify
sudo wg show
# Expected: interface wg0 with public key, listening on port 51820
```

#### 2.3 Setup CoreDNS

```bash
# Create directories
sudo mkdir -p /etc/coredns
sudo mkdir -p /var/lib/faasd/dns

# Create CoreDNS configuration
sudo tee /etc/coredns/Corefile > /dev/null <<'EOF'
faas:53 {
    bind fd00:faa5:0:100::1

    file /var/lib/faasd/dns/faas.db {
        reload 2s
    }

    log
    errors
}

.:53 {
    bind fd00:faa5:0:100::1
    forward . 2001:4860:4860::8888 2606:4700:4700::1111
    log
    errors
}
EOF

# Create initial DNS zone file
sudo tee /var/lib/faasd/dns/faas.db > /dev/null <<'EOF'
$ORIGIN faas.
$TTL 60

@       IN  SOA ns.faas. admin.faas. (
            2025001 ; Serial
            3600    ; Refresh
            1800    ; Retry
            604800  ; Expire
            60 )    ; Minimum TTL

@       IN  NS  ns.faas.
EOF

# Create systemd service for CoreDNS
sudo tee /etc/systemd/system/coredns.service > /dev/null <<'EOF'
[Unit]
Description=CoreDNS DNS Server
Documentation=https://coredns.io
After=network.target
Wants=wg-quick@wg0.service

[Service]
Type=simple
ExecStart=/usr/local/bin/coredns -conf /etc/coredns/Corefile
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Enable and start CoreDNS
sudo systemctl daemon-reload
sudo systemctl enable coredns
sudo systemctl start coredns

# Verify
sudo systemctl status coredns
# Expected: active (running)
```

---

### Phase 3: FaaS Platform Installation

#### 3.1 Setup FaaS Directories

```bash
# Create faasd directories
sudo mkdir -p /var/lib/faasd/{images,bundles,dns}
sudo mkdir -p /opt/faas/{bin,lib}

# Set permissions
sudo chown -R root:root /var/lib/faasd
sudo chmod 755 /var/lib/faasd
```

#### 3.2 Install FaaS Platform Code

```bash
# Clone or copy repository
cd /opt/faas
# Assuming code is in this directory

# Copy Python modules
sudo cp faasd.py /opt/faas/bin/
sudo cp dns_manager.py /opt/faas/lib/
sudo cp vpn_manager.py /opt/faas/lib/

# Make executable
sudo chmod +x /opt/faas/bin/faasd.py

# Copy client tool
sudo cp faas /usr/local/bin/
sudo chmod +x /usr/local/bin/faas
```

#### 3.3 Create faasd systemd Service

```bash
# Create service file
sudo tee /etc/systemd/system/faasd.service > /dev/null <<'EOF'
[Unit]
Description=FaaS Daemon (runc-based serverless platform)
Documentation=https://github.com/yourorg/faas
After=network.target wg-quick@wg0.service coredns.service
Requires=wg-quick@wg0.service coredns.service

[Service]
Type=simple
WorkingDirectory=/opt/faas/bin
ExecStart=/usr/bin/python3 /opt/faas/bin/faasd.py
Restart=on-failure
RestartSec=10

# Environment
Environment=PYTHONPATH=/opt/faas/lib
Environment=FAAS_ROOT=/var/lib/faasd
Environment=FAAS_VPN_ENDPOINT=YOUR_PUBLIC_IP_OR_DOMAIN

# Security (run as root for now)
User=root
Group=root

[Install]
WantedBy=multi-user.target
EOF

# Edit to set your VPN endpoint
sudo sed -i 's/YOUR_PUBLIC_IP_OR_DOMAIN/faas.example.com/' /etc/systemd/system/faasd.service

# Reload systemd
sudo systemctl daemon-reload
```

#### 3.4 Start FaaS Platform

```bash
# Enable and start faasd
sudo systemctl enable faasd
sudo systemctl start faasd

# Check status
sudo systemctl status faasd
# Expected: active (running)

# Check logs
sudo journalctl -u faasd -f
# Expected: [init] faasd started successfully
```

---

### Phase 4: Verification

#### 4.1 Verify Services

```bash
# Check WireGuard
sudo wg show
# Expected: interface wg0 with fd00:faa5:0:100::1/64

# Check CoreDNS
sudo ss -lnp | grep coredns
# Expected: listening on [fd00:faa5:0:100::1]:53

# Check faasd
curl http://localhost:8080/api/list
# Expected: {} (empty list, no functions yet)

# Check IPv6 routing
ip -6 route show
# Expected: fd00:faa5:0:100::/64 dev wg0
```

#### 4.2 Test Function Deployment

```bash
# Build test function (fibonacci example)
cd /path/to/faas/functions/fibonacci
docker build -t fibonacci .
docker save fibonacci > /tmp/fibonacci.tar

# Deploy function
curl -X POST \
  -H "X-Image-Name: fibonacci" \
  --data-binary @/tmp/fibonacci.tar \
  http://localhost:8080/api/new

# Expected response:
# {
#   "name": "fibonacci",
#   "ip": "fd00:faa5:1:0::a",
#   "cmd": ["python3", "/app/handler.py"]
# }

# Verify function IP assigned to wg0
ip -6 addr show dev wg0
# Expected: fd00:faa5:1:0::a/128 assigned

# Verify DNS record
dig fibonacci.faas AAAA @fd00:faa5:0:100::1 +short
# Expected: fd00:faa5:1:0::a
```

#### 4.3 Test VPN Client

```bash
# On client machine, create VPN connection
./faas vpn connect

# Expected:
# - Generates keypair
# - Registers with server
# - Configures wg-faas interface
# - Tests connectivity
# ✅ Connected!

# Test function access
curl http://fibonacci.faas/?n=10
# Expected: Fibonacci sequence (10 steps):
#           0, 1, 1, 2, 3, 5, 8, 13, 21, 34

# Disconnect
./faas vpn disconnect
```

---

## Monitoring and Maintenance

### Service Health Checks

```bash
# Check all services
sudo systemctl status wg-quick@wg0 coredns faasd

# View logs
sudo journalctl -u wg-quick@wg0 -f
sudo journalctl -u coredns -f
sudo journalctl -u faasd -f

# Check WireGuard peers
sudo wg show wg0

# Check DNS zone
cat /var/lib/faasd/dns/faas.db

# Check function containers
sudo runc list

# Check network configuration
ip -6 addr show dev wg0
ip -6 route show
```

### Resource Usage

```bash
# Check disk usage (images can be large)
du -sh /var/lib/faasd/images/*
du -sh /var/lib/faasd/bundles/*

# Check memory usage
ps aux | grep -E 'coredns|faasd|runc'

# Check network statistics
sudo wg show wg0 transfer
```

### Backup

**Critical files to backup:**
```bash
# WireGuard keys (CRITICAL - cannot regenerate!)
/etc/wireguard/server_private.key
/etc/wireguard/server_public.key

# FaaS registry (function metadata)
/var/lib/faasd/registry.json

# DNS zone (can be regenerated from registry)
/var/lib/faasd/dns/faas.db

# VPN peer configs (can be regenerated)
/etc/wireguard/peers/*.conf

# Function images (large, can be redeployed)
/var/lib/faasd/images/*/rootfs
```

**Backup command:**
```bash
sudo tar czf faasd-backup-$(date +%Y%m%d).tar.gz \
  /etc/wireguard/server_*.key \
  /var/lib/faasd/registry.json \
  /var/lib/faasd/dns/faas.db \
  /etc/wireguard/peers/
```

---

## Troubleshooting

### WireGuard Issues

**Problem: Interface won't start**
```bash
# Check kernel module
sudo modprobe wireguard
lsmod | grep wireguard

# Check config syntax
sudo wg-quick strip wg0

# Check for port conflicts
sudo ss -lunp | grep 51820
```

**Problem: Clients can't connect**
```bash
# Check firewall
sudo ufw status
sudo ufw allow 51820/udp

# Check endpoint is reachable
# On client:
ping YOUR_SERVER_IP
nc -u YOUR_SERVER_IP 51820
```

### CoreDNS Issues

**Problem: DNS not resolving**
```bash
# Check CoreDNS is listening
sudo ss -lnp | grep :53

# Check zone file syntax
coredns -conf /etc/coredns/Corefile -plugins | grep file

# Test directly
dig @fd00:faa5:0:100::1 fibonacci.faas AAAA

# Check CoreDNS logs
sudo journalctl -u coredns --no-pager -n 50
```

### Function Deployment Issues

**Problem: Container fails to start**
```bash
# Check runc
runc --version

# Check container logs
sudo journalctl -u faasd -n 100 | grep "Container stderr"

# Test runc manually
cd /var/lib/faasd/bundles/faas-*
sudo runc run test-container
```

**Problem: Socket FD passing fails**
```bash
# Check control socket exists
ls -la /tmp/*.sock

# Check container can access socket
# In config.json, verify mount:
cat config.json | jq '.mounts[] | select(.destination=="/control.sock")'
```

### IPv6 Issues

**Problem: IPv6 forwarding not working**
```bash
# Check kernel parameter
sysctl net.ipv6.conf.all.forwarding
# Should be: 1

# Check ip6tables rules
sudo ip6tables -L FORWARD -v

# Test routing
ip -6 route get fd00:faa5:1:0::a
# Should route via wg0
```

---

## Security Considerations

### Minimal Attack Surface

**Exposed ports:**
- 51820/udp - WireGuard (encrypted, authenticated)

**NOT exposed:**
- 8080/tcp - Control API (localhost only)
- 53/tcp+udp - CoreDNS (VPN only, not public)
- 80/tcp - Functions (VPN only, not public)

### Secure Defaults

1. **WireGuard:** All VPN traffic encrypted with ChaCha20-Poly1305
2. **Read-only rootfs:** Function containers use read-only root filesystem
3. **Namespace isolation:** Each function runs in isolated PID, network, mount namespaces
4. **Resource limits:** cgroups enforce memory (512MB) and CPU quotas
5. **Private keys never transmitted:** Clients generate keys locally

### Hardening (Optional)

```bash
# Restrict SSH access
sudo ufw allow from TRUSTED_IP to any port 22

# Enable fail2ban
sudo apt install fail2ban

# Regular updates
sudo apt update && sudo apt upgrade
sudo systemctl restart faasd  # After updates

# Audit logs
sudo ausearch -m avc -ts recent  # SELinux/AppArmor denials
```

---

## Summary

### Complete Dependency List

**System packages:**
- Python 3.8+
- runc
- Docker
- WireGuard
- iproute2
- iptables
- CoreDNS (manual install)

**Python libraries:**
- Standard library only (no pip packages required)

**Kernel requirements:**
- Linux 5.6+
- WireGuard module
- IPv6 support
- Network namespaces
- cgroups v2

**Network requirements:**
- Public IP or DDNS for WireGuard endpoint
- Outbound HTTPS (for Docker pulls)
- Inbound UDP 51820 (for WireGuard)

### Service Startup Order

1. **Kernel modules** (loaded at boot)
2. **WireGuard** (`wg-quick@wg0.service`) - Creates VPN interface
3. **CoreDNS** (`coredns.service`) - Binds to VPN IP for DNS
4. **faasd** (`faasd.service`) - Assigns function IPs to WireGuard interface

### Deployment Checklist

- [ ] Ubuntu 20.04+ or equivalent installed
- [ ] All system packages installed
- [ ] IPv6 forwarding enabled
- [ ] WireGuard server configured and running
- [ ] CoreDNS installed and running
- [ ] faasd installed and running
- [ ] Firewall configured (allow 51820/udp)
- [ ] VPN endpoint set in faasd.service
- [ ] Test function deployed
- [ ] VPN client connection tested
- [ ] DNS resolution working
- [ ] Function HTTP request successful

The platform is production-ready when all services are running and the test function responds via VPN! 🚀
