#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# sdk-egress entrypoint
# Validates secret configuration and executes GOST with mandatory upstream chaining.
# Fails closed on absent secrets, invalid config, or attempted debug body logging.
# ==============================================================================

CONFIG_FILE="${CONFIG_FILE:-/run/secrets/gost-config.json}"

echo "[sdk-egress] Starting egress forwarder check..."

# 1. Fail closed on absent or empty secret configuration
if [ ! -f "$CONFIG_FILE" ]; then
    echo "[sdk-egress] FATAL: Secret config file '$CONFIG_FILE' not found! Failing closed." >&2
    exit 1
fi

if [ ! -s "$CONFIG_FILE" ]; then
    echo "[sdk-egress] FATAL: Secret config file '$CONFIG_FILE' is empty! Failing closed." >&2
    exit 1
fi

# 2. Validate JSON syntax without eval
if command -v jq >/dev/null 2>&1; then
    if ! jq empty "$CONFIG_FILE" >/dev/null 2>&1; then
        echo "[sdk-egress] FATAL: Invalid JSON in '$CONFIG_FILE'! Failing closed." >&2
        exit 1
    fi

    # Verify Debug logging is false (strictly prohibit HTTP body/header logging)
    DEBUG_VAL=$(jq -r '.Debug // false' "$CONFIG_FILE")
    if [ "$DEBUG_VAL" = "true" ]; then
        echo "[sdk-egress] FATAL: Debug logging enabled in '$CONFIG_FILE'! Header/body logging is forbidden." >&2
        exit 1
    fi

    # Verify ServeNodes contains HTTP frontend
    SERVE_COUNT=$(jq '.ServeNodes | length' "$CONFIG_FILE")
    if [ "$SERVE_COUNT" -lt 1 ]; then
        echo "[sdk-egress] FATAL: No ServeNodes defined in '$CONFIG_FILE'." >&2
        exit 1
    fi

    # Verify ChainNodes contains mandatory upstream
    CHAIN_COUNT=$(jq '.ChainNodes | length' "$CONFIG_FILE")
    if [ "$CHAIN_COUNT" -lt 1 ]; then
        echo "[sdk-egress] FATAL: No ChainNodes defined in '$CONFIG_FILE'! Mandatory upstream required." >&2
        exit 1
    fi

    # Verify each ChainNode has a valid upstream protocol (socks5 or http)
    for i in $(seq 0 $((CHAIN_COUNT - 1))); do
        NODE_URL=$(jq -r ".ChainNodes[$i]" "$CONFIG_FILE")
        if [[ ! "$NODE_URL" =~ ^(socks5|http|https):// ]]; then
            echo "[sdk-egress] FATAL: Invalid upstream node protocol in ChainNodes[$i]: '$NODE_URL'" >&2
            exit 1
        fi
    done
else
    # Fallback syntax check if jq is not present
    if ! grep -q '"ChainNodes"' "$CONFIG_FILE"; then
        echo "[sdk-egress] FATAL: Missing 'ChainNodes' in '$CONFIG_FILE'." >&2
        exit 1
    fi
    if grep -q '"Debug"[[:space:]]*:[[:space:]]*true' "$CONFIG_FILE"; then
        echo "[sdk-egress] FATAL: Debug logging enabled in '$CONFIG_FILE'." >&2
        exit 1
    fi
fi

echo "[sdk-egress] Configuration validated successfully. Mandatory upstream chaining enforced."
echo "[sdk-egress] Launching GOST forwarder..."

# Execute GOST with secret configuration file
exec /usr/local/bin/gost -C "$CONFIG_FILE"
