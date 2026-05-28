#!/bin/bash
# =============================================================
# backup.sh — Daily server backup to Backblaze B2 via Restic
# =============================================================
# Runs automatically via cron at 03:00 every day.
# Backs up: /home/gigglin/ + /var/lib/docker/volumes/ + DB dumps
#           + libvirt VM disks + libvirt XML + /etc/iptables
# =============================================================

set -euo pipefail

# --- Config ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"
LOG_FILE="/var/log/restic-backup.log"
DUMP_DIR="/tmp/restic-db-dumps"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

# --- Load credentials ---
if [[ ! -f "$ENV_FILE" ]]; then
  echo "[$TIMESTAMP] ERROR: .env file not found at $ENV_FILE" | tee -a "$LOG_FILE"
  exit 1
fi
# shellcheck source=.env
source "$ENV_FILE"

export B2_ACCOUNT_ID
export B2_ACCOUNT_KEY
export RESTIC_PASSWORD
export RESTIC_REPOSITORY="b2:${B2_BUCKET_NAME}"

# --- Logging helper ---
log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

# --- Telegram notification (optional) ---
notify() {
  local msg="$1"
  if [[ -n "${TELEGRAM_BOT_TOKEN:-}" && -n "${TELEGRAM_CHAT_ID:-}" ]]; then
    curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
      -d chat_id="${TELEGRAM_CHAT_ID}" \
      -d text="🖥️ Backup server: ${msg}" \
      -d parse_mode="Markdown" > /dev/null 2>&1 || true
  fi
}

# --- Helper: dump a DB only if the container is running ---
container_running() {
  docker ps --format '{{.Names}}' | grep -q "^${1}$"
}

# --- Rotate logs (keep last 5000 lines) ---
if [[ -f "$LOG_FILE" ]] && [[ $(wc -l < "$LOG_FILE") -gt 5000 ]]; then
  tail -5000 "$LOG_FILE" > "${LOG_FILE}.tmp" && mv "${LOG_FILE}.tmp" "$LOG_FILE"
fi

log "=========================================="
log "Starting backup"
log "=========================================="
BACKUP_START=$(date +%s)

# --- 1. Database dumps ---
# Each block: check container is running, dump to $DUMP_DIR, skip on failure.
# Skipping is preferred over failing the whole backup — a missing DB dump is
# better than no backup at all.
log "Step 1: Dumping databases..."
mkdir -p "$DUMP_DIR"
chmod 700 "$DUMP_DIR"

# Nginx Proxy Manager (MariaDB) ---------------------------------------
if container_running "nginx-proxy-manager-db"; then
  log "  Dumping nginx-proxy-manager-db (MariaDB)..."
  docker exec nginx-proxy-manager-db \
    mysqldump --all-databases -uroot -p"${NPM_DB_ROOT_PASSWORD}" \
    --single-transaction --quick --lock-tables=false \
    > "$DUMP_DIR/npm-all-databases.sql" 2>>"$LOG_FILE"
  log "    OK ($(du -sh "$DUMP_DIR/npm-all-databases.sql" | cut -f1))"
else
  log "  nginx-proxy-manager-db not running — skipping"
fi

# Nextcloud (MariaDB) -------------------------------------------------
if container_running "nextcloud-db"; then
  log "  Dumping nextcloud-db (MariaDB)..."
  docker exec nextcloud-db \
    mariadb-dump --all-databases -uroot -p"${NEXTCLOUD_DB_ROOT_PASSWORD:-mariadbroot}" \
    --default-character-set=utf8mb4 --single-transaction --quick --skip-extended-insert \
    > "$DUMP_DIR/nextcloud-all-databases.sql" 2>>"$LOG_FILE"
  log "    OK ($(du -sh "$DUMP_DIR/nextcloud-all-databases.sql" | cut -f1))"
else
  log "  nextcloud-db not running — skipping"
fi

# Marzneshin (MariaDB — NOT SQLite, prior comment was wrong) ----------
# The container name carries the compose project prefix
# (e.g. marzneshin-marzneshin-db-1), so resolve it by pattern instead
# of hardcoding "marzneshin-db" — otherwise the dump is silently skipped.
MARZ_DB=$(docker ps --format '{{.Names}}' | grep -E '^marzneshin.*db' | head -1)
if [[ -n "$MARZ_DB" ]]; then
  if [[ -n "${MARZNESHIN_DB_ROOT_PASSWORD:-}" ]]; then
    log "  Dumping $MARZ_DB (MariaDB)..."
    docker exec "$MARZ_DB" \
      mariadb-dump --all-databases -uroot -p"${MARZNESHIN_DB_ROOT_PASSWORD}" \
      --single-transaction --quick --lock-tables=false \
      > "$DUMP_DIR/marzneshin-all-databases.sql" 2>>"$LOG_FILE"
    log "    OK ($(du -sh "$DUMP_DIR/marzneshin-all-databases.sql" | cut -f1))"
  else
    log "  $MARZ_DB running but MARZNESHIN_DB_ROOT_PASSWORD not set — skipping"
  fi
else
  log "  marzneshin-db not running — skipping"
fi

# LibreChat (MongoDB) -------------------------------------------------
if container_running "chat-mongodb"; then
  log "  Dumping chat-mongodb (MongoDB)..."
  docker exec chat-mongodb \
    mongodump --archive --gzip \
    > "$DUMP_DIR/librechat-mongo.archive.gz" 2>>"$LOG_FILE"
  log "    OK ($(du -sh "$DUMP_DIR/librechat-mongo.archive.gz" | cut -f1))"
else
  log "  chat-mongodb not running — skipping"
fi

# AI Testcase Generator (Postgres) ------------------------------------
if container_running "testcase-db"; then
  if [[ -n "${TESTCASE_DB_PASSWORD:-}" ]]; then
    log "  Dumping testcase-db (Postgres)..."
    docker exec -e PGPASSWORD="${TESTCASE_DB_PASSWORD}" testcase-db \
      pg_dumpall -U "${TESTCASE_DB_USER:-postgres}" \
      > "$DUMP_DIR/testcase-all-databases.sql" 2>>"$LOG_FILE"
    log "    OK ($(du -sh "$DUMP_DIR/testcase-all-databases.sql" | cut -f1))"
  else
    log "  testcase-db running but TESTCASE_DB_PASSWORD not set — skipping"
  fi
else
  log "  testcase-db not running — skipping"
fi

# Guacamole (Postgres) ------------------------------------------------
# Reads credentials directly from guacamole/.env to avoid duplicating
# the password across two .env files.
if container_running "guacamole-postgres"; then
  GUAC_ENV="$PROJECT_DIR/guacamole/.env"
  if [[ -f "$GUAC_ENV" ]]; then
    # shellcheck source=/dev/null
    GUAC_USER=$(grep -E '^POSTGRES_USER=' "$GUAC_ENV" | cut -d= -f2)
    GUAC_DB=$(grep -E '^POSTGRES_DB=' "$GUAC_ENV" | cut -d= -f2)
    GUAC_PASS=$(grep -E '^POSTGRES_PASSWORD=' "$GUAC_ENV" | cut -d= -f2)
    GUAC_USER="${GUAC_USER:-guacamole_user}"
    GUAC_DB="${GUAC_DB:-guacamole_db}"
    log "  Dumping guacamole-postgres..."
    docker exec -e PGPASSWORD="${GUAC_PASS}" guacamole-postgres \
      pg_dump -U "${GUAC_USER}" "${GUAC_DB}" \
      > "$DUMP_DIR/guacamole.sql" 2>>"$LOG_FILE"
    log "    OK ($(du -sh "$DUMP_DIR/guacamole.sql" | cut -f1))"
  else
    log "  guacamole-postgres running but $GUAC_ENV missing — skipping"
  fi
else
  log "  guacamole-postgres not running — skipping"
fi

# libvirt VM definitions ---------------------------------------------
# Dump XML of every defined domain so the VM can be re-defined on a
# fresh host without manually clicking through virt-install again.
if command -v virsh >/dev/null 2>&1; then
  log "  Dumping libvirt domain XMLs..."
  mkdir -p "$DUMP_DIR/libvirt"
  for dom in $(virsh list --all --name | grep -v '^$'); do
    virsh dumpxml "$dom" > "$DUMP_DIR/libvirt/${dom}.xml" 2>>"$LOG_FILE"
    log "    OK ${dom}.xml"
  done
else
  log "  virsh not installed — skipping libvirt XML dump"
fi

# --- 2. Restic backup ---
log "Step 2: Running restic backup..."

# /var/lib/libvirt/images contains the Win10 qcow2 (worth backing up,
# restic dedupes well) plus install ISOs (4-5 GB each, easy to re-download
# from Microsoft / fedorapeople). Exclude the ISOs.
restic backup \
  /home/gigglin/ \
  /var/lib/docker/volumes/ \
  /srv/nextcloud-data \
  /var/lib/libvirt/images \
  /etc/libvirt/qemu \
  /etc/iptables \
  /var/lib/marznode \
  "$DUMP_DIR" \
  --exclude="/home/gigglin/.cache" \
  --exclude="/home/gigglin/.local/share/Trash" \
  --exclude="/home/gigglin/snap" \
  --exclude="/var/lib/libvirt/images/*.iso" \
  --exclude="*.tmp" \
  --exclude="*.log.gz" \
  --exclude="node_modules" \
  --exclude="__pycache__" \
  --exclude=".git/objects/pack" \
  --tag "daily" \
  --tag "auto" \
  --verbose=1 \
  2>&1 | tee -a "$LOG_FILE"

log "Step 2: Restic backup complete"

# --- 3. Forget old snapshots (retention policy) ---
log "Step 3: Applying retention policy..."
restic forget \
  --keep-daily 30 \
  --keep-weekly 8 \
  --keep-monthly 12 \
  --prune \
  2>&1 | tee -a "$LOG_FILE"
log "Step 3: Retention policy applied"

# --- 4. Verify integrity (weekly — on Sundays) ---
if [[ "$(date '+%u')" == "7" ]]; then
  log "Step 4: Running weekly integrity check..."
  restic check 2>&1 | tee -a "$LOG_FILE"
  log "Step 4: Integrity check complete"
fi

# --- 5. Cleanup temp dumps ---
rm -rf "$DUMP_DIR"

# --- Summary ---
BACKUP_END=$(date +%s)
DURATION=$(( BACKUP_END - BACKUP_START ))
DURATION_MIN=$(( DURATION / 60 ))
DURATION_SEC=$(( DURATION % 60 ))

log "=========================================="
log "Backup completed in ${DURATION_MIN}m ${DURATION_SEC}s"
log "=========================================="

notify "✅ Backup completed successfully in ${DURATION_MIN}m ${DURATION_SEC}s"
