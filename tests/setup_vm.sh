#!/usr/bin/env bash
set -e
export DEBIAN_FRONTEND=noninteractive
curl -LsSf https://astral.sh/uv/install.sh | sh
sudo cp ~/.local/bin/uv /usr/local/bin/
sudo chmod +x /usr/local/bin/uv

sudo useradd -m -s /bin/bash faas_user
sudo groupadd faas_group
sudo usermod -aG faas_group faas_user 
sudo chown -R root:faas_group "$PROJECT_DIR"
sudo chmod -R 750 "$PROJECT_DIR"

# sudo setfacl -R -m u:faas_user:r-X "$PROJECT_DIR"
# sudo setfacl -R -d -m u:faas_user:r-X "$PROJECT_DIR"
