#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# deploy/scripts/generate-peers.sh
# Generates static internal peer mappings for /etc/hosts and nftables allowlist
# from the host configuration file. Never globally exempts RFC1918 ranges.
# ==============================================================================

CONFIG_FILE="${1:-config.example.json}"

if [ ! -f "$CONFIG_FILE" ]; then
    echo "ERROR: Configuration file '$CONFIG_FILE' not found." >&2
    exit 1
fi

echo "=== Generating Static Internal Peer Mappings from $CONFIG_FILE ==="

# Validate JSON
if command -v jq >/dev/null 2>&1; then
    jq empty "$CONFIG_FILE" || { echo "ERROR: Invalid JSON in $CONFIG_FILE" >&2; exit 1; }
    
    # Extract registered MCP endpoints and credential provider URLs
    echo "# Static internal peer mappings (Generated from $CONFIG_FILE)"
    echo "# DO NOT ADD RFC1918 WILDCARDS"
    echo ""
    echo "172.31.240.2   claude-sdk-host"
    echo "172.31.240.35  sdk-egress"
    
    # Extract MCP endpoint hosts if present
    MCP_HOSTS=$(jq -r '.applications[]?.mcp_endpoints[]?' "$CONFIG_FILE" 2>/dev/null | sed -E 's|^https?://([^:/]+).*|\1|' | sort -u || true)
    for host in $MCP_HOSTS; do
        if [[ "$host" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
            echo "$host   mcp-endpoint-$host"
        fi
    done

    # Extract credential provider hosts if present
    PROV_URLS=$(jq -r '.credential_providers[]?.url?' "$CONFIG_FILE" 2>/dev/null | sed -E 's|^https?://([^:/]+).*|\1|' | sort -u || true)
    for host in $PROV_URLS; do
        if [[ "$host" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
            echo "$host   credential-provider-$host"
        fi
    done
else
    # Simple default output if jq is absent
    cat <<EOF
172.31.240.2   claude-sdk-host
172.31.240.35  sdk-egress
172.31.240.20  tms-execution-mcp
172.31.240.21  tms-credentials-provider
EOF
fi

echo ""
echo "=== Done ==="
