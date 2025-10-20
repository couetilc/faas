# Dynamic DNS for FaaS with WireGuard VPN (IPv6-Only)

## Goal

Provide simple, robust DNS resolution for FaaS function endpoints on a single-node deployment, accessible via WireGuard VPN. Maintain the zero-copy socket passing architecture while enabling domain-based access.

**Network Architecture:** IPv6-only using `fd00:faa5::/32` address space for all FaaS networking.

## Core Problem

**Current State:**
- Functions accessible at IPv4 addresses: `curl http://10.0.0.12/?n=10`
- IPs bound to loopback interface (lo)
- No DNS resolution
- No remote access (IPs only work locally)
- IPv4-only networking

**Desired State:**
- Functions accessible via domain names: `curl http://fibonacci.faas/?n=10`
- Accessible remotely via secure IPv6 VPN (`fd00:faa5::/32`)
- Automatic DNS registration on function deployment
- Simple client API: `./faas vpn create`
- IPv6-only for future-proof networking and massive address space

## Design Principles

1. **Simplicity First** - Minimal dependencies, straightforward configuration
2. **Layer 4 Only** - No HTTP reverse proxy, maintain zero-copy architecture
3. **Single Node** - Not distributed, optimized for single-server deployment
4. **Dynamic Registration** - Functions auto-register on deployment
5. **Client-Friendly** - Dead simple VPN setup and connection
6. **IPv6-Only** - Future-proof with massive address space, no IPv4 exhaustion concerns

---

## IPv6 Address Plan: `fd00:faa5::/32`

The `fd00:faa5::/32` prefix provides our entire FaaS platform with a memorable, project-specific address space.

### Address Hierarchy

```
fd00:faa5::/32 - FaaS Platform Root (entire allocation)
│
├── fd00:faa5:0::/48 - Infrastructure
│   │
│   ├── fd00:faa5:0:100::/64 - WireGuard VPN Network
│   │   ├── fd00:faa5:0:100::1      - VPN Server (WireGuard + CoreDNS)
│   │   ├── fd00:faa5:0:100::a      - VPN Client 1
│   │   ├── fd00:faa5:0:100::b      - VPN Client 2
│   │   └── fd00:faa5:0:100::ffff   - Up to 65k clients
│   │
│   └── fd00:faa5:0:200::/64 - Reserved (future infrastructure)
│
└── fd00:faa5:1::/48 - Functions
    │
    ├── fd00:faa5:1:0::/64 - Default Deployment
    │   ├── fd00:faa5:1:0::a     - fibonacci function
    │   ├── fd00:faa5:1:0::b     - hello function
    │   ├── fd00:faa5:1:0::c     - api function
    │   └── ...
    │
    ├── fd00:faa5:1:1::/64 - Deployment 1 (multi-tenant future)
    ├── fd00:faa5:1:2::/64 - Deployment 2
    └── fd00:faa5:1:ffff::/64 - Up to 65k deployments
```

### Why This Structure?

**`fd00:faa5::`** - Memorable prefix matching "FaaS" project
- ULA (Unique Local Address) range, equivalent to private IPv4 (10.0.0.0/8)
- Private, not globally routed

**`/32` allocation** - Gives us 65,536 /48 networks
- Massive scalability headroom
- Clean hierarchical organization

**`0::/48` for infrastructure** - VPN, DNS, management services
- Separate from function network
- Easy firewall rules

**`1::/48` for functions** - All function endpoints
- Each deployment gets a `/64` subnet (18 quintillion addresses!)
- Hex addressing (`::a`, `::b`, `::c`) is cleaner than decimal

**`/64` subnets** - Standard IPv6 subnet size
- Allows SLAAC if ever needed
- Follows IPv6 best practices

### Address Examples

```
VPN Server:        fd00:faa5:0:100::1
VPN Client:        fd00:faa5:0:100::a
Function:          fd00:faa5:1:0::a
Multi-tenant:      fd00:faa5:1:5:fc::10
```

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                      FaaS Platform Server                         │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ WireGuard Server (wg0)                                  │    │
│  │ VPN Network: fd00:faa5:0:100::/64                       │    │
│  │ Server IPv6: fd00:faa5:0:100::1/64                      │    │
│  │                                                          │    │
│  │ Function IPv6s (assigned to wg0):                       │    │
│  │   fd00:faa5:1:0::a/128 → fibonacci                      │    │
│  │   fd00:faa5:1:0::b/128 → hello                          │    │
│  │   fd00:faa5:1:0::c/128 → api                            │    │
│  └──────────────────────┬──────────────────────────────────┘    │
│                         │                                         │
│  ┌──────────────────────┴──────────────────────────────────┐    │
│  │ CoreDNS (IPv6-only)                                     │    │
│  │ Listen: [fd00:faa5:0:100::1]:53                         │    │
│  │ Zone: faas                                              │    │
│  │ Backend: File plugin (/var/lib/faasd/dns/faas.db)      │    │
│  └──────────────────────┬──────────────────────────────────┘    │
│                         │                                         │
│  ┌──────────────────────┴──────────────────────────────────┐    │
│  │ faasd (IPv6-enabled)                                    │    │
│  │ - Manages function deployments                          │    │
│  │ - Allocates IPv6 from fd00:faa5:1:0::/64                │    │
│  │ - Assigns IPv6 to wg0 interface                         │    │
│  │ - Updates DNS zone file (AAAA records)                  │    │
│  │ - Manages VPN client configs                            │    │
│  └─────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────┘

                        ↕ Encrypted IPv6 VPN Tunnel

┌──────────────────────────────────────────────────────────────────┐
│                         User Machine                              │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ WireGuard Client                                        │    │
│  │ VPN IPv6: fd00:faa5:0:100::a/64                         │    │
│  │ DNS Server: fd00:faa5:0:100::1                          │    │
│  │ Routes: fd00:faa5::/32 (all FaaS traffic)               │    │
│  └──────────────────────┬───────────────────────────────────┘    │
│                         │                                         │
│  ┌──────────────────────┴───────────────────────────────────┐    │
│  │ Application (curl, browser, etc.)                        │    │
│  │                                                           │    │
│  │ curl http://fibonacci.faas/?n=10                         │    │
│  │   → DNS query to fd00:faa5:0:100::1                      │    │
│  │   → Resolves to fd00:faa5:1:0::a (AAAA record)           │    │
│  │   → TCP connect through VPN tunnel                       │    │
│  │   → Direct IPv6 connection to function                   │    │
│  └──────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────┘
```

---

## Key Design Decisions

### 1. Function IPv6 Addresses on WireGuard Interface

**Problem:** Function IPs on loopback (lo) are not routable from remote machines.

**Solution:** Assign function IPv6 addresses to the WireGuard interface (wg0).

```python
# Current (IPv4 on loopback - faasd.py:448)
subprocess.run(['ip', 'addr', 'add', f'{ip}/24', 'dev', 'lo', 'label', 'lo:faas'])

# New (IPv6 on WireGuard)
subprocess.run(['ip', '-6', 'addr', 'add', f'{ipv6}/128', 'dev', 'wg0'])
```

**Why it works:**
- WireGuard interface is routable (not loopback)
- Function IPv6 addresses become directly accessible through VPN tunnel
- No NAT needed (pure IPv6 end-to-end)
- No routing tables needed (routes via wg0)
- Maintains direct socket passing (zero-copy)

**Lifecycle:**
1. WireGuard starts first → wg0 interface created with fd00:faa5:0:100::1/64
2. faasd starts → checks for wg0 interface
3. faasd assigns function IPv6s to wg0 (fd00:faa5:1:0::a/128, ::b/128, etc.)
4. Functions become accessible via VPN

**IPv6 Advantages:**
- Massive address space (no exhaustion)
- `/128` for individual hosts (equivalent to IPv4 `/32`)
- Cleaner hex addressing (`::a`, `::b` vs `10`, `11`)
- Future-proof networking

### 2. CoreDNS with File Backend (IPv6-Only)

**No etcd required** - Use simple zone files for DNS records.

**Corefile:**
```
faas:53 {
    bind fd00:faa5:0:100::1

    file /var/lib/faasd/dns/faas.db {
        reload 2s
    }

    log
    errors
}

# Forward all other queries (IPv6 DNS servers)
.:53 {
    bind fd00:faa5:0:100::1
    forward . 2001:4860:4860::8888 2606:4700:4700::1111
    log
    errors
}
```

**Zone file format** (/var/lib/faasd/dns/faas.db):
```
$ORIGIN faas.
$TTL 60

@       IN  SOA ns.faas. admin.faas. (
            2025001 ; Serial
            3600    ; Refresh
            1800    ; Retry
            604800  ; Expire
            60 )    ; Minimum TTL

@       IN  NS  ns.faas.

; Function IPv6 records (auto-managed by faasd) - AAAA instead of A
fibonacci   IN  AAAA   fd00:faa5:1:0::a
hello       IN  AAAA   fd00:faa5:1:0::b
api         IN  AAAA   fd00:faa5:1:0::c
```

**Why file backend:**
- ✅ Simple - just write to a file
- ✅ No external dependencies (etcd, Redis, etc.)
- ✅ Human-readable and debuggable
- ✅ Auto-reload on change (CoreDNS watches file)
- ✅ Atomic updates (write to temp file, then rename)

**faasd DNS management (IPv6):**
```python
class DNSZoneManager:
    """Manages DNS zone file for function resolution (IPv6-only)."""

    def __init__(self, zone_file="/var/lib/faasd/dns/faas.db"):
        self.zone_file = zone_file
        self.serial = self._read_serial()

    def add_record(self, name, ipv6):
        """Add AAAA record for function."""
        records = self._read_records()
        records[name] = ipv6
        self._write_zone(records)

    def remove_record(self, name):
        """Remove AAAA record for function."""
        records = self._read_records()
        if name in records:
            del records[name]
            self._write_zone(records)

    def _write_zone(self, records):
        """Atomically write zone file with updated records."""
        self.serial += 1

        zone_content = f"""$ORIGIN faas.
$TTL 60

@       IN  SOA ns.faas. admin.faas. (
            {self.serial} ; Serial
            3600    ; Refresh
            1800    ; Retry
            604800  ; Expire
            60 )    ; Minimum TTL

@       IN  NS  ns.faas.

"""
        # Add function IPv6 records (AAAA)
        for name, ipv6 in sorted(records.items()):
            zone_content += f"{name:<15} IN  AAAA  {ipv6}\n"

        # Atomic write: write to temp file, then rename
        temp_file = f"{self.zone_file}.tmp"
        with open(temp_file, 'w') as f:
            f.write(zone_content)

        os.rename(temp_file, self.zone_file)
        # CoreDNS will detect change and reload within 2s
```

### 3. WireGuard Configuration (IPv6-Only)

**Server config** (/etc/wireguard/wg0.conf):
```ini
[Interface]
Address = fd00:faa5:0:100::1/64
ListenPort = 51820
PrivateKey = <server_private_key>

# IPv6 forwarding and routing
PostUp = sysctl -w net.ipv6.conf.all.forwarding=1
PostUp = ip6tables -A FORWARD -i wg0 -j ACCEPT
PostUp = ip6tables -A FORWARD -o wg0 -j ACCEPT

PostDown = ip6tables -D FORWARD -i wg0 -j ACCEPT
PostDown = ip6tables -D FORWARD -o wg0 -j ACCEPT

# Client peers (dynamically managed by faasd)
# Will be in /etc/wireguard/peers/*.conf and included
```

**Client config generation (IPv6):**
```python
class VPNManager:
    """Manages WireGuard VPN client configurations (IPv6-only)."""

    def __init__(self):
        self.server_public_key = self._get_server_public_key()
        self.server_endpoint = self._get_server_endpoint()
        self.next_client_id = 0xa  # Start from hex 'a' (10 decimal)

    def create_client_config(self, client_name):
        """Generate WireGuard config for a client."""

        # Generate client keys
        private_key = self._generate_private_key()
        public_key = self._derive_public_key(private_key)

        # Allocate client IPv6 (hex notation)
        client_ipv6 = f"fd00:faa5:0:100::{self.next_client_id:x}"
        self.next_client_id += 1

        # Add peer to server config
        self._add_peer_to_server(client_name, public_key, client_ipv6)

        # Generate client config
        client_config = f"""[Interface]
PrivateKey = {private_key}
Address = {client_ipv6}/64
DNS = fd00:faa5:0:100::1

[Peer]
PublicKey = {self.server_public_key}
Endpoint = {self.server_endpoint}:51820
AllowedIPs = fd00:faa5::/32
PersistentKeepalive = 25
"""

        return client_config

    def _add_peer_to_server(self, name, public_key, ipv6):
        """Add peer to WireGuard server config."""
        peer_config = f"""# Client: {name}
[Peer]
PublicKey = {public_key}
AllowedIPs = {ipv6}/128
"""

        peer_file = f"/etc/wireguard/peers/{name}.conf"
        with open(peer_file, 'w') as f:
            f.write(peer_config)

        # Reload WireGuard
        subprocess.run(['wg', 'syncconf', 'wg0',
                       '<(cat /etc/wireguard/wg0.conf /etc/wireguard/peers/*.conf)'],
                      shell=True, executable='/bin/bash')
```

### 4. IPv6 Network Ranges (`fd00:faa5::/32`)

**fd00:faa5:0:100::/64** - VPN network (WireGuard clients)
- fd00:faa5:0:100::1 - Server (WireGuard + CoreDNS)
- fd00:faa5:0:100::a-ffff - VPN clients (hex addressing)

**fd00:faa5:1:0::/64** - Function network (default deployment)
- fd00:faa5:1:0::a-ffff - Function IPv6 addresses (assigned to wg0)

**Why separate `/48` networks:**
- Clean separation of infrastructure (0::/48) vs. functions (1::/48)
- Easy firewall rules (`ip6tables` by network)
- Clear routing intent
- Scalable to 65k deployments (each gets own /64)

**Why hex addressing:**
- `::a`, `::b`, `::c` is cleaner than `::10`, `::11`, `::12`
- Natural for IPv6
- Easy to read and type

---

## Client API: Integrated VPN Management

The `./faas vpn` command provides **seamless, one-command VPN setup** - no manual WireGuard commands required. The client handles everything: key generation, server registration, interface configuration, routing, and DNS setup.

### Design Philosophy

**Zero manual steps:** User runs `./faas vpn connect`, and they're connected. No `wg-quick`, no config files to copy, no separate commands.

**Direct WireGuard control:** Uses `ip` and `wg` commands directly instead of `wg-quick` for fine-grained control.

**Smart defaults:** Single unnamed "default" configuration for simple use cases, optional named configs for multi-device scenarios.

---

### Command: `./faas vpn connect [name]`

**Purpose:** Create and activate VPN connection in one command.

**What it does:**
1. Check if configuration exists, create if not
2. Generate WireGuard keypair locally
3. Register with faasd server (allocates IPv6)
4. Configure WireGuard interface (`wg-faas`)
5. Set up IPv6 routing for `fd00:faa5::/32`
6. Configure DNS to use `fd00:faa5:0:100::1`
7. Test connectivity (ping, DNS, HTTP)
8. Report success

**Example (first time):**
```bash
$ ./faas vpn connect

╭─────────────────────────────────────────────╮
│  FaaS VPN Connection                        │
╰─────────────────────────────────────────────╯

⚙  Checking existing configuration...
   No config found, creating new one...

🔑 Generating WireGuard keypair...
📡 Registering with server...
   Allocated IPv6: fd00:faa5:0:100::a

🔧 Configuring WireGuard interface...
   [✓] Created interface wg-faas
   [✓] Assigned IPv6: fd00:faa5:0:100::a/64
   [✓] Added peer: server
   [✓] Set MTU: 1420

🌐 Configuring routing...
   [✓] Added route: fd00:faa5::/32 via wg-faas

🔍 Configuring DNS...
   [✓] DNS server: fd00:faa5:0:100::1

🧪 Testing connectivity...
   [✓] Ping VPN server: 2.3ms
   [✓] DNS resolution: fibonacci.faas → fd00:faa5:1:0::a
   [✓] HTTP test: server is reachable

✅ Connected! Your FaaS VPN is active.

Configuration saved as: default
VPN Interface: wg-faas
Your IPv6: fd00:faa5:0:100::a

Try it:
  curl http://fibonacci.faas/?n=10

To disconnect:
  ./faas vpn disconnect
```

**Example (already configured):**
```bash
$ ./faas vpn connect laptop

⚙  Found existing config: laptop
🔧 Activating WireGuard interface...
   [✓] Created interface wg-faas
   [✓] Assigned IPv6: fd00:faa5:0:100::b/64
   ...
✅ Connected!
```

**Named configurations:**
```bash
# Create separate configs for different devices
./faas vpn connect laptop
./faas vpn connect desktop
./faas vpn connect phone
```

**Behind the scenes:**
1. **Client generates keypair** (never sends private key to server):
   ```bash
   wg genkey → private_key
   echo private_key | wg pubkey → public_key
   ```

2. **Client → Server API call:**
   ```http
   POST /api/vpn/create
   Content-Type: application/json

   {
     "name": "default",
     "public_key": "xY2zA3bC4dE5fG..."
   }
   ```

3. **Server responds:**
   ```json
   {
     "ipv6": "fd00:faa5:0:100::a",
     "server_public_key": "aB1cD2eF3gH...",
     "endpoint": "faas.example.com"
   }
   ```

4. **Client configures interface directly:**
   ```bash
   sudo ip link add wg-faas type wireguard
   sudo ip -6 addr add fd00:faa5:0:100::a/64 dev wg-faas
   sudo wg setconf wg-faas <(echo "[Interface]
   PrivateKey = ...
   [Peer]
   PublicKey = ...
   Endpoint = faas.example.com:51820
   AllowedIPs = fd00:faa5::/32")
   sudo ip link set mtu 1420 up dev wg-faas
   sudo ip -6 route add fd00:faa5::/32 dev wg-faas
   ```

5. **Client configures DNS** (uses resolvconf or systemd-resolved):
   ```bash
   # Via resolvconf
   echo "nameserver fd00:faa5:0:100::1" | sudo resolvconf -a wg-faas

   # Or via systemd-resolved
   sudo resolvectl dns wg-faas fd00:faa5:0:100::1
   sudo resolvectl domain wg-faas ~faas
   ```

6. **Client saves config locally:**
   ```
   ~/.config/faas/vpn/default.json
   ```

---

### Command: `./faas vpn disconnect [name]`

**Purpose:** Disconnect VPN and clean up interface.

**What it does:**
1. Remove DNS configuration
2. Delete IPv6 routes
3. Delete WireGuard interface
4. Leave local config intact (for reconnecting)

**Example:**
```bash
$ ./faas vpn disconnect

Disconnecting FaaS VPN...

✅ Disconnected.
```

**Behind the scenes:**
```bash
sudo resolvconf -d wg-faas
sudo ip -6 route del fd00:faa5::/32 dev wg-faas
sudo ip link delete wg-faas
```

---

### Command: `./faas vpn status`

**Purpose:** Show current VPN connection status and statistics.

**Example:**
```bash
$ ./faas vpn status

╭─────────────────────────────────────────────╮
│  FaaS VPN Status                            │
╰─────────────────────────────────────────────╯

Status: ✅ Connected

Your IPv6: fd00:faa5:0:100::a

Interface: wg-faas
Server: faas.example.com:51820
Last handshake: 23 seconds ago
Transfer: 1.2 MiB received, 384 KiB sent

Connectivity: ✅ Active

To disconnect: ./faas vpn disconnect
```

**When not connected:**
```bash
$ ./faas vpn status

Status: Not connected

To connect: ./faas vpn connect
```

---

### Command: `./faas vpn list`

**Purpose:** List all saved VPN configurations.

**Example:**
```bash
$ ./faas vpn list

Saved VPN Configurations:
┌──────────────┬────────────────────────┬──────────┐
│ Name         │ IPv6                   │ Status   │
├──────────────┼────────────────────────┼──────────┤
│ default      │ fd00:faa5:0:100::a     │ active   │
│ laptop       │ fd00:faa5:0:100::b     │ saved    │
│ phone        │ fd00:faa5:0:100::c     │ saved    │
└──────────────┴────────────────────────┴──────────┘
```

**Status values:**
- **active** - Currently connected (interface exists)
- **saved** - Configuration exists but not connected

---

### Command: `./faas vpn remove [name]`

**Purpose:** Delete VPN configuration and revoke server access.

**What it does:**
1. Disconnect if currently active
2. Delete peer from server's WireGuard config
3. Delete local configuration file
4. Free IPv6 address on server

**Example:**
```bash
$ ./faas vpn remove laptop

Disconnecting laptop...

✅ Removed VPN configuration: laptop
```

**Behind the scenes:**
```
1. If connected: ./faas vpn disconnect laptop
2. Client → Server: DELETE /api/vpn/remove/laptop
3. Server removes /etc/wireguard/peers/laptop.conf
4. Server runs: wg syncconf wg0
5. Client deletes ~/.config/faas/vpn/laptop.json
```

---

### Configuration Storage

**Client-side:**
```
~/.config/faas/vpn/
├── default.json      # Default unnamed config
├── laptop.json       # Named config: laptop
└── phone.json        # Named config: phone
```

**Config file format** (`~/.config/faas/vpn/default.json`):
```json
{
  "name": "default",
  "private_key": "cPqL8vVjkE7hN3mR9sT...",
  "public_key": "xY2zA3bC4dE5fG6hI7jK...",
  "client_ipv6": "fd00:faa5:0:100::a",
  "server_public_key": "aB1cD2eF3gH4iJ5kL...",
  "server_endpoint": "faas.example.com",
  "server_ipv6": "fd00:faa5:0:100::1",
  "allowed_ips": "fd00:faa5::/32",
  "dns": "fd00:faa5:0:100::1"
}
```

**Server-side:**
```
/etc/wireguard/peers/
├── default.conf      # Peer config for default
├── laptop.conf       # Peer config for laptop
└── phone.conf        # Peer config for phone
```

**Peer config format** (`/etc/wireguard/peers/default.conf`):
```ini
# Client: default
[Peer]
PublicKey = xY2zA3bC4dE5fG6hI7jK...
AllowedIPs = fd00:faa5:0:100::a/128
```

---

### Complete Workflow Example

**First-time setup and usage:**

```bash
# 1. User deploys a function
./faas new fibonacci
# Output: Deployed fibonacci at fd00:faa5:1:0::a
#         DNS: fibonacci.faas → fd00:faa5:1:0::a

# 2. User connects to VPN (one command!)
./faas vpn connect
# Output: [Creates config, configures interface, tests connectivity]
#         ✅ Connected! Your FaaS VPN is active.

# 3. User accesses function via DNS
curl http://fibonacci.faas/?n=10
# Output: Fibonacci sequence (10 steps):
#         0, 1, 1, 2, 3, 5, 8, 13, 21, 34

# 4. User checks status
./faas vpn status
# Output: Status: ✅ Connected
#         Your IPv6: fd00:faa5:0:100::a

# 5. User disconnects
./faas vpn disconnect
# Output: ✅ Disconnected.

# 6. User reconnects later (uses saved config)
./faas vpn connect
# Output: ⚙  Found existing config: default
#         ✅ Connected!
```

**Multi-device workflow:**

```bash
# On laptop
./faas vpn connect laptop
# Gets: fd00:faa5:0:100::a

# On desktop
./faas vpn connect desktop
# Gets: fd00:faa5:0:100::b

# On phone (generate config for mobile app)
./faas vpn connect phone
# Gets: fd00:faa5:0:100::c

# List all configs
./faas vpn list
# Shows: laptop (active), desktop (saved), phone (saved)

# Remove old device
./faas vpn remove old-laptop
```

---

### Server API Endpoints

The faasd server exposes these endpoints for VPN management:

#### POST `/api/vpn/create`

Create new VPN peer and allocate IPv6.

**Request:**
```json
{
  "name": "laptop",
  "public_key": "xY2zA3bC4dE5fG6hI7jK..."
}
```

**Response:**
```json
{
  "ipv6": "fd00:faa5:0:100::a",
  "server_public_key": "aB1cD2eF3gH4iJ5kL...",
  "endpoint": "faas.example.com"
}
```

**Implementation:**
```python
def _handle_vpn_create(self):
    """Create new VPN peer."""
    length = int(self.headers.get('Content-Length', 0))
    body = json.loads(self.rfile.read(length))

    name = body['name']
    public_key = body['public_key']

    # Allocate IPv6 (fd00:faa5:0:100::a, ::b, ::c, ...)
    client_ipv6 = self.server.vpn_manager.allocate_ipv6()

    # Add peer to WireGuard server
    self.server.vpn_manager.add_peer(name, public_key, client_ipv6)

    # Get server info
    server_public_key = self.server.vpn_manager.get_server_public_key()
    server_endpoint = os.getenv('FAAS_VPN_ENDPOINT', 'localhost')

    # Respond
    self.send_response(200)
    self.send_header('Content-Type', 'application/json')
    self.end_headers()

    response = json.dumps({
        'ipv6': client_ipv6,
        'server_public_key': server_public_key,
        'endpoint': server_endpoint
    })
    self.wfile.write(response.encode())

    print(f"[vpn] Created peer: {name} → {client_ipv6}")
```

#### DELETE `/api/vpn/remove/{name}`

Remove VPN peer and free IPv6.

**Response:** 200 OK (empty body)

**Implementation:**
```python
def _handle_vpn_remove(self):
    """Remove VPN peer."""
    name = self.path.split('/')[-1]

    # Remove peer from WireGuard
    self.server.vpn_manager.remove_peer(name)

    self.send_response(200)
    self.end_headers()

    print(f"[vpn] Removed peer: {name}")
```

#### GET `/api/vpn/list`

List all VPN peers (optional, for admin).

**Response:**
```json
[
  {
    "name": "default",
    "ipv6": "fd00:faa5:0:100::a",
    "created": "2025-01-15",
    "status": "active"
  },
  {
    "name": "laptop",
    "ipv6": "fd00:faa5:0:100::b",
    "created": "2025-01-16",
    "status": "inactive"
  }
]
```

---

### VPN Manager Implementation (Server-Side)

The server needs a `VPNManager` class to handle peer lifecycle:

```python
class VPNManager:
    """Manages WireGuard VPN peers on the server."""

    def __init__(self):
        self.peers_dir = Path("/etc/wireguard/peers")
        self.peers_dir.mkdir(exist_ok=True)
        self.next_client_id = 0xa  # Start from hex 'a'
        self.allocated_ips = self._load_allocated_ips()

    def allocate_ipv6(self):
        """Allocate next available IPv6 for VPN client."""
        while True:
            ipv6 = f"fd00:faa5:0:100::{self.next_client_id:x}"
            if ipv6 not in self.allocated_ips:
                self.allocated_ips.add(ipv6)
                self.next_client_id += 1
                return ipv6
            self.next_client_id += 1

    def add_peer(self, name, public_key, ipv6):
        """Add peer to WireGuard server configuration."""
        # Create peer config file
        peer_config = f"""# Client: {name}
[Peer]
PublicKey = {public_key}
AllowedIPs = {ipv6}/128
"""

        peer_file = self.peers_dir / f"{name}.conf"
        with open(peer_file, 'w') as f:
            f.write(peer_config)

        # Reload WireGuard to apply changes
        self._reload_wireguard()

        print(f"[vpn] Added peer {name}: {ipv6}")

    def remove_peer(self, name):
        """Remove peer from WireGuard server configuration."""
        peer_file = self.peers_dir / f"{name}.conf"

        if peer_file.exists():
            # Read to get IPv6 for deallocation
            with open(peer_file) as f:
                content = f.read()
                if 'AllowedIPs' in content:
                    ipv6 = content.split('AllowedIPs = ')[1].split('/')[0]
                    self.allocated_ips.discard(ipv6)

            peer_file.unlink()
            self._reload_wireguard()
            print(f"[vpn] Removed peer {name}")

    def get_server_public_key(self):
        """Read server's public key."""
        with open("/etc/wireguard/server_public.key") as f:
            return f.read().strip()

    def _reload_wireguard(self):
        """Reload WireGuard configuration with all peers."""
        # Combine main config + all peer configs
        subprocess.run([
            'bash', '-c',
            'wg syncconf wg0 <(cat /etc/wireguard/wg0.conf /etc/wireguard/peers/*.conf)'
        ], check=True)

    def _load_allocated_ips(self):
        """Load currently allocated IPs from peer configs."""
        allocated = set()
        for peer_file in self.peers_dir.glob("*.conf"):
            with open(peer_file) as f:
                content = f.read()
                if 'AllowedIPs' in content:
                    ipv6 = content.split('AllowedIPs = ')[1].split('/')[0]
                    allocated.add(ipv6)
        return allocated
```

---

## Integration with Existing faasd

### Changes to faasd.py

**1. Initialize DNS and VPN managers:**
```python
def main():
    # ... existing setup ...

    # Initialize DNS manager
    dns_manager = DNSZoneManager()

    # Initialize VPN manager
    vpn_manager = VPNManager()

    # Pass to control server
    control_server.dns_manager = dns_manager
    control_server.vpn_manager = vpn_manager
```

**2. Modify IP assignment:**
```python
def add_listener(self, ip, image_name, rootfs_path, cmd):
    """Start listening on IP for image requests."""

    # NEW: Assign to wg0 instead of lo
    try:
        result = subprocess.run(
            ['ip', 'addr', 'add', f'{ip}/32', 'dev', 'wg0'],
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            stderr = result.stderr.lower()
            if 'file exists' not in stderr:
                raise Exception(f"Failed to add IP to wg0: {result.stderr}")

        print(f"[listener] Configured {ip}/32 on wg0 interface")

    except Exception as e:
        print(f"[listener] Error configuring IP: {e}")
        raise

    # ... rest of existing code ...
```

**3. Add DNS registration:**
```python
def _handle_new(self):
    """Handle image upload."""
    # ... existing deployment code ...

    # NEW: Register in DNS
    self.server.dns_manager.add_record(name, ip)
    print(f"[dns] Registered {name}.faas → {ip}")

    # ... rest of response ...
```

**4. Add VPN API endpoints:**
```python
class ControlAPI(BaseHTTPRequestHandler):
    # ... existing endpoints ...

    def do_POST(self):
        if self.path == '/api/new':
            self._handle_new()
        elif self.path == '/api/vpn/create':
            self._handle_vpn_create()
        else:
            self.send_error(404)

    def do_GET(self):
        if self.path.startswith('/api/ip/'):
            self._handle_ip()
        elif self.path == '/api/list':
            self._handle_list()
        elif self.path == '/api/vpn/list':
            self._handle_vpn_list()
        else:
            self.send_error(404)

    def do_DELETE(self):
        if self.path.startswith('/api/vpn/remove/'):
            self._handle_vpn_remove()
        else:
            self.send_error(404)

    def _handle_vpn_create(self):
        """Create new VPN peer (see Server API Endpoints section above)."""
        # Implementation shown in Server API Endpoints section
        pass

    def _handle_vpn_remove(self):
        """Remove VPN peer (see Server API Endpoints section above)."""
        # Implementation shown in Server API Endpoints section
        pass

    def _handle_vpn_list(self):
        """List all VPN peers."""
        peers = []
        for peer_file in Path("/etc/wireguard/peers").glob("*.conf"):
            with open(peer_file) as f:
                content = f.read()
                # Parse peer info
                name = peer_file.stem
                ipv6 = content.split('AllowedIPs = ')[1].split('/')[0]
                # Add to list
                peers.append({
                    'name': name,
                    'ipv6': ipv6,
                    'status': 'active'  # Could check wg show for actual status
                })

        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(peers).encode())
```

---

## Deployment Sequence

### First-Time Setup

1. **Install dependencies:**
   ```bash
   # WireGuard
   sudo apt install wireguard wireguard-tools

   # CoreDNS
   wget https://github.com/coredns/coredns/releases/download/v1.11.1/coredns_1.11.1_linux_amd64.tgz
   tar xzf coredns_1.11.1_linux_amd64.tgz
   sudo mv coredns /usr/local/bin/
   ```

2. **Generate WireGuard server keys:**
   ```bash
   wg genkey | tee /etc/wireguard/server_private.key | wg pubkey > /etc/wireguard/server_public.key
   chmod 600 /etc/wireguard/server_private.key
   ```

3. **Create WireGuard server config:**
   ```bash
   # /etc/wireguard/wg0.conf
   [Interface]
   Address = 10.100.0.1/24
   ListenPort = 51820
   PrivateKey = <contents of server_private.key>

   PostUp = iptables -A FORWARD -i wg0 -j ACCEPT
   PostUp = iptables -A FORWARD -o wg0 -j ACCEPT
   PostDown = iptables -D FORWARD -i wg0 -j ACCEPT
   PostDown = iptables -D FORWARD -o wg0 -j ACCEPT
   ```

4. **Start WireGuard:**
   ```bash
   sudo systemctl enable wg-quick@wg0
   sudo systemctl start wg-quick@wg0
   ```

5. **Create CoreDNS config:**
   ```bash
   mkdir -p /etc/coredns
   cat > /etc/coredns/Corefile << 'EOF'
   faas:53 {
       bind 10.100.0.1
       file /var/lib/faasd/dns/faas.db {
           reload 2s
       }
       log
       errors
   }

   .:53 {
       bind 10.100.0.1
       forward . 8.8.8.8 1.1.1.1
       log
       errors
   }
   EOF
   ```

6. **Initialize DNS zone file:**
   ```bash
   mkdir -p /var/lib/faasd/dns
   cat > /var/lib/faasd/dns/faas.db << 'EOF'
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
   ```

7. **Start CoreDNS:**
   ```bash
   sudo coredns -conf /etc/coredns/Corefile &
   ```

8. **Start faasd:**
   ```bash
   sudo python3 faasd.py
   ```

### Typical Usage Flow (Integrated VPN Client)

1. **Deploy a function:**
   ```bash
   ./faas new fibonacci
   # faasd automatically:
   # - Allocates IPv6: fd00:faa5:1:0::a
   # - Assigns to wg0: ip -6 addr add fd00:faa5:1:0::a/128 dev wg0
   # - Registers DNS: fibonacci.faas → fd00:faa5:1:0::a
   # - CoreDNS reloads zone file within 2s
   ```

2. **Connect to VPN (one command!):**
   ```bash
   ./faas vpn connect
   # Client automatically:
   # - Generates WireGuard keypair
   # - Registers with server (allocates fd00:faa5:0:100::a)
   # - Creates wg-faas interface
   # - Configures IPv6 routing and DNS
   # - Tests connectivity
   # Output: ✅ Connected! Your FaaS VPN is active.
   ```

3. **Access function:**
   ```bash
   curl http://fibonacci.faas/?n=10
   # DNS: fibonacci.faas → fd00:faa5:0:100::1:53 → fd00:faa5:1:0::a
   # TCP: Direct through VPN to fd00:faa5:1:0::a:80
   # Zero-copy FD passing to container
   # Output: Fibonacci sequence (10 steps):
   #         0, 1, 1, 2, 3, 5, 8, 13, 21, 34
   ```

4. **Disconnect when done:**
   ```bash
   ./faas vpn disconnect
   # Output: ✅ Disconnected.
   ```

5. **Reconnect later (uses saved config):**
   ```bash
   ./faas vpn connect
   # Output: ⚙  Found existing config: default
   #         ✅ Connected!
   ```

---

## IPv6 Implementation Details

### Python Socket Programming Changes

**Key differences when using IPv6:**

#### 1. Socket Creation

```python
# IPv4
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

# IPv6
sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)  # IPv6-only
```

#### 2. Socket Binding

```python
# IPv4: 2-tuple (host, port)
sock.bind(('10.0.0.10', 80))

# IPv6: 4-tuple (host, port, flowinfo, scope_id)
sock.bind(('fd00:faa5:1:0::a', 80, 0, 0))
```

**The 4-tuple components:**
- `host` - IPv6 address string
- `port` - Port number
- `flowinfo` - QoS flow label (usually 0)
- `scope_id` - Zone index for link-local addresses (0 for ULA)

#### 3. faasd IPv6 Integration

```python
class Registry:
    """Manages function IPv6 allocation."""

    def allocate_ipv6(self):
        """Allocate next available IPv6 in function range."""
        used = {m['ipv6'] for m in self.data.values()}

        # Start from fd00:faa5:1:0::a (hex a = 10)
        for i in range(0xa, 0xffff):
            ipv6 = f"fd00:faa5:1:0::{i:x}"
            if ipv6 not in used:
                return ipv6
        raise Exception("No IPv6 addresses available")


class FaaSServer:
    """Handles HTTP requests on allocated IPv6 addresses."""

    def add_listener(self, ipv6, image_name, rootfs_path, cmd):
        """Start listening on IPv6 for image requests."""

        # Configure IPv6 on wg0
        try:
            result = subprocess.run(
                ['ip', '-6', 'addr', 'add', f'{ipv6}/128', 'dev', 'wg0'],
                capture_output=True,
                text=True
            )

            if result.returncode != 0:
                stderr = result.stderr.lower()
                if 'file exists' not in stderr:
                    raise Exception(f"Failed to add IPv6 to wg0: {result.stderr}")

            print(f"[listener] Configured {ipv6}/128 on wg0 interface")

        except Exception as e:
            print(f"[listener] Error configuring IPv6: {e}")
            raise

        # Create IPv6 socket
        sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)

        try:
            # Bind with 4-tuple
            sock.bind((ipv6, 80, 0, 0))
            sock.listen(5)

            with self.lock:
                self.sockets[sock] = (image_name, rootfs_path, cmd)

            print(f"[listener] Listening on [{ipv6}]:80 for {image_name}")

        except Exception as e:
            print(f"[listener] Error binding to [{ipv6}]:80: {e}")
            raise
```

#### 4. Container Handler (No Changes to FD Passing!)

```python
# In fibonacci/handler.py or docker_handler.py

# Socket FD passing works identically for IPv6!
tcp_fd = receive_socket_fd()

# Reconstruct socket (automatically detects IPv6)
client_sock = socket.fromfd(tcp_fd, socket.AF_INET6, socket.SOCK_STREAM)

# Get client address (now a 4-tuple)
try:
    client_addr = client_sock.getpeername()
    # client_addr = ('fd00:faa5:0:100::a', 54321, 0, 0)
    print(f"[handler] Request from [{client_addr[0]}]:{client_addr[1]}")
except OSError:
    client_addr = ('unknown', 0, 0, 0)

# Handle HTTP request (works the same!)
FibonacciHandler(client_sock, client_addr, None)
```

### System Configuration for IPv6

#### Enable IPv6 Forwarding

```bash
# Temporary
sudo sysctl -w net.ipv6.conf.all.forwarding=1

# Permanent
echo "net.ipv6.conf.all.forwarding=1" | sudo tee -a /etc/sysctl.conf
sudo sysctl -p
```

#### Firewall Rules (ip6tables)

```bash
# Allow IPv6 forwarding through WireGuard
sudo ip6tables -A FORWARD -i wg0 -j ACCEPT
sudo ip6tables -A FORWARD -o wg0 -j ACCEPT

# Allow established connections
sudo ip6tables -A FORWARD -m state --state RELATED,ESTABLISHED -j ACCEPT

# Save rules (Debian/Ubuntu)
sudo netfilter-persistent save
```

### Testing IPv6 Connectivity

```bash
# Test WireGuard IPv6
ping6 -c 3 fd00:faa5:0:100::1

# Test DNS resolution
dig fibonacci.faas AAAA @fd00:faa5:0:100::1
nslookup fibonacci.faas fd00:faa5:0:100::1

# Test HTTP access
curl -6 http://[fd00:faa5:1:0::a]/?n=10
curl http://fibonacci.faas/?n=10

# Check IPv6 routing
ip -6 route show
# Should show: fd00:faa5::/32 dev wg0

# Check IPv6 addresses on wg0
ip -6 addr show dev wg0

# Trace IPv6 route
traceroute6 fd00:faa5:1:0::a
```

### Common IPv6 Pitfalls and Solutions

#### 1. URL Syntax with IPv6 Addresses

```bash
# WRONG (will fail)
curl http://fd00:faa5:1:0::a/?n=10

# CORRECT (brackets required)
curl http://[fd00:faa5:1:0::a]/?n=10

# BEST (use DNS!)
curl http://fibonacci.faas/?n=10
```

#### 2. Socket Bind Tuple

```python
# WRONG (IPv4 syntax)
sock.bind(('fd00:faa5:1:0::a', 80))  # TypeError!

# CORRECT (IPv6 4-tuple)
sock.bind(('fd00:faa5:1:0::a', 80, 0, 0))
```

#### 3. WireGuard Endpoint (Can Be IPv4 or IPv6!)

```ini
# IPv4 endpoint works fine for IPv6-only tunnel
[Peer]
Endpoint = 203.0.113.10:51820  # IPv4 endpoint
AllowedIPs = fd00:faa5::/32    # IPv6 inside tunnel

# IPv6 endpoint also works
[Peer]
Endpoint = [2001:db8::1]:51820  # IPv6 endpoint (needs brackets!)
AllowedIPs = fd00:faa5::/32
```

#### 4. CoreDNS Forward Servers

```
# Use IPv6 DNS servers
forward . 2001:4860:4860::8888 2606:4700:4700::1111

# Or IPv4 (still works for forwarding)
forward . 8.8.8.8 1.1.1.1
```

### Migration from Current IPv4 Code

**Changes required in faasd.py:**

1. **IP allocation** (line ~154):
```python
# Old
ip = f"10.0.0.{i}"

# New
ipv6 = f"fd00:faa5:1:0::{i:x}"
```

2. **Interface assignment** (line ~448):
```python
# Old
subprocess.run(['ip', 'addr', 'add', f'{ip}/32', 'dev', 'lo'])

# New
subprocess.run(['ip', '-6', 'addr', 'add', f'{ipv6}/128', 'dev', 'wg0'])
```

3. **Socket creation** (line ~473):
```python
# Old
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.bind((ip, 80))

# New
sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
sock.bind((ipv6, 80, 0, 0))
```

4. **DNS records** (DNS manager):
```python
# Old
zone_content += f"{name:<15} IN  A   {ip}\n"

# New
zone_content += f"{name:<15} IN  AAAA  {ipv6}\n"
```

**That's it!** Everything else (FD passing, containers, HTTP handling) works identically.

---

## Benefits of This Design

✅ **Maintains Zero-Copy Architecture**
- No reverse proxy
- Direct TCP connection to function IP
- Socket FD passed directly to container

✅ **Simple and Robust**
- No etcd, Redis, or complex dependencies
- Zone files are human-readable
- Easy to debug and troubleshoot

✅ **Secure**
- All traffic encrypted via WireGuard
- No public exposure of functions
- VPN provides authentication layer

✅ **Dynamic**
- Functions auto-register on deployment
- DNS updates automatically
- VPN clients can be added/removed on-demand

✅ **Client-Friendly**
- Single command to create VPN config
- Standard WireGuard clients work everywhere
- Domain names instead of IPv6 addresses

✅ **IPv6 Future-Proof**
- Massive address space (`fd00:faa5::/32` = 18 quintillion addresses per /64)
- No IP exhaustion concerns
- Clean hex addressing (`::a`, `::b` vs `10`, `11`)
- No NAT required (pure end-to-end connectivity)
- Modern networking stack

---

## Potential Enhancements

### Short-Term
- **QR code generation** for mobile VPN setup (`./faas vpn qr [name]`)
- **Automatic CoreDNS/WireGuard startup** via systemd
- **VPN connection status** detection in `./faas vpn list`
- **DNS wildcards** for function namespaces (*.prod.faas)
- **IPv6 SLAAC** for automatic client addressing

### Long-Term
- **Multiple VPN networks** for isolation (prod vs. dev)
- **DHCPv6** integration for dynamic client IP assignment
- **DNS-SD/mDNS** for local function discovery over IPv6
- **IPv6 privacy extensions** support
- **Metrics/monitoring** dashboard accessible via VPN

---

## Open Questions

1. **WireGuard startup order:** Should WireGuard start before or after faasd?
   - **Proposal:** WireGuard starts first (systemd dependency)
   - faasd checks for wg0 interface on startup
   - Fail gracefully if wg0 not available

2. **DNS zone serial management:** How to persist serial across restarts?
   - **Proposal:** Store in separate file (/var/lib/faasd/dns/serial)
   - Increment on each update
   - Read on startup

3. **Client IP allocation:** How to handle IP reuse when clients are removed?
   - **Proposal:** Simple sequential allocation for now
   - Could add IP pool manager later if needed

4. **Server endpoint discovery:** How does faasd know its public IP/hostname?
   - **Proposal:** Configuration file or environment variable
   - `FAAS_VPN_ENDPOINT=faas.example.com`

5. **Function removal:** Should we remove from DNS immediately or keep for TTL period?
   - **Proposal:** Remove immediately from zone file
   - Clients will get NXDOMAIN after CoreDNS reload (2s)

---

## Files to Create/Modify

### Server-Side (New Files)
- `/etc/wireguard/wg0.conf` - WireGuard server config
- `/etc/wireguard/server_private.key` - Server private key
- `/etc/wireguard/server_public.key` - Server public key
- `/etc/wireguard/peers/*.conf` - Client peer configs (auto-managed)
- `/etc/coredns/Corefile` - CoreDNS configuration
- `/var/lib/faasd/dns/faas.db` - DNS zone file (AAAA records)
- `docs/DNS_DESIGN.md` - This document

### Server-Side (Modified Files)
- `faasd.py` - Add DNS and VPN managers, modify IPv6 assignment, add VPN API endpoints

### Server-Side (New Python Modules)
- `dns_manager.py` - DNSZoneManager class (AAAA record management)
- `vpn_manager.py` - VPNManager class (peer lifecycle, IPv6 allocation)

### Client-Side (Modified Files)
- `faas` - Add integrated VPN client with connect/disconnect/status/list/remove commands

### Client-Side (New Files - Auto-Created)
- `~/.config/faas/vpn/default.json` - Default VPN configuration
- `~/.config/faas/vpn/*.json` - Named VPN configurations

---

## Summary

This design provides a **simple, robust, single-node, IPv6-only implementation** of dynamic DNS for FaaS functions, accessible via WireGuard VPN. It maintains the zero-copy architecture while providing user-friendly domain-based access through a clean client API.

### Key Innovations

1. **IPv6-Only with `fd00:faa5::/32`** - Memorable, future-proof addressing
   - Massive address space (no exhaustion)
   - Clean hex notation (`::a`, `::b`, `::c`)
   - No NAT required

2. **Function IPv6s on WireGuard interface** - Makes them routable through VPN
   - Assigned to wg0 (not loopback)
   - Direct end-to-end connectivity
   - Maintains zero-copy socket passing

3. **CoreDNS with file backend** - Simple, no external dependencies
   - AAAA records for IPv6 resolution
   - Auto-reload on changes
   - Human-readable zone files

4. **Automatic DNS registration** - Functions self-register on deployment
   - Dynamic zone file updates
   - 2-second reload time
   - Atomic file operations

5. **Clean client API** - `./faas vpn create` generates ready-to-use configs
   - Single command setup
   - Standard WireGuard clients
   - Cross-platform support

### IPv6 Advantages

- **18 quintillion addresses per /64** - Never run out
- **Hierarchical allocation** - Infrastructure vs. functions clearly separated
- **Future-proof** - Modern networking stack
- **No NAT complexity** - Pure Layer 3 routing
- **Works with IPv4 endpoints** - Tunnel endpoint can be IPv4

### Implementation Simplicity

The migration from IPv4 requires only **4 small code changes**:
1. IPv6 allocation (`f"fd00:faa5:1:0::{i:x}"`)
2. Interface assignment (`ip -6 addr add`)
3. Socket creation (`AF_INET6`, 4-tuple bind)
4. DNS records (`AAAA` instead of `A`)

Everything else (FD passing, containers, HTTP handling) works identically!

This foundation can be extended with additional features while keeping the core design simple and maintainable.
