#!/bin/bash

set -e

echo "=== AutoServe Installer ==="

# Detect package manager
if command -v apt-get >/dev/null 2>&1; then
    PKG_MANAGER="apt-get"
    UPDATE_CMD="apt-get update -y"
    INSTALL_CMD="apt-get install -y"
elif command -v yum >/dev/null 2>&1; then
    PKG_MANAGER="yum"
    UPDATE_CMD="yum makecache"
    INSTALL_CMD="yum install -y"
else
    echo "Unsupported package manager. Please install dependencies manually."
    exit 1
fi

# Function to install a package if missing
install_if_missing() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo "Installing $1..."
        sudo $INSTALL_CMD "$2"
    else
        echo "$1 is already installed."
    fi
}

echo "Updating package lists..."
sudo $UPDATE_CMD

# Check & install dependencies
install_if_missing curl curl
install_if_missing git git
install_if_missing python3 python3
install_if_missing pip3 python3-pip

# Docker installation
if ! command -v docker >/dev/null 2>&1; then
    echo "Installing Docker..."
    curl -fsSL https://get.docker.com | sudo sh
    sudo usermod -aG docker "$USER"
    echo "Docker installed. Please log out and log back in to use Docker without sudo."
else
    echo "Docker is already installed."
fi

# Docker Compose installation
if ! command -v docker-compose >/dev/null 2>&1; then
    echo "Installing docker-compose..."
    sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" \
        -o /usr/local/bin/docker-compose
    sudo chmod +x /usr/local/bin/docker-compose
else
    echo "docker-compose is already installed."
fi

# Ensure .env files exist
if [ ! -f ".env" ] && [ -f ".env.example" ]; then
    echo "Copying .env.example to .env..."
    cp .env.example .env
fi

if [ ! -f ".env.docker" ] && [ -f ".env.docker.example" ]; then
    echo "Copying .env.docker.example to .env.docker..."
    cp .env.docker.example .env.docker
fi

echo "=== Installation Complete ==="
echo ""
echo "You can now run: ./start.sh"
echo "If you just installed Docker, log out & back in (or run 'newgrp docker') before continuing."
