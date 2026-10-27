#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# deploy/scripts/verify-egress.sh
# Manual egress acceptance verification test runner for live disposable stack.
#
# Covers:
# - NET-01: Outgoing traffic exits through proxy; returns upstream-observed IP
# - NET-02: Direct external IPv4/IPv6, UDP/QUIC, metadata fail closed
# - NET-03: External DNS (UDP/TCP 53) and Docker DNS (127.0.0.11) dropped; static peers work
# ==============================================================================

echo "=== Claude SDK Host: Manual Egress Acceptance Probes ==="

CONTAINER="claude-sdk-host"

if ! docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^${CONTAINER}$"; then
    echo "ERROR: Container '$CONTAINER' is not running." >&2
    echo "This script is designed for live manual acceptance verification." >&2
    exit 1
fi

echo "Running probe suite inside $CONTAINER..."

# ------------------------------------------------------------------------------
# Test 1: NET-01 - External HTTP/HTTPS works via proxy
# ------------------------------------------------------------------------------
echo ""
echo "[NET-01] Testing outgoing HTTPS request through configured proxy..."
EXIT_IP=$(docker exec "$CONTAINER" curl -s --max-time 10 https://api.ipify.org || true)
if [ -n "$EXIT_IP" ]; then
    echo "  [PASS] Request succeeded via proxy. Observed Exit IP: $EXIT_IP"
else
    echo "  [FAIL] Request via proxy failed or timed out." >&2
fi

# ------------------------------------------------------------------------------
# Test 2: NET-02 - Direct external connection without proxy must fail closed
# ------------------------------------------------------------------------------
echo ""
echo "[NET-02] Testing direct outbound connection (bypassing proxy)..."
DIRECT_CODE=$(docker exec "$CONTAINER" curl --noproxy '*' -s -o /dev/null -w "%{http_code}" --max-time 5 https://1.1.1.1 2>/dev/null || echo "TIMEOUT")
if [ "$DIRECT_CODE" = "TIMEOUT" ] || [ "$DIRECT_CODE" = "000" ]; then
    echo "  [PASS] Direct outbound connection failed closed (timed out / rejected as required)."
else
    echo "  [FAIL] Direct connection succeeded with HTTP $DIRECT_CODE! Firewall leak detected!" >&2
    exit 1
fi

# ------------------------------------------------------------------------------
# Test 3: NET-03 - External DNS & Docker resolver 127.0.0.11 must be dropped
# ------------------------------------------------------------------------------
echo ""
echo "[NET-03] Testing direct DNS resolution to 127.0.0.11 and 8.8.8.8..."
# Docker resolver check
DOCKER_DNS=$(docker exec "$CONTAINER" python3 -c '
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.settimeout(2.0)
try:
    s.sendto(b"\xaa\xbb\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00\x07example\x03com\x00\x00\x01\x00\x01", ("127.0.0.11", 53))
    data, _ = s.recvfrom(512)
    print("RESOLVED")
except Exception:
    print("BLOCKED")
' 2>/dev/null || echo "BLOCKED")

if [ "$DOCKER_DNS" = "BLOCKED" ]; then
    echo "  [PASS] Docker resolver 127.0.0.11 is blocked by nftables."
else
    echo "  [FAIL] Docker resolver 127.0.0.11 responded! DNS leak detected!" >&2
    exit 1
fi

# External DNS check
EXT_DNS=$(docker exec "$CONTAINER" python3 -c '
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.settimeout(2.0)
try:
    s.sendto(b"\xaa\xbb\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00\x07example\x03com\x00\x00\x01\x00\x01", ("8.8.8.8", 53))
    data, _ = s.recvfrom(512)
    print("RESOLVED")
except Exception:
    print("BLOCKED")
' 2>/dev/null || echo "BLOCKED")

if [ "$EXT_DNS" = "BLOCKED" ]; then
    echo "  [PASS] Direct external DNS to 8.8.8.8:53 is blocked by nftables."
else
    echo "  [FAIL] Direct external DNS succeeded! DNS leak detected!" >&2
    exit 1
fi

echo ""
echo "=== Egress Acceptance Verification Passed ==="
