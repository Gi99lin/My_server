#!/usr/bin/env bash
# YouTrack Server — first-time install helper.
# The official image runs as uid 13001 and refuses to start if the mounted
# directories are missing or owned by anyone else.
set -euo pipefail
cd "$(dirname "$0")"

mkdir -p data conf logs backups
sudo chown -R 13001:13001 data conf logs backups

docker compose up -d

echo
echo "YouTrack is starting (first boot takes a couple of minutes)."
echo "1. Open http://<server-ip>:8899 — the Configuration Wizard will ask for a token:"
echo "   docker exec youtrack cat /opt/youtrack/conf/internal/services/configurationWizard/wizard_token.txt"
echo "2. In the wizard set Base URL to https://youtrack.gigglin.tech and create the admin user."
echo "3. Add a Proxy Host in NPM: youtrack.gigglin.tech -> youtrack:8080 (scheme http,"
echo "   enable Websockets Support + Block Common Exploits, request SSL cert)."
echo "4. Create a permanent token (Profile -> Account Security -> Tokens, scope: YouTrack),"
echo "   put it into .env (YT_TOKEN) and run the preset bootstrap:"
echo "   python3 bootstrap/bootstrap_youtrack.py"
