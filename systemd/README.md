# Systemd Service Definitions

This directory contains systemd service files for all FaaS platform components.

## Services

### 1. wg-faas.service
WireGuard VPN interface for the FaaS platform. This service:
- Loads the WireGuard kernel module
- Creates the `wg-faas` network interface
- Assigns the server IPv6 address (fd00:faa5:0:100::1/64)
- Configures WireGuard with server settings
- Sets up routing for the entire fd00:faa5::/32 network
- Enables IPv6 forwarding

**Dependencies:** None (base service)
**Required by:** coredns.service, faasd.service

### 2. coredns.service
DNS server for function name resolution. This service:
- Runs CoreDNS bound to the WireGuard interface
- Serves DNS queries for *.faas domains
- Auto-reloads zone files for function updates
- Runs as unprivileged `coredns` user

**Dependencies:** wg-faas.service
**Required by:** faasd.service

### 3. faasd.service
Main FaaS platform daemon. This service:
- Manages function lifecycles
- Assigns IPv6 addresses to functions on wg-faas interface
- Handles HTTP requests and socket passing to containers
- Provides REST API for function management
- Updates DNS zone files for CoreDNS

**Dependencies:** wg-faas.service, coredns.service

## Service Dependency Chain

```
wg-faas.service (WireGuard)
    ↓ (required by)
coredns.service (DNS)
    ↓ (required by)
faasd.service (FaaS Daemon)
```

The dependency chain ensures:
1. WireGuard starts first and creates the wg-faas interface
2. CoreDNS starts second and binds to fd00:faa5:0:100::1:53
3. faasd starts last and assigns function IPs to wg-faas

## Installation

### Automatic Installation
If you installed via .deb/.rpm package or install.sh script, services are already installed.

### Manual Installation

1. **Copy service files:**
   ```bash
   sudo cp systemd/*.service /etc/systemd/system/
   ```

2. **Create required users:**
   ```bash
   # CoreDNS user
   sudo useradd -r -s /bin/false -d /var/lib/coredns coredns
   ```

3. **Create required directories:**
   ```bash
   sudo mkdir -p /var/lib/faasd/{dns,functions,images}
   sudo mkdir -p /etc/coredns
   sudo mkdir -p /run/faasd

   sudo chown -R coredns:coredns /var/lib/faasd/dns
   sudo chown -R root:root /var/lib/faasd/functions
   sudo chown -R root:root /var/lib/faasd/images
   ```

4. **Create WireGuard configuration:**
   ```bash
   sudo mkdir -p /etc/wireguard

   # Generate server keys
   wg genkey | sudo tee /etc/wireguard/server_private.key | \
       wg pubkey | sudo tee /etc/wireguard/server_public.key

   sudo chmod 600 /etc/wireguard/server_private.key
   sudo chmod 644 /etc/wireguard/server_public.key

   # Create basic WireGuard config
   PRIVATE_KEY=$(sudo cat /etc/wireguard/server_private.key)
   sudo tee /etc/wireguard/wg-faas.conf > /dev/null <<EOF
[Interface]
PrivateKey = $PRIVATE_KEY
ListenPort = 51820

# Peers will be added dynamically by faasd
EOF

   sudo chmod 600 /etc/wireguard/wg-faas.conf
   ```

5. **Create CoreDNS configuration:**
   ```bash
   sudo tee /etc/coredns/Corefile > /dev/null <<'EOF'
faas:53 {
    bind fd00:faa5:0:100::1
    file /var/lib/faasd/dns/faas.db {
        reload 2s
    }
    log
    errors
}
EOF

   # Create initial empty zone file
   sudo tee /var/lib/faasd/dns/faas.db > /dev/null <<'EOF'
$ORIGIN faas.
$TTL 60
@       IN  SOA ns.faas. admin.faas. (
            2024010100  ; Serial
            3600        ; Refresh
            1800        ; Retry
            604800      ; Expire
            60 )        ; Minimum TTL

@       IN  NS  ns.faas.
ns      IN  AAAA  fd00:faa5:0:100::1
EOF

   sudo chown coredns:coredns /var/lib/faasd/dns/faas.db
   ```

6. **Reload systemd and enable services:**
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable wg-faas.service
   sudo systemctl enable coredns.service
   sudo systemctl enable faasd.service
   ```

7. **Start services:**
   ```bash
   sudo systemctl start wg-faas.service
   sudo systemctl start coredns.service
   sudo systemctl start faasd.service
   ```

## Service Management

### Check Service Status
```bash
# Check all FaaS services
sudo systemctl status wg-faas.service
sudo systemctl status coredns.service
sudo systemctl status faasd.service

# Short status overview
sudo systemctl is-active wg-faas coredns faasd
```

### Start/Stop Services
```bash
# Start all services (in dependency order)
sudo systemctl start faasd.service  # Starts wg-faas and coredns automatically

# Stop all services
sudo systemctl stop faasd.service
sudo systemctl stop coredns.service
sudo systemctl stop wg-faas.service

# Restart faasd (dependencies remain running)
sudo systemctl restart faasd.service
```

### View Logs
```bash
# Follow logs in real-time
sudo journalctl -u faasd.service -f
sudo journalctl -u coredns.service -f
sudo journalctl -u wg-faas.service -f

# View recent logs
sudo journalctl -u faasd.service -n 100
sudo journalctl -u coredns.service -n 100

# View logs since boot
sudo journalctl -u faasd.service -b

# View logs for all FaaS services
sudo journalctl -u wg-faas.service -u coredns.service -u faasd.service -f
```

### Enable/Disable Auto-start
```bash
# Enable services to start on boot
sudo systemctl enable wg-faas.service
sudo systemctl enable coredns.service
sudo systemctl enable faasd.service

# Disable auto-start
sudo systemctl disable faasd.service
sudo systemctl disable coredns.service
sudo systemctl disable wg-faas.service
```

## Troubleshooting

### Service Won't Start

1. **Check service status and logs:**
   ```bash
   sudo systemctl status faasd.service
   sudo journalctl -u faasd.service -n 50
   ```

2. **Verify dependencies are running:**
   ```bash
   sudo systemctl is-active wg-faas coredns
   ```

3. **Check WireGuard interface exists:**
   ```bash
   ip -6 addr show dev wg-faas
   # Should show fd00:faa5:0:100::1/64
   ```

4. **Verify CoreDNS is listening:**
   ```bash
   sudo ss -tulpn | grep coredns
   # Should show listening on [fd00:faa5:0:100::1]:53
   ```

5. **Test DNS resolution:**
   ```bash
   dig @fd00:faa5:0:100::1 -p 53 test.faas AAAA
   ```

### IPv6 Forwarding Not Working

```bash
# Check IPv6 forwarding is enabled
sysctl net.ipv6.conf.all.forwarding
# Should return: net.ipv6.conf.all.forwarding = 1

# Enable if needed
sudo sysctl -w net.ipv6.conf.all.forwarding=1

# Make persistent
echo "net.ipv6.conf.all.forwarding=1" | sudo tee -a /etc/sysctl.conf
```

### WireGuard Module Not Loading

```bash
# Check if WireGuard module is available
sudo modprobe wireguard
lsmod | grep wireguard

# If missing, install WireGuard
# Ubuntu/Debian:
sudo apt-get install wireguard

# RHEL/Fedora:
sudo dnf install wireguard-tools
```

### Permissions Issues

```bash
# Fix DNS zone file permissions
sudo chown coredns:coredns /var/lib/faasd/dns/faas.db
sudo chmod 644 /var/lib/faasd/dns/faas.db

# Fix WireGuard config permissions
sudo chmod 600 /etc/wireguard/wg-faas.conf
sudo chmod 600 /etc/wireguard/server_private.key
```

### Service Restart Loop

If a service is restarting repeatedly:

```bash
# Check start limit status
sudo systemctl status faasd.service

# Reset start limit counter
sudo systemctl reset-failed faasd.service

# Check logs for error details
sudo journalctl -u faasd.service -n 200
```

## Security Considerations

### Service Hardening

All services include security hardening:
- **PrivateTmp**: Each service gets private /tmp
- **ProtectSystem**: Filesystem protection (read-only /usr, /boot)
- **ProtectHome**: /home directories are inaccessible
- **NoNewPrivileges**: Prevents privilege escalation
- **CapabilityBoundingSet**: Minimal required capabilities

### CoreDNS Security
- Runs as unprivileged `coredns` user
- Only CAP_NET_BIND_SERVICE capability (for binding port 53)
- Read-only access to /etc/coredns
- Read-write only to /var/lib/faasd/dns

### faasd Security
- Runs as root (required for container management and network configuration)
- NoNewPrivileges=no (needs to create containers)
- Private /tmp directory
- Read-write restricted to /var/lib/faasd and /run/faasd

### WireGuard Security
- Private key must be mode 600
- Configuration file must be mode 600
- Only root can read server private key

## Integration with Other Init Systems

### OpenRC (Alpine Linux)

See `openrc/` directory for OpenRC service scripts.

### runit (Void Linux)

See `runit/` directory for runit service scripts.

### systemd-nspawn Containers

Services can run inside systemd-nspawn containers with:
```bash
sudo systemd-nspawn -D /var/lib/machines/faas --boot
```

Ensure the container has CAP_NET_ADMIN for WireGuard.

## Performance Tuning

### Increase File Descriptor Limits

For high-traffic deployments, increase limits in service files:

```ini
[Service]
LimitNOFILE=1048576
LimitNPROC=4096
```

### Adjust Restart Policy

For critical production services, adjust restart behavior:

```ini
[Service]
Restart=always
RestartSec=5s
StartLimitInterval=0  # Disable start limit
```

### Resource Limits with cgroups

Limit CPU and memory for services:

```ini
[Service]
CPUQuota=200%  # 2 CPU cores max
MemoryMax=2G   # 2GB RAM max
```

## Monitoring

### Systemd Service Status

```bash
# Watch service status in real-time
watch -n 1 'systemctl status wg-faas coredns faasd | grep Active'

# Check if services are running
systemctl is-active wg-faas coredns faasd

# Check if services are enabled
systemctl is-enabled wg-faas coredns faasd
```

### Integration with Monitoring Tools

Services log to systemd journal, which can be exported to:
- **Prometheus**: Use `systemd_exporter` for service metrics
- **Grafana**: Journal data via Loki
- **Datadog**: Use datadog-agent with systemd integration
- **Splunk**: Forward journal logs with systemd-journal-upload

Example Prometheus query:
```promql
systemd_unit_state{name="faasd.service",state="active"}
```
