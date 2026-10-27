#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# deploy/scripts/drain-recreate.sh
# Gracefully drains, stops, and recreates the Claude SDK Host namespace stack.
#
# Process Contract:
# 1. Sends SIGUSR1 to claude-sdk-host to enter draining state (rejecting new submissions).
# 2. Polls local http://127.0.0.1:8080/health/live via in-container urllib until active=0 and queued=0.
# 3. If timeout is exceeded, logs warning and proceeds with SIGTERM shutdown.
# 4. Tears down and restarts the complete multi-container namespace unit (down -> up).
# Note: Down/up is distinct and sequential, not an atomic kernel operation.
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOST_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

DRAIN_TIMEOUT_SECONDS="${DRAIN_TIMEOUT_SECONDS:-60}"
POLL_INTERVAL=2

echo "=== Claude SDK Host: Drain & Recreate Stack ==="
cd "$HOST_DIR"

if ! command -v docker >/dev/null 2>&1; then
    echo "ERROR: docker command not found." >&2
    exit 1
fi

# 1. Check if claude-sdk-host is running
if docker compose ps --services --filter "status=running" 2>/dev/null | grep -q "^claude-sdk-host$"; then
    echo "[1/4] Sending SIGUSR1 to claude-sdk-host to enter draining mode..."
    docker compose kill -s SIGUSR1 claude-sdk-host

    echo "[2/4] Polling in-container /health/live (timeout: ${DRAIN_TIMEOUT_SECONDS}s)..."
    ELAPSED=0
    DRAINED=0

    while [ "$ELAPSED" -lt "$DRAIN_TIMEOUT_SECONDS" ]; do
        # Execute urllib GET to loopback inside the container
        if docker compose exec -T claude-sdk-host python3 -c "
import json, sys, urllib.request
try:
    with urllib.request.urlopen('http://127.0.0.1:8080/health/live', timeout=2) as resp:
        data = json.loads(resp.read().decode('utf-8'))
        active = data.get('active', 0)
        queued = data.get('queued', 0)
        draining = data.get('draining', True)
        if active == 0 and queued == 0:
            sys.exit(0)
        else:
            sys.exit(1)
except Exception:
    sys.exit(2)
" 2>/dev/null; then
            DRAINED=1
            echo "  Drain complete: all in-flight and queued sessions finished."
            break
        fi

        sleep "$POLL_INTERVAL"
        ELAPSED=$((ELAPSED + POLL_INTERVAL))
        echo "  Waiting for active/queued sessions to finish (${ELAPSED}s / ${DRAIN_TIMEOUT_SECONDS}s)..."
    done

    if [ "$DRAINED" -eq 0 ]; then
        echo "  WARNING: Drain timeout reached (${DRAIN_TIMEOUT_SECONDS}s). Proceeding with SIGTERM shutdown."
    fi
else
    echo "[1/4] claude-sdk-host is not currently running. Skipping graceful drain."
fi

# 2. Stop and tear down existing namespace containers and networks
echo "[3/4] Stopping stack containers (docker compose down)..."
docker compose down --remove-orphans

# 3. Bring up the stack
echo "[4/4] Starting stack containers (docker compose up -d)..."
docker compose up -d

echo ""
echo "=== Stack Recreation Complete ==="
docker compose ps
