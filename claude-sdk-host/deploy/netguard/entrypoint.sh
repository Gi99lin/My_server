#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# netguard entrypoint
# Applies fail-closed atomic nftables IPv4/IPv6 rules inside the shared namespace
# before marking itself healthy.
# ==============================================================================

echo "[netguard] Starting network namespace guard initialization..."

# Helper: strict IPv4 CIDR validation (e.g. 172.31.240.0/28)
validate_ipv4_cidr() {
    local val="$1"
    local name="$2"
    if [[ ! "$val" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}/[0-9]{1,2}$ ]]; then
        echo "[netguard] FATAL: Invalid IPv4 CIDR for $name: '$val'" >&2
        exit 1
    fi
}

# Helper: strict IPv4 address validation (e.g. 172.31.240.35)
validate_ipv4_addr() {
    local val="$1"
    local name="$2"
    if [[ ! "$val" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
        echo "[netguard] FATAL: Invalid IPv4 address for $name: '$val'" >&2
        exit 1
    fi
}

# Helper: strict integer port validation (e.g. 8080)
validate_port() {
    local val="$1"
    local name="$2"
    if [[ ! "$val" =~ ^[0-9]+$ ]] || [ "$val" -lt 1 ] || [ "$val" -gt 65535 ]; then
        echo "[netguard] FATAL: Invalid port for $name: '$val'" >&2
        exit 1
    fi
}

# 1. Environment & variable validation (No eval, strict matching)
CLIENTS_SUBNET="${CLIENTS_SUBNET:-172.31.240.0/28}"
TOOLS_SUBNET="${TOOLS_SUBNET:-172.31.240.16/28}"
PROXY_IP="${PROXY_IP:-172.31.240.35}"
PROXY_PORT="${PROXY_PORT:-8080}"
API_PORT="${API_PORT:-8080}"

validate_ipv4_cidr "$CLIENTS_SUBNET" "CLIENTS_SUBNET"
validate_ipv4_cidr "$TOOLS_SUBNET" "TOOLS_SUBNET"
validate_ipv4_addr "$PROXY_IP" "PROXY_IP"
validate_port "$PROXY_PORT" "PROXY_PORT"
validate_port "$API_PORT" "API_PORT"

# Validate ALLOWED_INTERNAL_IPS (comma-separated list of IPv4 addresses)
ALLOWED_INTERNAL_IPS="${ALLOWED_INTERNAL_IPS:-}"
INTERNAL_IP_ELEMENTS=""
if [ -n "$ALLOWED_INTERNAL_IPS" ]; then
    IFS=',' read -ra IP_ARRAY <<< "$ALLOWED_INTERNAL_IPS"
    for ip in "${IP_ARRAY[@]}"; do
        ip_trimmed=$(echo "$ip" | tr -d '[:space:]')
        if [ -n "$ip_trimmed" ]; then
            validate_ipv4_addr "$ip_trimmed" "ALLOWED_INTERNAL_IPS item"
            if [ -z "$INTERNAL_IP_ELEMENTS" ]; then
                INTERNAL_IP_ELEMENTS="$ip_trimmed"
            else
                INTERNAL_IP_ELEMENTS="$INTERNAL_IP_ELEMENTS, $ip_trimmed"
            fi
        fi
    done
fi

# Validate ALLOWED_INTERNAL_PORTS (comma-separated list of ports)
ALLOWED_INTERNAL_PORTS="${ALLOWED_INTERNAL_PORTS:-}"
INTERNAL_PORT_ELEMENTS=""
if [ -n "$ALLOWED_INTERNAL_PORTS" ]; then
    IFS=',' read -ra PORT_ARRAY <<< "$ALLOWED_INTERNAL_PORTS"
    for p in "${PORT_ARRAY[@]}"; do
        p_trimmed=$(echo "$p" | tr -d '[:space:]')
        if [ -n "$p_trimmed" ]; then
            validate_port "$p_trimmed" "ALLOWED_INTERNAL_PORTS item"
            if [ -z "$INTERNAL_PORT_ELEMENTS" ]; then
                INTERNAL_PORT_ELEMENTS="$p_trimmed"
            else
                INTERNAL_PORT_ELEMENTS="$INTERNAL_PORT_ELEMENTS, $p_trimmed"
            fi
        fi
    done
fi

echo "[netguard] Variables validated:"
echo "  CLIENTS_SUBNET: $CLIENTS_SUBNET"
echo "  PROXY_IP:       $PROXY_IP:$PROXY_PORT"
echo "  API_PORT:       $API_PORT"
echo "  INTERNAL_IPS:   ${INTERNAL_IP_ELEMENTS:-<none>}"
echo "  INTERNAL_PORTS: ${INTERNAL_PORT_ELEMENTS:-<none>}"

# 2. Render atomic nftables ruleset
RULES_FILE="/tmp/nftables.rules"

cat <<EOF > "$RULES_FILE"
flush ruleset

table inet netguard {
EOF

if [ -n "$INTERNAL_IP_ELEMENTS" ]; then
cat <<EOF >> "$RULES_FILE"
    set allowed_internal_ips {
        type ipv4_addr
        elements = { $INTERNAL_IP_ELEMENTS }
    }
EOF
fi

if [ -n "$INTERNAL_PORT_ELEMENTS" ]; then
cat <<EOF >> "$RULES_FILE"
    set allowed_internal_ports {
        type inet_service
        elements = { $INTERNAL_PORT_ELEMENTS }
    }
EOF
fi

cat <<EOF >> "$RULES_FILE"
    chain input {
        type filter hook input priority filter; policy drop;

        # Allow established and related connections
        ct state established,related accept
        ct state invalid drop

        # Loopback: accept lo, but EXPLICITLY DROP Docker resolver 127.0.0.11
        iifname "lo" ip saddr 127.0.0.11 drop
        iifname "lo" ip daddr 127.0.0.11 drop
        iifname "lo" accept

        # Inbound API requests from authorized client subnet only
        ip saddr $CLIENTS_SUBNET tcp dport $API_PORT accept

        # Drop everything else
        drop
    }

    chain forward {
        type filter hook forward priority filter; policy drop;
        drop
    }

    chain output {
        type filter hook output priority filter; policy drop;

        # Allow established and related return traffic
        ct state established,related accept
        ct state invalid drop

        # Loopback: accept lo, but EXPLICITLY DROP Docker resolver 127.0.0.11
        oifname "lo" ip daddr 127.0.0.11 drop
        oifname "lo" accept

        # Drop ALL outbound DNS (UDP 53, TCP 53, DoT TCP 853)
        udp dport 53 drop
        tcp dport 53 drop
        tcp dport 853 drop

        # Drop all UDP/QUIC
        ip protocol udp drop
        ip6 nexthdr udp drop

        # Allow outbound TCP to egress proxy only on fixed proxy IP and port
        ip daddr $PROXY_IP tcp dport $PROXY_PORT accept
EOF

if [ -n "$INTERNAL_IP_ELEMENTS" ] && [ -n "$INTERNAL_PORT_ELEMENTS" ]; then
cat <<EOF >> "$RULES_FILE"

        # Allow outbound TCP to approved internal endpoints and ports
        ip daddr @allowed_internal_ips tcp dport @allowed_internal_ports accept
EOF
fi

cat <<EOF >> "$RULES_FILE"

        # Drop all other outbound IPv4 and IPv6 traffic (fail-closed)
        drop
    }
}
EOF

# 3. Apply atomic nftables ruleset
echo "[netguard] Applying atomic nftables ruleset from $RULES_FILE..."
if ! nft -f "$RULES_FILE"; then
    echo "[netguard] FATAL: Failed to apply nftables ruleset. Failing closed." >&2
    exit 1
fi
rm -f "$RULES_FILE"

# 4. Verify ruleset is active
if ! nft list table inet netguard >/dev/null 2>&1; then
    echo "[netguard] FATAL: Table inet netguard not present after load." >&2
    exit 1
fi

echo "[netguard] Ruleset successfully loaded and verified. Network namespace secured."

# 5. Keep alive and monitor
# Trap termination signals for clean shutdown
trap 'echo "[netguard] Shutting down..."; exit 0' SIGTERM SIGINT

while true; do
    if ! nft list table inet netguard >/dev/null 2>&1; then
        echo "[netguard] ERROR: Ruleset dropped unexpectedly! Exiting." >&2
        exit 1
    fi
    sleep 5 &
    wait $!
done
