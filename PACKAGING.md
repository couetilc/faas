# FaaS Platform Packaging and Distribution

## Overview

This document describes packaging strategies for distributing the FaaS platform, from simple tarball releases to full distribution packages.

---

## Package Distribution Strategies

### Strategy 1: Single Binary Release (Simplest)

**Concept:** Bundle Python code into a single executable using PyInstaller or similar.

**Pros:**
- ✅ Single file to download
- ✅ No Python version issues
- ✅ Easy to install: `curl -L https://releases/faasd | sudo install /usr/local/bin/`

**Cons:**
- ⚠️ Large binary size (~50MB with Python embedded)
- ⚠️ Still requires system dependencies (runc, WireGuard, CoreDNS)
- ⚠️ Platform-specific (need builds for x86_64, arm64, etc.)

**Implementation:**
```bash
# Using PyInstaller
pip install pyinstaller
pyinstaller --onefile \
    --add-data "dns_manager.py:." \
    --add-data "vpn_manager.py:." \
    faasd.py

# Result: dist/faasd (single binary)
```

**Not recommended** - Doesn't solve dependency management.

---

### Strategy 2: Installation Script (Recommended for Quick Start)

**Concept:** Single curl-to-bash installer that sets up everything.

**Pros:**
- ✅ One command install: `curl -fsSL https://get.faas.dev | sudo bash`
- ✅ Handles all dependencies
- ✅ Works on multiple distros
- ✅ Can auto-detect OS and architecture

**Cons:**
- ⚠️ Security concerns (piping curl to bash)
- ⚠️ Less control for users
- ⚠️ Hard to customize

**Implementation:** See `install.sh` example below.

**Best for:** Demos, development, getting started quickly.

---

### Strategy 3: Distribution Packages (Recommended for Production)

**Concept:** Native packages for each distribution (.deb, .rpm, etc.)

**Debian/Ubuntu (.deb):**
- Manage dependencies via `dpkg`
- Integrate with `apt` repositories
- Automatic systemd service setup

**RHEL/Fedora (.rpm):**
- Manage dependencies via `rpm`
- Integrate with `dnf/yum` repositories
- Automatic systemd service setup

**Pros:**
- ✅ Native package management
- ✅ Automatic dependency installation
- ✅ Clean upgrade/removal
- ✅ Familiar to sysadmins
- ✅ GPG signing for security

**Cons:**
- ⚠️ Need to build for multiple distros
- ⚠️ Requires package repository hosting

**Best for:** Production deployments, enterprise users.

---

### Strategy 4: Container Image (Alternative)

**Concept:** Distribute as Docker/Podman container.

**Pros:**
- ✅ All dependencies bundled
- ✅ Version pinning
- ✅ Easy to run: `docker run -d faas/faasd`

**Cons:**
- ⚠️ Requires privileged container (for WireGuard, namespaces)
- ⚠️ Container-in-container complexity (running runc inside Docker)
- ⚠️ Network configuration complexity

**Best for:** Kubernetes deployments (advanced).

**Not recommended** for single-node setup - adds unnecessary complexity.

---

### Strategy 5: Tarball + Makefile (Developer-Friendly)

**Concept:** Traditional source distribution with Makefile.

**Pros:**
- ✅ Simple and transparent
- ✅ Easy to customize
- ✅ No build tools required (just Python + system packages)
- ✅ Works on any Linux distro

**Cons:**
- ⚠️ Manual dependency installation
- ⚠️ Manual systemd setup
- ⚠️ No automatic updates

**Best for:** Developers, customization, learning.

**Implementation:** See tarball structure below.

---

## Recommended Distribution Strategy

### Tier 1: Official .deb and .rpm Packages

**Target users:** Production deployments, enterprise

**Provides:**
- Automatic dependency resolution
- Systemd service integration
- Clean upgrades and removal
- GPG-signed packages

### Tier 2: Installation Script

**Target users:** Quick starts, demos, development

**Provides:**
- One-command install
- Auto-detects OS and installs appropriate packages
- Sets up services automatically

### Tier 3: Source Tarball

**Target users:** Developers, custom builds

**Provides:**
- Full source code
- Makefile for manual installation
- Maximum flexibility

---

## Package Structure

### Debian Package Structure (.deb)

```
faasd_1.0.0_amd64.deb
├── DEBIAN/
│   ├── control              # Package metadata, dependencies
│   ├── postinst             # Post-installation script (setup systemd)
│   ├── prerm                # Pre-removal script (stop services)
│   └── postrm               # Post-removal script (cleanup)
├── usr/
│   ├── bin/
│   │   └── faas             # Client CLI
│   └── lib/
│       └── faasd/
│           ├── faasd.py     # Main daemon
│           ├── dns_manager.py
│           └── vpn_manager.py
├── etc/
│   ├── systemd/system/
│   │   └── faasd.service    # Systemd service
│   ├── coredns/
│   │   └── Corefile.example
│   └── wireguard/
│       └── wg0.conf.example
└── var/
    └── lib/
        └── faasd/
            ├── dns/
            └── images/
```

### control File

```
Package: faasd
Version: 1.0.0
Section: net
Priority: optional
Architecture: amd64
Depends: python3 (>= 3.8),
         runc (>= 1.1.0),
         wireguard (>= 1.0.0),
         wireguard-tools,
         iproute2,
         iptables
Recommends: docker.io | docker-ce
Suggests: coredns
Maintainer: FaaS Team <team@faas.dev>
Description: Serverless function platform with runc
 FaaS platform using runc for container execution, WireGuard VPN
 for secure access, and CoreDNS for function name resolution.
 .
 Supports IPv6-only networking with zero-copy socket passing.
Homepage: https://github.com/yourorg/faas
```

### postinst Script

```bash
#!/bin/bash
set -e

# Post-installation setup

case "$1" in
    configure)
        echo "Setting up faasd..."

        # Create faasd user (optional - currently runs as root)
        # useradd -r -s /bin/false -d /var/lib/faasd faasd || true

        # Create directories
        mkdir -p /var/lib/faasd/{images,bundles,dns}
        mkdir -p /etc/wireguard/peers

        # Set permissions
        chown -R root:root /var/lib/faasd
        chmod 755 /var/lib/faasd

        # Generate WireGuard keys if they don't exist
        if [ ! -f /etc/wireguard/server_private.key ]; then
            echo "Generating WireGuard server keys..."
            wg genkey | tee /etc/wireguard/server_private.key | \
                wg pubkey > /etc/wireguard/server_public.key
            chmod 600 /etc/wireguard/server_private.key
            echo "WireGuard keys generated at /etc/wireguard/server_*.key"
        fi

        # Initialize DNS zone if it doesn't exist
        if [ ! -f /var/lib/faasd/dns/faas.db ]; then
            cat > /var/lib/faasd/dns/faas.db <<'EOF'
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
        fi

        # Enable IPv6 forwarding
        sysctl -w net.ipv6.conf.all.forwarding=1 >/dev/null 2>&1 || true
        if ! grep -q "^net.ipv6.conf.all.forwarding=1" /etc/sysctl.conf 2>/dev/null; then
            echo "net.ipv6.conf.all.forwarding=1" >> /etc/sysctl.conf
        fi

        # Reload systemd
        systemctl daemon-reload

        echo ""
        echo "faasd installed successfully!"
        echo ""
        echo "Next steps:"
        echo "  1. Configure WireGuard: /etc/wireguard/wg0.conf"
        echo "  2. Configure CoreDNS: /etc/coredns/Corefile"
        echo "  3. Set FAAS_VPN_ENDPOINT in /etc/systemd/system/faasd.service"
        echo "  4. Start services:"
        echo "       sudo systemctl start wg-quick@wg0"
        echo "       sudo systemctl start coredns"
        echo "       sudo systemctl start faasd"
        echo ""
        ;;
esac

exit 0
```

### prerm Script

```bash
#!/bin/bash
set -e

case "$1" in
    remove|upgrade|deconfigure)
        echo "Stopping faasd service..."
        systemctl stop faasd || true
        ;;
esac

exit 0
```

### postrm Script

```bash
#!/bin/bash
set -e

case "$1" in
    purge)
        echo "Removing faasd data..."

        # Remove data directory (only on purge, not upgrade)
        rm -rf /var/lib/faasd

        # Remove WireGuard peers (keep keys for backup)
        rm -rf /etc/wireguard/peers

        echo "faasd data removed."
        ;;
    remove)
        # Keep data on remove (for reinstall/upgrade)
        echo "faasd removed (data preserved in /var/lib/faasd)."
        ;;
esac

exit 0
```

---

## Building Packages

### Build .deb Package

```bash
#!/bin/bash
# build-deb.sh

set -e

VERSION="1.0.0"
ARCH="amd64"
PKG_NAME="faasd_${VERSION}_${ARCH}"
BUILD_DIR="build/${PKG_NAME}"

echo "Building faasd ${VERSION} for ${ARCH}..."

# Clean previous builds
rm -rf build
mkdir -p "${BUILD_DIR}"

# Create directory structure
mkdir -p "${BUILD_DIR}/DEBIAN"
mkdir -p "${BUILD_DIR}/usr/bin"
mkdir -p "${BUILD_DIR}/usr/lib/faasd"
mkdir -p "${BUILD_DIR}/etc/systemd/system"
mkdir -p "${BUILD_DIR}/var/lib/faasd/dns"

# Copy files
cp faasd.py "${BUILD_DIR}/usr/lib/faasd/"
cp dns_manager.py "${BUILD_DIR}/usr/lib/faasd/"
cp vpn_manager.py "${BUILD_DIR}/usr/lib/faasd/"
cp faas "${BUILD_DIR}/usr/bin/"
chmod +x "${BUILD_DIR}/usr/bin/faas"

# Copy systemd service
cp systemd/faasd.service "${BUILD_DIR}/etc/systemd/system/"

# Create control file
cat > "${BUILD_DIR}/DEBIAN/control" <<EOF
Package: faasd
Version: ${VERSION}
Section: net
Priority: optional
Architecture: ${ARCH}
Depends: python3 (>= 3.8), runc (>= 1.1.0), wireguard, wireguard-tools, iproute2, iptables
Recommends: docker.io | docker-ce
Maintainer: FaaS Team <team@faas.dev>
Description: Serverless function platform with runc
 FaaS platform using runc for container execution.
Homepage: https://github.com/yourorg/faas
EOF

# Create postinst script
cp packaging/debian/postinst "${BUILD_DIR}/DEBIAN/"
chmod 755 "${BUILD_DIR}/DEBIAN/postinst"

# Create prerm script
cp packaging/debian/prerm "${BUILD_DIR}/DEBIAN/"
chmod 755 "${BUILD_DIR}/DEBIAN/prerm"

# Create postrm script
cp packaging/debian/postrm "${BUILD_DIR}/DEBIAN/"
chmod 755 "${BUILD_DIR}/DEBIAN/postrm"

# Build package
dpkg-deb --build "${BUILD_DIR}"

echo "Package built: build/${PKG_NAME}.deb"

# Optional: Check with lintian
if command -v lintian >/dev/null 2>&1; then
    lintian "build/${PKG_NAME}.deb"
fi
```

### Build .rpm Package

```bash
#!/bin/bash
# build-rpm.sh

set -e

VERSION="1.0.0"
RELEASE="1"

echo "Building faasd ${VERSION}-${RELEASE} RPM..."

# Create RPM build structure
mkdir -p ~/rpmbuild/{BUILD,RPMS,SOURCES,SPECS,SRPMS}

# Create source tarball
tar czf ~/rpmbuild/SOURCES/faasd-${VERSION}.tar.gz \
    --transform "s|^|faasd-${VERSION}/|" \
    faasd.py dns_manager.py vpn_manager.py faas systemd/

# Create spec file
cat > ~/rpmbuild/SPECS/faasd.spec <<EOF
Name:           faasd
Version:        ${VERSION}
Release:        ${RELEASE}%{?dist}
Summary:        Serverless function platform with runc
License:        MIT
URL:            https://github.com/yourorg/faas
Source0:        %{name}-%{version}.tar.gz

Requires:       python3 >= 3.8
Requires:       runc >= 1.1.0
Requires:       wireguard-tools
Requires:       iproute
Requires:       iptables
Recommends:     docker

BuildArch:      noarch

%description
FaaS platform using runc for container execution, WireGuard VPN
for secure access, and CoreDNS for function name resolution.

%prep
%autosetup

%install
mkdir -p %{buildroot}/usr/lib/faasd
mkdir -p %{buildroot}/usr/bin
mkdir -p %{buildroot}/etc/systemd/system
mkdir -p %{buildroot}/var/lib/faasd/dns

install -m 644 faasd.py %{buildroot}/usr/lib/faasd/
install -m 644 dns_manager.py %{buildroot}/usr/lib/faasd/
install -m 644 vpn_manager.py %{buildroot}/usr/lib/faasd/
install -m 755 faas %{buildroot}/usr/bin/
install -m 644 systemd/faasd.service %{buildroot}/etc/systemd/system/

%files
/usr/lib/faasd/
/usr/bin/faas
/etc/systemd/system/faasd.service
/var/lib/faasd/

%post
systemctl daemon-reload
echo "faasd installed. Configure and start services."

%preun
systemctl stop faasd || true

%postun
if [ \$1 -eq 0 ]; then
    rm -rf /var/lib/faasd
fi

%changelog
* Wed Jan 15 2025 FaaS Team <team@faas.dev> - 1.0.0-1
- Initial release
EOF

# Build RPM
rpmbuild -ba ~/rpmbuild/SPECS/faasd.spec

echo "RPM built: ~/rpmbuild/RPMS/noarch/faasd-${VERSION}-${RELEASE}.noarch.rpm"
```

---

## Installation Script

```bash
#!/bin/bash
# install.sh - One-command installer for FaaS platform

set -e

INSTALL_DIR="/opt/faas"
VERSION="1.0.0"
BASE_URL="https://github.com/yourorg/faas/releases/download/v${VERSION}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "========================================"
echo "  FaaS Platform Installer v${VERSION}"
echo "========================================"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo -e "${RED}Error: This script must be run as root${NC}"
    echo "Please run: sudo $0"
    exit 1
fi

# Detect OS
if [ -f /etc/os-release ]; then
    . /etc/os-release
    OS=$ID
    VER=$VERSION_ID
else
    echo -e "${RED}Error: Cannot detect OS${NC}"
    exit 1
fi

echo -e "${GREEN}Detected OS: $OS $VER${NC}"

# Install dependencies based on OS
install_dependencies() {
    case $OS in
        ubuntu|debian)
            echo "Installing dependencies via apt..."
            apt-get update
            apt-get install -y python3 runc docker.io wireguard wireguard-tools iproute2 iptables curl
            ;;
        fedora|rhel|centos)
            echo "Installing dependencies via dnf..."
            dnf install -y python3 runc docker wireguard-tools iproute iptables curl
            ;;
        arch)
            echo "Installing dependencies via pacman..."
            pacman -Sy --noconfirm python runc docker wireguard-tools iproute2 iptables curl
            ;;
        *)
            echo -e "${YELLOW}Warning: Unsupported OS. Please install dependencies manually.${NC}"
            return 1
            ;;
    esac
}

# Install CoreDNS
install_coredns() {
    echo "Installing CoreDNS..."
    COREDNS_VERSION="1.11.1"

    # Detect architecture
    ARCH=$(uname -m)
    case $ARCH in
        x86_64)
            COREDNS_ARCH="amd64"
            ;;
        aarch64|arm64)
            COREDNS_ARCH="arm64"
            ;;
        *)
            echo -e "${RED}Unsupported architecture: $ARCH${NC}"
            exit 1
            ;;
    esac

    curl -L "https://github.com/coredns/coredns/releases/download/v${COREDNS_VERSION}/coredns_${COREDNS_VERSION}_linux_${COREDNS_ARCH}.tgz" | \
        tar xz -C /tmp
    mv /tmp/coredns /usr/local/bin/
    chmod +x /usr/local/bin/coredns
    echo -e "${GREEN}CoreDNS installed${NC}"
}

# Install FaaS platform
install_faasd() {
    echo "Installing FaaS platform..."

    # Create directories
    mkdir -p ${INSTALL_DIR}/{bin,lib}
    mkdir -p /var/lib/faasd/{images,bundles,dns}
    mkdir -p /etc/wireguard/peers

    # Download release
    curl -L "${BASE_URL}/faasd.py" -o ${INSTALL_DIR}/lib/faasd.py
    curl -L "${BASE_URL}/dns_manager.py" -o ${INSTALL_DIR}/lib/dns_manager.py
    curl -L "${BASE_URL}/vpn_manager.py" -o ${INSTALL_DIR}/lib/vpn_manager.py
    curl -L "${BASE_URL}/faas" -o /usr/local/bin/faas

    chmod +x /usr/local/bin/faas
    chmod +x ${INSTALL_DIR}/lib/faasd.py

    echo -e "${GREEN}FaaS platform files installed${NC}"
}

# Setup WireGuard
setup_wireguard() {
    echo "Setting up WireGuard..."

    # Generate keys if they don't exist
    if [ ! -f /etc/wireguard/server_private.key ]; then
        wg genkey | tee /etc/wireguard/server_private.key | wg pubkey > /etc/wireguard/server_public.key
        chmod 600 /etc/wireguard/server_private.key
    fi

    # Create config if it doesn't exist
    if [ ! -f /etc/wireguard/wg0.conf ]; then
        cat > /etc/wireguard/wg0.conf <<EOF
[Interface]
Address = fd00:faa5:0:100::1/64
ListenPort = 51820
PrivateKey = $(cat /etc/wireguard/server_private.key)

PostUp = sysctl -w net.ipv6.conf.all.forwarding=1
PostUp = ip6tables -A FORWARD -i wg0 -j ACCEPT
PostUp = ip6tables -A FORWARD -o wg0 -j ACCEPT

PostDown = ip6tables -D FORWARD -i wg0 -j ACCEPT
PostDown = ip6tables -D FORWARD -o wg0 -j ACCEPT
EOF
    fi

    echo -e "${GREEN}WireGuard configured${NC}"
}

# Setup CoreDNS
setup_coredns() {
    echo "Setting up CoreDNS..."

    mkdir -p /etc/coredns

    if [ ! -f /etc/coredns/Corefile ]; then
        cat > /etc/coredns/Corefile <<'EOF'
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
    fi

    # Initialize DNS zone
    if [ ! -f /var/lib/faasd/dns/faas.db ]; then
        cat > /var/lib/faasd/dns/faas.db <<'EOF'
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
    fi

    echo -e "${GREEN}CoreDNS configured${NC}"
}

# Setup systemd services
setup_systemd() {
    echo "Setting up systemd services..."

    # CoreDNS service
    cat > /etc/systemd/system/coredns.service <<'EOF'
[Unit]
Description=CoreDNS DNS Server
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

    # faasd service
    cat > /etc/systemd/system/faasd.service <<EOF
[Unit]
Description=FaaS Daemon
After=network.target wg-quick@wg0.service coredns.service
Requires=wg-quick@wg0.service coredns.service

[Service]
Type=simple
WorkingDirectory=${INSTALL_DIR}/lib
ExecStart=/usr/bin/python3 ${INSTALL_DIR}/lib/faasd.py
Restart=on-failure
RestartSec=10

Environment=PYTHONPATH=${INSTALL_DIR}/lib
Environment=FAAS_ROOT=/var/lib/faasd
Environment=FAAS_VPN_ENDPOINT=CHANGEME

User=root
Group=root

[Install]
WantedBy=multi-user.target
EOF

    systemctl daemon-reload
    echo -e "${GREEN}Systemd services configured${NC}"
}

# Enable IPv6 forwarding
enable_ipv6_forwarding() {
    echo "Enabling IPv6 forwarding..."
    sysctl -w net.ipv6.conf.all.forwarding=1
    if ! grep -q "^net.ipv6.conf.all.forwarding=1" /etc/sysctl.conf 2>/dev/null; then
        echo "net.ipv6.conf.all.forwarding=1" >> /etc/sysctl.conf
    fi
    echo -e "${GREEN}IPv6 forwarding enabled${NC}"
}

# Main installation
echo ""
echo "Step 1/7: Installing dependencies..."
install_dependencies

echo ""
echo "Step 2/7: Installing CoreDNS..."
install_coredns

echo ""
echo "Step 3/7: Installing FaaS platform..."
install_faasd

echo ""
echo "Step 4/7: Setting up WireGuard..."
setup_wireguard

echo ""
echo "Step 5/7: Setting up CoreDNS..."
setup_coredns

echo ""
echo "Step 6/7: Setting up systemd services..."
setup_systemd

echo ""
echo "Step 7/7: Enabling IPv6 forwarding..."
enable_ipv6_forwarding

echo ""
echo "========================================"
echo -e "${GREEN}Installation Complete!${NC}"
echo "========================================"
echo ""
echo "Next steps:"
echo "  1. Set your VPN endpoint:"
echo "     Edit /etc/systemd/system/faasd.service"
echo "     Change FAAS_VPN_ENDPOINT=CHANGEME to your public IP/domain"
echo ""
echo "  2. Start services:"
echo "     sudo systemctl enable --now wg-quick@wg0"
echo "     sudo systemctl enable --now coredns"
echo "     sudo systemctl enable --now faasd"
echo ""
echo "  3. Deploy a function:"
echo "     faas new my-function"
echo ""
echo "  4. Connect via VPN:"
echo "     faas vpn connect"
echo ""
echo "For more information: https://docs.faas.dev"
echo ""
```

---

## Distribution Channels

### GitHub Releases

**Structure:**
```
v1.0.0/
├── faasd_1.0.0_amd64.deb
├── faasd_1.0.0_arm64.deb
├── faasd-1.0.0-1.x86_64.rpm
├── faasd-1.0.0-1.aarch64.rpm
├── faasd-1.0.0.tar.gz
├── install.sh
├── SHA256SUMS
└── SHA256SUMS.sig
```

**Download:**
```bash
# Install script
curl -fsSL https://github.com/yourorg/faas/releases/download/v1.0.0/install.sh | sudo bash

# Debian package
wget https://github.com/yourorg/faas/releases/download/v1.0.0/faasd_1.0.0_amd64.deb
sudo apt install ./faasd_1.0.0_amd64.deb

# Verify checksum
wget https://github.com/yourorg/faas/releases/download/v1.0.0/SHA256SUMS
sha256sum -c SHA256SUMS --ignore-missing
```

### APT Repository (Debian/Ubuntu)

**Setup:**
```bash
# Add GPG key
curl -fsSL https://apt.faas.dev/gpg.key | sudo gpg --dearmor -o /usr/share/keyrings/faas-archive-keyring.gpg

# Add repository
echo "deb [signed-by=/usr/share/keyrings/faas-archive-keyring.gpg] https://apt.faas.dev stable main" | \
    sudo tee /etc/apt/sources.list.d/faas.list

# Install
sudo apt update
sudo apt install faasd
```

### YUM/DNF Repository (RHEL/Fedora)

**Setup:**
```bash
# Add repository
sudo tee /etc/yum.repos.d/faas.repo <<EOF
[faas]
name=FaaS Platform Repository
baseurl=https://yum.faas.dev/rpm
enabled=1
gpgcheck=1
gpgkey=https://yum.faas.dev/rpm/gpg.key
EOF

# Install
sudo dnf install faasd
```

---

## Summary

### Recommended Distribution Strategy

**For production:**
1. **Primary:** .deb and .rpm packages with APT/YUM repos
2. **Secondary:** GitHub releases with checksums

**For development/testing:**
1. **Primary:** Installation script (`curl | bash`)
2. **Secondary:** Source tarball

**For enterprise:**
1. **Primary:** .deb/.rpm packages
2. **Secondary:** Internal package mirrors
3. **Tertiary:** Air-gapped tarball install

### Build Pipeline

```
Code Push → GitHub Actions
    ↓
Build Matrix:
    - build-deb (amd64, arm64)
    - build-rpm (x86_64, aarch64)
    - build-tarball
    - build-install-script
    ↓
Sign Packages (GPG)
    ↓
Upload to:
    - GitHub Releases
    - APT Repository
    - YUM Repository
    ↓
Update Documentation
```

Ready to tackle systemd definitions and cloud-init next!
