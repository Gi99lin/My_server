#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# deploy/scripts/provision-auth.sh
# Safely provisions the official Claude authentication named volume with restricted
# non-root ownership (UID:GID 1000:1000, mode 0700) WITHOUT starting the API
# unauthenticated or exposing network endpoints.
# ==============================================================================

VOLUME_NAME="claude_sdk_auth"
HOST_UID="${HOST_UID:-1000}"
HOST_GID="${HOST_GID:-1000}"

echo "=== Provisioning Auth Volume: $VOLUME_NAME ==="

# Check docker CLI
if ! command -v docker >/dev/null 2>&1; then
    echo "ERROR: docker command not found." >&2
    exit 1
fi

# 1. Create named volume if it doesn't already exist
if ! docker volume inspect "$VOLUME_NAME" >/dev/null 2>&1; then
    echo "[1/3] Creating Docker volume '$VOLUME_NAME'..."
    docker volume create "$VOLUME_NAME" >/dev/null
else
    echo "[1/3] Docker volume '$VOLUME_NAME' already exists."
fi

# 2. Provision ownership using a strictly isolated, network-disabled one-off container
echo "[2/3] Setting restricted non-root permissions ($HOST_UID:$HOST_GID, mode 0700)..."
docker run --rm \
    --network none \
    -v "$VOLUME_NAME:/target" \
    alpine:3.20 \
    sh -c "chown -R $HOST_UID:$HOST_GID /target && chmod 700 /target"

# 3. Verify ownership
echo "[3/3] Verifying volume permissions..."
PERMS=$(docker run --rm \
    --network none \
    -v "$VOLUME_NAME:/target:ro" \
    alpine:3.20 \
    sh -c "stat -c '%u:%g %a' /target 2>/dev/null || stat -f '%u:%g %p' /target")

echo "  Volume target metadata: $PERMS"
echo "=== Auth Volume Provisioning Complete ==="
echo "Volume is isolated and ready for official login maintenance or service mounting."
