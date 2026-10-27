#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# deploy/scripts/login-maintenance.sh
# Interactive one-off maintenance container to perform official Claude Code sign-in.
#
# Connects through the egress proxy forwarder and persists subscription credentials
# directly to the restricted claude_sdk_auth volume. Never dumps or logs tokens.
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOST_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

IMAGE_NAME="claude-sdk-host:local"
VOLUME_NAME="claude_sdk_auth"
EGRESS_PROXY_URL="${HTTP_PROXY:-http://172.31.240.35:8080}"

echo "=== Claude SDK Host: Official Login Maintenance ==="
echo "This command launches an interactive session to authenticate your personal"
echo "Claude subscription via the official Claude Code CLI."
echo ""
echo "Target volume:    $VOLUME_NAME"
echo "Egress proxy:     $EGRESS_PROXY_URL"
echo ""

# Ensure image exists or prompt build
if ! docker image inspect "$IMAGE_NAME" >/dev/null 2>&1; then
    echo "ERROR: Image '$IMAGE_NAME' not found. Please build first:" >&2
    echo "  cd $HOST_DIR && docker compose build" >&2
    exit 1
fi

# Ensure proxy is reachable if stack is running
echo "Launching interactive login container (press Ctrl+C to abort)..."
docker run -it --rm \
    --name claude-login-maintenance \
    --network claude_sdk_proxy \
    -e HTTP_PROXY="$EGRESS_PROXY_URL" \
    -e HTTPS_PROXY="$EGRESS_PROXY_URL" \
    -e http_proxy="$EGRESS_PROXY_URL" \
    -e https_proxy="$EGRESS_PROXY_URL" \
    -e CLAUDE_CONFIG_DIR=/var/lib/claude-auth \
    -v "$VOLUME_NAME:/var/lib/claude-auth" \
    --user 1000:1000 \
    --entrypoint /bin/bash \
    "$IMAGE_NAME" \
    -c "echo 'Running official Claude login...' && claude login && echo 'Login completed successfully.'"

echo ""
echo "=== Official Login Maintenance Finished ==="
echo "Credentials saved in volume '$VOLUME_NAME'."
