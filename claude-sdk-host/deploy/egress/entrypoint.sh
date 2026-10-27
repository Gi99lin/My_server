#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# sdk-egress entrypoint
# Validates secret configuration and executes GOST with mandatory upstream chaining.
# Fails closed on absent secrets, invalid config, query options, or bypass attempts.
# Never prints ChainNode strings (may contain credentials) or request headers.
# ==============================================================================

CONFIG_FILE="${CONFIG_FILE:-/run/secrets/gost-config.json}"

echo "[sdk-egress] Starting egress forwarder validation..."

# 1. Fail closed on absent or empty secret configuration
if [ ! -f "$CONFIG_FILE" ]; then
    echo "[sdk-egress] FATAL: Secret config file '$CONFIG_FILE' not found! Failing closed." >&2
    exit 1
fi

if [ ! -s "$CONFIG_FILE" ]; then
    echo "[sdk-egress] FATAL: Secret config file '$CONFIG_FILE' is empty! Failing closed." >&2
    exit 1
fi

# 2. Validate JSON syntax using jq (no debug fallback grep parser)
if ! command -v jq >/dev/null 2>&1; then
    echo "[sdk-egress] FATAL: jq utility is required for secure JSON validation. Failing closed." >&2
    exit 1
fi

if ! jq empty "$CONFIG_FILE" >/dev/null 2>&1; then
    echo "[sdk-egress] FATAL: Invalid JSON syntax in '$CONFIG_FILE'! Failing closed." >&2
    exit 1
fi

# Verify Debug logging is false (strictly prohibit HTTP body/header debug logging)
DEBUG_VAL=$(jq -r 'if has("Debug") then .Debug else null end' "$CONFIG_FILE")
if [ "$DEBUG_VAL" != "false" ]; then
    echo "[sdk-egress] FATAL: 'Debug' must be explicitly set to false. Header/body logging forbidden." >&2
    exit 1
fi

# Reject bypass or direct route configurations
BYPASS_VAL=$(jq -r '.Bypass // empty' "$CONFIG_FILE")
ROUTES_VAL=$(jq -r '.Routes // empty' "$CONFIG_FILE")
if [ -n "$BYPASS_VAL" ] || [ -n "$ROUTES_VAL" ]; then
    echo "[sdk-egress] FATAL: Bypass or Routes configurations are forbidden. Mandatory chaining required." >&2
    exit 1
fi

# Verify ServeNodes contains exactly one HTTP listener
SERVE_COUNT=$(jq '.ServeNodes | length' "$CONFIG_FILE" 2>/dev/null || echo 0)
if [ "$SERVE_COUNT" -ne 1 ]; then
    echo "[sdk-egress] FATAL: Exactly one HTTP listener required in ServeNodes (found: $SERVE_COUNT)." >&2
    exit 1
fi

SERVE_NODE=$(jq -r '.ServeNodes[0]' "$CONFIG_FILE")
if [[ "$SERVE_NODE" == *"?"* ]]; then
    echo "[sdk-egress] FATAL: Query options in ServeNodes are forbidden." >&2
    exit 1
fi

if [[ ! "$SERVE_NODE" =~ ^http://(:[0-9]+|[0-9\.]+:[0-9]+)$ ]]; then
    echo "[sdk-egress] FATAL: ServeNode must be an HTTP listener (e.g. http://:8080)." >&2
    exit 1
fi

# Verify ChainNodes contains exactly one configured supported parent
CHAIN_COUNT=$(jq '.ChainNodes | length' "$CONFIG_FILE" 2>/dev/null || echo 0)
if [ "$CHAIN_COUNT" -ne 1 ]; then
    echo "[sdk-egress] FATAL: Exactly one parent upstream proxy required in ChainNodes (found: $CHAIN_COUNT)." >&2
    exit 1
fi

CHAIN_NODE=$(jq -r '.ChainNodes[0]' "$CONFIG_FILE")
if [[ "$CHAIN_NODE" == *"?"* ]]; then
    echo "[sdk-egress] FATAL: Query options in ChainNodes are forbidden." >&2
    exit 1
fi

# Reject direct/bypass in chain
if [[ "$CHAIN_NODE" == *"direct"* ]] || [[ "$CHAIN_NODE" == *"bypass"* ]]; then
    echo "[sdk-egress] FATAL: Direct or bypass routes in ChainNodes are forbidden." >&2
    exit 1
fi

# Verify supported parent proxy scheme (socks5, http, https) without printing the node string
if [[ ! "$CHAIN_NODE" =~ ^(socks5|http|https):// ]]; then
    echo "[sdk-egress] FATAL: Unsupported parent proxy scheme in ChainNodes. Only socks5, http, or https allowed." >&2
    exit 1
fi

echo "[sdk-egress] Configuration successfully validated. Mandatory upstream chaining enforced."
echo "[sdk-egress] Launching GOST forwarder (suppressing credential URLs and authorization headers)..."

# Execute GOST while suppressing untrusted request/error logs containing headers or credential URLs
exec /usr/local/bin/gost -C "$CONFIG_FILE" >/dev/null 2>&1
