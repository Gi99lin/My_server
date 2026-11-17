#!/bin/bash
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

echo "==================================="
echo "    LibreChat Installation"
echo "==================================="

# Ensure directories exist and have proper permissions for the node user
echo "[1/2] Setting up host directories and permissions..."
mkdir -p images uploads logs data-node meili_data

if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    # We use sudo because the running user might need to give permissions to user 1000 (node) in container
    echo "Applying standard 1000:1000 ownership..."
    sudo chown -R 1000:1000 images uploads logs data-node meili_data
fi

echo "[2/2] Starting containers..."
docker-compose up -d

echo ""
echo "✅ LibreChat is now running!"
echo "🌍 Internal access point: LibreChat:3080 via the 'proxy_network'."
echo "Please configure Nginx Proxy Manager to point a Custom Domain to the 'LibreChat' container on port '3080'."
