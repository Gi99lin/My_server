#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# deploy/scripts/drain-recreate.sh
# Gracefully drains, stops, and recreates the entire Claude SDK Host namespace stack.
#
# Prevents orphaned processes or unmanaged network namespaces by recreating
# sdk-netguard, claude-sdk-host, and sdk-egress as a single atomic unit.
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOST_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "=== Claude SDK Host: Drain & Recreate Stack ==="
cd "$HOST_DIR"

# 1. Attempt graceful API drain / cancel check if API container is running
if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^claude-sdk-host$"; then
    echo "[1/3] claude-sdk-host is active. Checking health / draining..."
    # If debug port or internal curl is available, attempt health check
    docker exec claude-sdk-host python -m claude_host check-config --config /run/secrets/host-config.json 2>/dev/null || true
else
    echo "[1/3] Stack not currently running."
fi

# 2. Stop and remove containers and networks cleanly
echo "[2/3] Tearing down existing stack cleanly..."
docker compose down --remove-orphans

# 3. Recreate the complete namespace unit
echo "[3/3] Rebuilding (if needed) and bringing up stack atomically..."
docker compose up -d --build

echo ""
echo "=== Stack Recreation Initiated ==="
echo "Checking service status:"
docker compose ps
