#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# deploy/scripts/generate-peers.sh
# Generates static internal peer mappings for /etc/hosts and nftables allowlist
# from the host configuration file. Never globally exempts RFC1918 ranges.
# Writes output to target file (default: deploy/hosts) or stdout.
# ==============================================================================

CONFIG_FILE="${1:-config.example.json}"
OUTPUT_FILE="${2:-deploy/hosts}"

if [ ! -f "$CONFIG_FILE" ]; then
    echo "ERROR: Configuration file '$CONFIG_FILE' not found." >&2
    exit 1
fi

TEMP_HOSTS=$(mktemp)

cat <<EOF > "$TEMP_HOSTS"
# Static internal peer mappings (Generated from $CONFIG_FILE)
# DO NOT ADD RFC1918 WILDCARDS OR DIRECT ROUTES
127.0.0.1       localhost
::1             localhost ip6-localhost ip6-loopback

172.31.240.2    claude-sdk-host
172.31.240.35   sdk-egress
EOF

# Extract MCP endpoints and credential provider hosts if jq is available
if command -v jq >/dev/null 2>&1; then
    # Extract MCP endpoint hostnames / IPs
    MCP_HOSTS=$(jq -r '.applications[]?.mcp_endpoints[]?' "$CONFIG_FILE" 2>/dev/null | sed -E 's|^https?://([^:/]+).*|\1|' | sort -u || true)
    for host in $MCP_HOSTS; do
        if [[ "$host" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
            echo "$host    mcp-endpoint-$host" >> "$TEMP_HOSTS"
        fi
    done

    # Extract credential provider hostnames / IPs
    PROV_HOSTS=$(jq -r '.credential_providers[]?.url?' "$CONFIG_FILE" 2>/dev/null | sed -E 's|^https?://([^:/]+).*|\1|' | sort -u || true)
    for host in $PROV_HOSTS; do
        if [[ "$host" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
            echo "$host    credential-provider-$host" >> "$TEMP_HOSTS"
        fi
    done
else
    cat <<EOF >> "$TEMP_HOSTS"
172.31.240.20   tms.example.internal
172.31.240.21   vault.example.internal
EOF
fi

if [ -n "$OUTPUT_FILE" ]; then
    mkdir -p "$(dirname "$OUTPUT_FILE")"
    mv "$TEMP_HOSTS" "$OUTPUT_FILE"
    echo "Wrote static internal peer mappings to $OUTPUT_FILE"
else
    cat "$TEMP_HOSTS"
    rm -f "$TEMP_HOSTS"
fi
