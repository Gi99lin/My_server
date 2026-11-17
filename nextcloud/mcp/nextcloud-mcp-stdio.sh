#!/usr/bin/env bash
# Local stdio MCP server for the Nextcloud personal hub.
# Reads the app password from the macOS Keychain and starts a pinned
# nextcloud-mcp-server. Installed as ~/.local/bin/nextcloud-mcp (symlink).
# Stdout carries MCP traffic only; diagnostics go to stderr.
set -euo pipefail

host="${NEXTCLOUD_MCP_HOST:-https://cloud.gigglin.tech}"
user="${NEXTCLOUD_MCP_USER:-admin}"
service="HomeLab nextcloud-mcp"
version="0.213.1"

die() { echo "nextcloud-mcp: $*" >&2; exit 1; }

# Claude Desktop starts this without a login shell, so set a usable PATH.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

password=$(/usr/bin/timeout 5 /usr/bin/security find-generic-password \
  -s "$service" -a "$user" -w 2>/dev/null) \
  || die "no app password in Keychain (service '$service', account '$user')"
[[ -n "$password" ]] || die "empty app password in Keychain"

command -v uvx >/dev/null || die "uvx not found in PATH"

NEXTCLOUD_HOST="$host" NEXTCLOUD_USERNAME="$user" NEXTCLOUD_PASSWORD="$password" \
  exec uvx "nextcloud-mcp-server==$version" run --transport stdio --no-oauth \
    --enable-app calendar --enable-app notes --enable-app webdav
