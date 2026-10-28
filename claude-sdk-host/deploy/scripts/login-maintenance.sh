#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# deploy/scripts/login-maintenance.sh
# Interactive one-off maintenance container to perform official Claude Code sign-in.
#
# Runs in the guarded SDK namespace using the persistent auth volume.
# Discovers the bundled CLI via the Python SDK (not assuming global binary on PATH).
# Never prints HTTP_PROXY or authentication values.
# ==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOST_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "=== Claude SDK Host: Official Login Maintenance ==="
echo "This command launches an interactive session in the guarded SDK namespace"
echo "to authenticate via the official bundled Claude Code CLI."
echo ""

cd "$HOST_DIR"

# Ensure docker compose is available
if ! command -v docker >/dev/null 2>&1; then
    echo "ERROR: docker command not found." >&2
    exit 1
fi

# In-container login command that discovers the bundled binary dynamically
LOGIN_CMD='
CLI_PATH=$(python3 -c "import claude_agent_sdk, pathlib; p = pathlib.Path(claude_agent_sdk.__file__).parent / \"_bundled\" / \"claude\"; print(p if p.is_file() else \"claude\")")
if [ ! -x "$CLI_PATH" ] && [ "$CLI_PATH" != "claude" ]; then
    chmod +x "$CLI_PATH" 2>/dev/null || true
fi
echo "Starting official Claude authentication flow..."
exec "$CLI_PATH" auth login --claudeai
'

if docker compose ps --services --filter "status=running" 2>/dev/null | grep -q "^claude-sdk-host$"; then
    echo "Attaching to running claude-sdk-host service in guarded namespace..."
    docker compose exec -it -u 1000:1000 -e DISABLE_AUTOUPDATER=1 -e CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 claude-sdk-host bash -c "$LOGIN_CMD"
else
    echo "Launching disposable maintenance container in guarded SDK namespace..."
    docker compose run --rm -it -u 1000:1000 -e DISABLE_AUTOUPDATER=1 -e CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 --entrypoint bash claude-sdk-host -c "$LOGIN_CMD"
fi

echo ""
echo "=== Official Login Maintenance Finished ==="
echo "Authentication complete. Credentials persisted securely in auth volume."
