#!/usr/bin/env sh
set -eu
if [ "$#" -ne 1 ]; then
    echo "Usage: local-login.sh /absolute/operator/local.env" >&2
    exit 1
fi
# This is an operator-owned local environment file, not an HTTP input.
set -a
. "$1"
set +a
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$SCRIPT_DIR/login-maintenance.sh"
