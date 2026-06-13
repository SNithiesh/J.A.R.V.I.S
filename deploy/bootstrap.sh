#!/usr/bin/env bash
# ============================================================
# JARVIS VPS bootstrap — run ONCE on a fresh Ubuntu 22.04/24.04
# server:   bash deploy/bootstrap.sh
# Installs Docker, locks the firewall to SSH/HTTP/HTTPS only.
# ============================================================
set -euo pipefail

echo "[1/4] System updates (a fresh VPS is weeks behind on patches)..."
sudo apt-get update -y && sudo apt-get upgrade -y

echo "[2/4] Installing Docker (official convenience script)..."
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"   # lets you run docker without sudo

echo "[3/4] Firewall: only SSH(22), HTTP(80), HTTPS(443) may enter..."
sudo apt-get install -y ufw
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw --force enable

echo "[4/4] Done."
echo ">>> Log out (type: exit) and SSH back in — the docker group"
echo ">>> permission only takes effect on a fresh login. Then deploy."
