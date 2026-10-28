#!/usr/bin/env sh
set -eu
CONFIG_FILE="${CONFIG_FILE:-/run/secrets/gost-config.json}"
# URL parsing/allowlist validation never emits a URL, request or credential.
python3 /usr/local/lib/validate_config.py "$CONFIG_FILE" /tmp/gost-runtime.json
exec /usr/local/bin/gost -C /tmp/gost-runtime.json >/dev/null 2>&1
