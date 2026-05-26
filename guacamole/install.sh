#!/usr/bin/env bash
# Install / bootstrap Guacamole stack.
# Idempotent: safe to re-run; will not wipe pgdata.

set -euo pipefail

cd "$(dirname "$0")"

# 1. Ensure .env exists; create from template with a random password on first run.
if [[ ! -f .env ]]; then
  echo "[+] First run: generating .env with random POSTGRES_PASSWORD"
  cp .env.example .env
  RANDOM_PASS="$(openssl rand -hex 24)"
  # macOS sed needs '' after -i; GNU sed doesn't. Use a portable approach.
  sed -i.bak "s|replace_me_with_random_value|${RANDOM_PASS}|" .env
  rm -f .env.bak
fi

# 2. Generate Postgres schema for Guacamole (one-time, image-version-pinned).
if [[ ! -f init/initdb.sql ]]; then
  echo "[+] Generating init/initdb.sql from guacamole image"
  docker run --rm guacamole/guacamole:1.5.5 \
    /opt/guacamole/bin/initdb.sh --postgresql > init/initdb.sql
fi

# 3. Bring the stack up.
echo "[+] Starting Guacamole stack"
docker compose up -d

echo
echo "[✓] Done. Access via SSH tunnel from your laptop:"
echo "    ssh -L 8080:127.0.0.1:8080 <user>@<server>"
echo "    Then open http://localhost:8080/guacamole"
echo
echo "    Default login: guacadmin / guacadmin  (change immediately!)"
