# Cloud-Init Configuration for FaaS Platform

This directory contains cloud-init configuration files for automated deployment of the FaaS platform on cloud providers.

## Overview

Cloud-init is the industry standard for cloud instance initialization. It runs once on the first boot of a cloud instance and performs automated setup tasks like:
- Installing packages
- Creating users
- Configuring services
- Setting up networking
- Running custom scripts

## Files

### faas-cloud-init.yaml

Complete cloud-init configuration that sets up a FaaS platform from scratch on a fresh cloud instance.

**What it does:**
1. Sets hostname and timezone
2. Creates `faas` and `coredns` users
3. Installs all required packages (Python, runc, Docker, WireGuard, etc.)
4. Downloads and installs CoreDNS
5. Generates WireGuard server keys
6. Creates systemd service definitions
7. Configures IPv6 forwarding
8. Sets up firewall rules
9. Clones FaaS repository and installs binaries
10. Starts all services
11. Displays setup completion message with server public key

## Supported Cloud Providers

This cloud-init configuration works on:
- **AWS EC2** - Amazon Web Services
- **Google Cloud Platform (GCP)** - Compute Engine
- **Microsoft Azure** - Virtual Machines
- **DigitalOcean** - Droplets
- **Linode** - Compute Instances
- **Vultr** - Cloud Compute
- **Hetzner Cloud**
- **Oracle Cloud Infrastructure (OCI)**
- **IBM Cloud**
- Any cloud provider supporting cloud-init

## Quick Start

### 1. Customize Configuration

Before deploying, edit `faas-cloud-init.yaml`:

**Replace SSH public key:**
```yaml
users:
  - name: faas
    ssh_authorized_keys:
      - ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExample...  # YOUR KEY HERE
```

**Optional: Change hostname/FQDN:**
```yaml
hostname: faas-platform
fqdn: faas.example.com
```

**Optional: Change timezone:**
```yaml
timezone: America/New_York  # Or Europe/London, Asia/Tokyo, etc.
```

### 2. Deploy on Your Cloud Provider

#### AWS EC2

**Via Console:**
1. Go to EC2 → Launch Instance
2. Choose Ubuntu 22.04 LTS AMI
3. Select instance type (t3.small or larger recommended)
4. In "Advanced details" → "User data", paste contents of `faas-cloud-init.yaml`
5. Launch instance

**Via AWS CLI:**
```bash
aws ec2 run-instances \
  --image-id ami-0c55b159cbfafe1f0 \
  --instance-type t3.small \
  --key-name your-key-pair \
  --security-group-ids sg-xxxxxxxxx \
  --subnet-id subnet-xxxxxxxxx \
  --user-data file://faas-cloud-init.yaml \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=faas-platform}]'
```

#### Google Cloud Platform

```bash
gcloud compute instances create faas-platform \
  --image-family=ubuntu-2204-lts \
  --image-project=ubuntu-os-cloud \
  --machine-type=e2-small \
  --zone=us-central1-a \
  --metadata-from-file user-data=faas-cloud-init.yaml \
  --tags=faas-server
```

#### DigitalOcean

**Via Console:**
1. Create → Droplets
2. Choose Ubuntu 22.04 LTS
3. Select size (Basic $6/mo or higher recommended)
4. Scroll to "Advanced Options" → "Add Initialization scripts"
5. Paste contents of `faas-cloud-init.yaml`
6. Create Droplet

**Via doctl:**
```bash
doctl compute droplet create faas-platform \
  --image ubuntu-22-04-x64 \
  --size s-1vcpu-1gb \
  --region nyc3 \
  --user-data-file faas-cloud-init.yaml
```

#### Azure

```bash
az vm create \
  --resource-group myResourceGroup \
  --name faas-platform \
  --image Ubuntu2204 \
  --size Standard_B1s \
  --custom-data faas-cloud-init.yaml \
  --admin-username azureuser \
  --generate-ssh-keys
```

#### Linode

```bash
linode-cli linodes create \
  --type g6-nanode-1 \
  --region us-east \
  --image linode/ubuntu22.04 \
  --label faas-platform \
  --metadata.user_data "$(cat faas-cloud-init.yaml | base64)"
```

#### Vultr

**Via Console:**
1. Deploy New Server
2. Choose Cloud Compute
3. Select Ubuntu 22.04 LTS
4. Under "Startup Script", click "Add New" and paste `faas-cloud-init.yaml`
5. Deploy Server

### 3. Wait for Setup to Complete

Cloud-init typically takes **5-10 minutes** to complete. You can monitor progress:

**SSH to the instance:**
```bash
ssh faas@<instance-public-ip>
```

**Watch cloud-init progress:**
```bash
# View real-time log
sudo tail -f /var/log/cloud-init-output.log

# Check cloud-init status
cloud-init status

# Wait for completion
cloud-init status --wait
```

### 4. Verify Installation

Once cloud-init completes:

**Check services are running:**
```bash
sudo systemctl status wg-faas coredns faasd
```

**Get server public key:**
```bash
sudo cat /etc/wireguard/server_public.key
```

**View server info in MOTD:**
```bash
cat /etc/motd
```

### 5. Connect from Client

On your local machine:

```bash
# Note the instance's public IP address
INSTANCE_IP=<your-instance-public-ip>

# Connect via VPN (will prompt for server details)
./faas vpn connect
```

## Network Requirements

### Firewall Rules

The cloud-init configuration automatically sets up UFW firewall with:
- **Port 51820/UDP** - WireGuard VPN (public)
- **Port 22/TCP** - SSH (public)

**Function ports (80), DNS (53), and API (8080) are VPN-only** and not exposed publicly.

### Cloud Provider Firewall/Security Groups

You also need to configure your cloud provider's firewall:

**AWS Security Group:**
```bash
# Allow WireGuard
aws ec2 authorize-security-group-ingress \
  --group-id sg-xxxxxxxxx \
  --protocol udp \
  --port 51820 \
  --cidr 0.0.0.0/0

# Allow SSH
aws ec2 authorize-security-group-ingress \
  --group-id sg-xxxxxxxxx \
  --protocol tcp \
  --port 22 \
  --cidr 0.0.0.0/0
```

**GCP Firewall Rule:**
```bash
gcloud compute firewall-rules create allow-wireguard \
  --allow udp:51820 \
  --target-tags faas-server \
  --source-ranges 0.0.0.0/0
```

**DigitalOcean Firewall:**
Create a firewall in the console allowing:
- Inbound UDP 51820 from All IPv4/IPv6
- Inbound TCP 22 from All IPv4/IPv6

## Instance Requirements

### Minimum Specifications

- **CPU:** 1 vCPU
- **RAM:** 1 GB
- **Disk:** 10 GB
- **OS:** Ubuntu 22.04 LTS (recommended) or Debian 11+

### Recommended Specifications

For production workloads:
- **CPU:** 2+ vCPUs
- **RAM:** 2+ GB
- **Disk:** 20+ GB SSD
- **Network:** 1+ Gbps

### Recommended Instance Types

| Provider | Instance Type | vCPU | RAM | Price/mo |
|----------|--------------|------|-----|----------|
| AWS | t3.small | 2 | 2 GB | ~$15 |
| GCP | e2-small | 2 | 2 GB | ~$13 |
| DigitalOcean | Basic | 1 | 1 GB | $6 |
| Azure | B1s | 1 | 1 GB | ~$8 |
| Linode | Nanode | 1 | 1 GB | $5 |
| Vultr | Regular | 1 | 1 GB | $6 |

## Customization

### Change CoreDNS Version

In `faas-cloud-init.yaml`, update:
```yaml
runcmd:
  - |
    COREDNS_VERSION="1.11.1"  # Change this version
```

### Add Custom Functions

Deploy functions after setup:

```yaml
runcmd:
  # ... existing commands ...

  # Deploy example functions
  - cd /var/lib/faasd && /usr/local/bin/faas new fibonacci
  - cd /var/lib/faasd && /usr/local/bin/faas new hello
```

### Configure DNS Domain

If you want to use a real domain (e.g., faas.example.com) instead of just *.faas:

1. **Update Corefile:**
```yaml
write_files:
  - path: /etc/coredns/Corefile
    content: |
      faas.example.com:53 {
          bind fd00:faa5:0:100::1
          file /var/lib/faasd/dns/faas.example.com.db {
              reload 2s
          }
          log
          errors
      }
```

2. **Update zone file:**
```yaml
write_files:
  - path: /var/lib/faasd/dns/faas.example.com.db
    content: |
      $ORIGIN faas.example.com.
      $TTL 60
      @       IN  SOA ns.faas.example.com. admin.faas.example.com. (...)
```

3. **Delegate subdomain:**
Configure your domain registrar to delegate `faas.example.com` to your server's IPv6 address.

### Add Monitoring

Add Prometheus/Grafana during setup:

```yaml
packages:
  # ... existing packages ...
  - prometheus
  - grafana

runcmd:
  # ... existing commands ...

  # Start Prometheus
  - systemctl enable prometheus
  - systemctl start prometheus

  # Start Grafana
  - systemctl enable grafana-server
  - systemctl start grafana-server
```

## Troubleshooting

### Cloud-Init Failed

**Check cloud-init status:**
```bash
cloud-init status
# Output: status: error  (if failed)
```

**View error logs:**
```bash
sudo cat /var/log/cloud-init-output.log | grep -i error
```

**Common issues:**
1. **Package installation failed** - Check package names for your OS version
2. **Network timeout** - Retry or increase timeouts
3. **Permission denied** - Check file permissions in write_files section

### Services Not Starting

**Check which service failed:**
```bash
sudo systemctl status wg-faas coredns faasd
```

**Common issues:**
1. **wg-faas failed** - WireGuard module not loaded: `sudo modprobe wireguard`
2. **coredns failed** - Port 53 already in use: `sudo ss -tulpn | grep :53`
3. **faasd failed** - Dependencies not running: `sudo systemctl start wg-faas coredns`

**View detailed logs:**
```bash
sudo journalctl -u wg-faas -u coredns -u faasd -n 100
```

### Cannot Connect via VPN

**Check server public IP:**
```bash
curl -4 ifconfig.me
# or
curl -6 ifconfig.me
```

**Check WireGuard is listening:**
```bash
sudo ss -ulpn | grep 51820
# Should show: *:51820
```

**Check firewall allows WireGuard:**
```bash
sudo ufw status | grep 51820
# Should show: 51820/udp ALLOW Anywhere
```

**Test from client:**
```bash
nc -zvu <server-public-ip> 51820
# Should show: Connection to <ip> 51820 port [udp/*] succeeded!
```

## Security Considerations

### Hardening Checklist

- [ ] Change default SSH port from 22
- [ ] Disable password authentication (use keys only)
- [ ] Enable automatic security updates
- [ ] Configure fail2ban for SSH brute-force protection
- [ ] Restrict SSH access to specific IPs
- [ ] Enable audit logging
- [ ] Set up log monitoring/alerting

### Enhanced Security Configuration

Add to cloud-init:

```yaml
packages:
  # ... existing packages ...
  - fail2ban
  - unattended-upgrades

write_files:
  # Disable password authentication
  - path: /etc/ssh/sshd_config.d/99-hardening.conf
    content: |
      PasswordAuthentication no
      PermitRootLogin no
      Port 2222

  # Enable automatic security updates
  - path: /etc/apt/apt.conf.d/50unattended-upgrades
    content: |
      Unattended-Upgrade::Allowed-Origins {
          "${distro_id}:${distro_codename}-security";
      };
      Unattended-Upgrade::Automatic-Reboot "false";

runcmd:
  # ... existing commands ...

  # Enable fail2ban
  - systemctl enable fail2ban
  - systemctl start fail2ban
```

## Production Deployment

For production use, consider:

1. **High Availability:**
   - Deploy multiple instances behind a load balancer
   - Use managed DNS (Route53, Cloud DNS, etc.)
   - Set up health checks

2. **Backup and Recovery:**
   - Snapshot instance regularly
   - Backup `/var/lib/faasd` and `/etc/wireguard`
   - Document recovery procedures

3. **Monitoring and Logging:**
   - Integrate with CloudWatch, Stackdriver, etc.
   - Set up alerts for service failures
   - Centralized log aggregation

4. **Updates and Maintenance:**
   - Schedule regular updates
   - Test updates in staging first
   - Maintain upgrade documentation

5. **Compliance:**
   - Enable encryption at rest
   - Configure audit logging
   - Follow security baselines (CIS, NIST)

## Alternative: Terraform Deployment

For infrastructure-as-code, see `terraform/` directory for Terraform configurations that use this cloud-init file.

Example:
```hcl
resource "aws_instance" "faas" {
  ami           = "ami-0c55b159cbfafe1f0"  # Ubuntu 22.04
  instance_type = "t3.small"
  user_data     = file("${path.module}/../cloud-init/faas-cloud-init.yaml")

  tags = {
    Name = "faas-platform"
  }
}
```

## Support

For issues with cloud-init deployment:
1. Check `/var/log/cloud-init-output.log` on the instance
2. Review systemd service logs: `sudo journalctl -u faasd -f`
3. Verify network connectivity and firewall rules
4. Open an issue at https://github.com/connorcouetil/faas/issues
