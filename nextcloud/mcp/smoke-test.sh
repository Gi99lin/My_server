#!/usr/bin/env bash
# Smoke test for the local Nextcloud MCP wrapper.
# Sends an MCP initialize + tools/list over stdio and checks the answers.
# Usage: smoke-test.sh [path-to-wrapper]   (default: ~/.local/bin/nextcloud-mcp)
set -euo pipefail
wrapper="${1:-$HOME/.local/bin/nextcloud-mcp}"
[[ -x "$wrapper" ]] || { echo "FAIL: $wrapper is not executable"; exit 1; }

requests='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"smoke-test","version":"1"}}}
{"jsonrpc":"2.0","method":"notifications/initialized"}
{"jsonrpc":"2.0","id":2,"method":"tools/list"}'

# Keep stdin open long enough for the server to answer, then close it.
out=$( { echo "$requests"; sleep "${SMOKE_WAIT:-20}"; } | timeout 90 "$wrapper" 2>/dev/null || true )

python3 -I - "$out" <<'PY'
import json, sys
msgs = {}
for line in sys.argv[1].splitlines():
    try:
        m = json.loads(line)
    except ValueError:
        continue
    if "id" in m:
        msgs[m["id"]] = m
init, tools = msgs.get(1, {}), msgs.get(2, {})
if "serverInfo" not in init.get("result", {}):
    sys.exit("FAIL: no serverInfo in initialize response")
names = [t["name"] for t in tools.get("result", {}).get("tools", [])]
if not any("calendar" in n for n in names):
    sys.exit(f"FAIL: no calendar tools in tools/list ({len(names)} tools)")
print(f"PASS: {init['result']['serverInfo'].get('name')} with {len(names)} tools")
PY
