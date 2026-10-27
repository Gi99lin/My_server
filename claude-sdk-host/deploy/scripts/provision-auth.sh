#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# deploy/scripts/provision-auth.sh
# Safely provisions the official Claude authentication named volume and durable
# journal named volume with restricted non-root ownership (UID:GID 1000:1000, mode 0700)
# WITHOUT starting the API unauthenticated or exposing network endpoints.
# ==============================================================================

AUTH_VOLUME="${AUTH_VOLUME:-claude_sdk_auth}"
JOURNAL_VOLUME="${JOURNAL_VOLUME:-claude_sdk_journal}"
HOST_UID="${HOST_UID:-1000}"
HOST_GID="${HOST_GID:-1000}"

echo "=== Provisioning Persistent Volumes ==="
echo "Auth Volume:    $AUTH_VOLUME"
echo "Journal Volume: $JOURNAL_VOLUME"

# Check docker CLI
if ! command -v docker >/dev/null 2>&1; then
    echo "ERROR: docker command not found." >&2
    exit 1
fi

provision_volume() {
    local vol="$1"
    echo "--- Provisioning volume: $vol ---"
    # 1. Create named volume if it doesn't already exist
    if ! docker volume inspect "$vol" >/dev/null 2>&1; then
        echo "Creating Docker volume '$vol'..."
        docker volume create "$vol" >/dev/null
    else
        echo "Docker volume '$vol' already exists."
    fi

    # 2. Provision ownership using a strictly isolated, network-disabled one-off container
    echo "Setting restricted non-root permissions ($HOST_UID:$HOST_GID, mode 0700)..."
    docker run --rm \
        --network none \
        -v "$vol:/target" \
        alpine:3.20 \
        sh -c "chown -R $HOST_UID:$HOST_GID /target && chmod 700 /target"

    # 3. Verify ownership
    echo "Verifying volume permissions..."
    PERMS=$(docker run --rm \
        --network none \
        -v "$vol:/target:ro" \
        alpine:3.20 \
        sh -c "stat -c '%u:%g %a' /target 2>/dev/null || stat -f '%u:%g %p' /target")
    echo "  Volume '$vol' metadata: $PERMS"
}

provision_volume "$AUTH_VOLUME"
provision_volume "$JOURNAL_VOLUME"

echo "=== Volume Provisioning Complete ==="
echo "Both volumes are secured with mode 0700 (UID:GID $HOST_UID:$HOST_GID) and ready for mounting."
