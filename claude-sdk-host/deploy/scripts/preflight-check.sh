#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# deploy/scripts/preflight-check.sh
# Verifies host prerequisites and checks for IP/subnet conflicts before deployment.
# ==============================================================================

echo "=== Claude SDK Host Preflight Check ==="

SUBNETS=(
    "172.31.240.0/28"
    "172.31.240.16/28"
    "172.31.240.32/28"
    "172.31.240.48/28"
)

# 1. Check tools
echo "[1/4] Checking required host CLI tools..."
for tool in docker git; do
    if ! command -v "$tool" >/dev/null 2>&1; then
        echo "  [FAIL] Required tool missing: $tool" >&2
        exit 1
    fi
    echo "  [OK] Found $tool: $(command -v "$tool")"
done

# Check docker compose
if docker compose version >/dev/null 2>&1; then
    echo "  [OK] Found docker compose: $(docker compose version)"
else
    echo "  [FAIL] 'docker compose' plugin missing." >&2
    exit 1
fi

# 2. Check for route / network conflicts on the host
echo "[2/4] Checking for subnet conflicts on host routes..."
HOST_ROUTES=""
if command -v ip >/dev/null 2>&1; then
    HOST_ROUTES=$(ip route show 2>/dev/null || true)
elif command -v netstat >/dev/null 2>&1; then
    HOST_ROUTES=$(netstat -rn 2>/dev/null || true)
fi

CONFLICT_FOUND=0
for subnet in "${SUBNETS[@]}"; do
    base_prefix="${subnet%/*}"
    # Check if prefix appears in host routing table
    if echo "$HOST_ROUTES" | grep -q "$base_prefix"; then
        echo "  [CONFLICT] Subnet $subnet overlaps with an existing host route!" >&2
        CONFLICT_FOUND=1
    else
        echo "  [OK] No host route conflict for $subnet"
    fi
done

# 3. Check existing Docker networks for IPAM conflicts
echo "[3/4] Checking Docker networks for IPAM conflicts..."
if docker info >/dev/null 2>&1; then
    DOCKER_SUBNETS=$(docker network inspect $(docker network ls -q) 2>/dev/null | grep '"Subnet"' || true)
    for subnet in "${SUBNETS[@]}"; do
        if echo "$DOCKER_SUBNETS" | grep -q "\"$subnet\""; then
            echo "  [CONFLICT] Subnet $subnet is already assigned to an existing Docker network!" >&2
            CONFLICT_FOUND=1
        else
            echo "  [OK] Subnet $subnet is available in Docker IPAM."
        fi
    done
else
    echo "  [INFO] Docker daemon not reachable or offline; skipping live Docker IPAM check."
fi

if [ "$CONFLICT_FOUND" -ne 0 ]; then
    echo ""
    echo "=== PREFLIGHT FAILED ==="
    echo "One or more subnets conflict with existing routes or Docker networks."
    echo "Adjust SDK_CLIENTS_SUBNET, SDK_TOOLS_SUBNET, SDK_PROXY_SUBNET, or SDK_UPSTREAM_SUBNET in .env"
    exit 1
fi

# 4. Check configuration files
echo "[4/4] Checking configuration template validity..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOST_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

if [ -f "$HOST_DIR/config.example.json" ]; then
    echo "  [OK] config.example.json found."
else
    echo "  [FAIL] config.example.json missing!" >&2
    exit 1
fi

if [ -f "$HOST_DIR/deploy/egress/gost.example.json" ]; then
    echo "  [OK] gost.example.json found."
else
    echo "  [FAIL] gost.example.json missing!" >&2
    exit 1
fi

echo ""
echo "=== PREFLIGHT PASSED ==="
echo "Host environment is ready for Claude SDK Host stack deployment."
