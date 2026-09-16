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

# root's ~/.docker/config.json is a directory (not a file) on this host,
# which makes every docker exec/ps below print a harmless but noisy
# "Error parsing config file" warning. Point docker at a throwaway config
# dir instead of fixing/removing root's broken one.
export DOCKER_CONFIG="/tmp/restic-backup-docker-config"
mkdir -p "$DOCKER_CONFIG"

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

# --- Helper: run one dump command, log OK/size or FAILED, never abort the
# rest of the backup because one DB (of a dozen) couldn't be dumped ---
run_dump() {
  local desc="$1" outfile="$2"
  shift 2
  if "$@" > "$outfile" 2>>"$LOG_FILE"; then
    log "    OK ($(du -sh "$outfile" | cut -f1))"
  else
    log "    FAILED — $desc (see $LOG_FILE for details)"
  fi
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
  run_dump "nginx-proxy-manager-db" "$DUMP_DIR/npm-all-databases.sql" \
    docker exec nginx-proxy-manager-db \
      mysqldump --all-databases -uroot -p"${NPM_DB_ROOT_PASSWORD}" \
      --single-transaction --quick --lock-tables=false
else
  log "  nginx-proxy-manager-db not running — skipping"
fi

# Nextcloud (MariaDB) -------------------------------------------------
if container_running "nextcloud-db"; then
  log "  Dumping nextcloud-db (MariaDB)..."
  run_dump "nextcloud-db" "$DUMP_DIR/nextcloud-all-databases.sql" \
    docker exec nextcloud-db \
      mariadb-dump --all-databases -uroot -p"${NEXTCLOUD_DB_ROOT_PASSWORD:-mariadbroot}" \
      --default-character-set=utf8mb4 --single-transaction --quick --skip-extended-insert
else
  log "  nextcloud-db not running — skipping"
fi

# Marzneshin (MariaDB — NOT SQLite, prior comment was wrong) ----------
# The container name carries the compose project prefix
# (e.g. marzneshin-marzneshin-db-1), so resolve it by pattern instead
# of hardcoding "marzneshin-db" — otherwise the dump is silently skipped.
MARZ_DB=$(docker ps --format '{{.Names}}' | grep -E '^marzneshin.*db' | head -1 || true)
if [[ -n "$MARZ_DB" ]]; then
  if [[ -n "${MARZNESHIN_DB_ROOT_PASSWORD:-}" ]]; then
    log "  Dumping $MARZ_DB (MariaDB)..."
    run_dump "$MARZ_DB" "$DUMP_DIR/marzneshin-all-databases.sql" \
      docker exec "$MARZ_DB" \
        mariadb-dump --all-databases -uroot -p"${MARZNESHIN_DB_ROOT_PASSWORD}" \
        --single-transaction --quick --lock-tables=false
  else
    log "  $MARZ_DB running but MARZNESHIN_DB_ROOT_PASSWORD not set — skipping"
  fi
else
  log "  marzneshin-db not running — skipping"
fi

# LibreChat (MongoDB) -------------------------------------------------
if container_running "chat-mongodb"; then
  log "  Dumping chat-mongodb (MongoDB)..."
  run_dump "chat-mongodb" "$DUMP_DIR/librechat-mongo.archive.gz" \
    docker exec chat-mongodb \
      mongodump --archive --gzip
else
  log "  chat-mongodb not running — skipping"
fi

# AI Testcase Generator (Postgres) ------------------------------------
if container_running "testcase-db"; then
  if [[ -n "${TESTCASE_DB_PASSWORD:-}" ]]; then
    log "  Dumping testcase-db (Postgres)..."
    run_dump "testcase-db" "$DUMP_DIR/testcase-all-databases.sql" \
      docker exec -e PGPASSWORD="${TESTCASE_DB_PASSWORD}" testcase-db \
        pg_dumpall -U "${TESTCASE_DB_USER:-postgres}"
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
    run_dump "guacamole-postgres" "$DUMP_DIR/guacamole.sql" \
      docker exec -e PGPASSWORD="${GUAC_PASS}" guacamole-postgres \
        pg_dump -U "${GUAC_USER}" "${GUAC_DB}"
  else
    log "  guacamole-postgres running but $GUAC_ENV missing — skipping"
  fi
else
  log "  guacamole-postgres not running — skipping"
fi

# Manager Helper (Postgres) --------------------------------------------
if container_running "manager-helper-db"; then
  MH_ENV="$PROJECT_DIR/manager-helper/.env"
  MH_PASS=$(grep -E '^POSTGRES_PASSWORD=' "$MH_ENV" 2>/dev/null | cut -d= -f2)
  MH_PASS="${MH_PASS:-mh}"
  log "  Dumping manager-helper-db (Postgres)..."
  run_dump "manager-helper-db" "$DUMP_DIR/manager-helper.sql" \
    docker exec -e PGPASSWORD="${MH_PASS}" manager-helper-db \
      pg_dump -U mh mh
else
  log "  manager-helper-db not running — skipping"
fi

# HR Bot — resumatch-bot dev + prod (Postgres) -------------------------
# Separate git repo checked out at hrBot/ (not a submodule of this repo).
# Each environment has its own container, .env file and Postgres DB.
HRBOT_DIR="$PROJECT_DIR/hrBot"
dump_hrbot_env() {
  local env_name="$1" container="$2" env_file="$3"
  if container_running "$container"; then
    if [[ -f "$env_file" ]]; then
      local user pass db
      user=$(grep -E '^POSTGRES_USER=' "$env_file" | cut -d= -f2); user="${user:-resumatch_user}"
      pass=$(grep -E '^POSTGRES_PASSWORD=' "$env_file" | cut -d= -f2); pass="${pass:-secret_password}"
      db=$(grep -E '^POSTGRES_DB=' "$env_file" | cut -d= -f2); db="${db:-resumatch_db}"
      log "  Dumping $container (Postgres, hrBot $env_name)..."
      run_dump "$container" "$DUMP_DIR/hrbot-${env_name}.sql" \
        docker exec -e PGPASSWORD="${pass}" "$container" \
          pg_dump -U "${user}" "${db}"
    else
      log "  $container running but $env_file missing — skipping"
    fi
  else
    log "  $container not running — skipping"
  fi
}
dump_hrbot_env "prod" "hrbot_prod_db" "$HRBOT_DIR/.env.prod"
dump_hrbot_env "dev"  "hrbot_dev_db"  "$HRBOT_DIR/.env.dev"

# Agentfarm / workInfra — shared Postgres for Dify+Langfuse+n8n+LiteLLM -
# Separate project outside this repo (~/workInfra, sibling of My_server).
# One Postgres instance hosts several app databases, so dump everything
# + roles via pg_dumpall instead of a single database.
WORKINFRA_ENV="$(dirname "$PROJECT_DIR")/workInfra/.env"
if container_running "agentfarm-postgres"; then
  if [[ -f "$WORKINFRA_ENV" ]]; then
    AF_USER=$(grep -E '^POSTGRES_USER=' "$WORKINFRA_ENV" | cut -d= -f2)
    AF_PASS=$(grep -E '^POSTGRES_PASSWORD=' "$WORKINFRA_ENV" | cut -d= -f2)
    log "  Dumping agentfarm-postgres (Postgres, all databases)..."
    run_dump "agentfarm-postgres" "$DUMP_DIR/agentfarm-all-databases.sql" \
      docker exec -e PGPASSWORD="${AF_PASS}" agentfarm-postgres \
        pg_dumpall -U "${AF_USER}"
  else
    log "  agentfarm-postgres running but $WORKINFRA_ENV missing — skipping"
  fi
else
  log "  agentfarm-postgres not running — skipping"
fi

# LibreChat code-interpreter vector DB (pgvector) -----------------------
# Credentials match the hardcoded defaults in librechat/docker-compose.yml;
# override via backup/.env (LIBRECHAT_VECTORDB_*) if that file ever changes.
if container_running "chat-vectordb"; then
  log "  Dumping chat-vectordb (Postgres/pgvector)..."
  run_dump "chat-vectordb" "$DUMP_DIR/chat-vectordb.sql" \
    docker exec -e PGPASSWORD="${LIBRECHAT_VECTORDB_PASSWORD:-mypassword}" chat-vectordb \
      pg_dump -U "${LIBRECHAT_VECTORDB_USER:-myuser}" "${LIBRECHAT_VECTORDB_DB:-mydatabase}"
else
  log "  chat-vectordb not running — skipping"
fi

# libvirt VM definitions ---------------------------------------------
# Dump XML of every defined domain so the VM can be re-defined on a
# fresh host without manually clicking through virt-install again.
if command -v virsh >/dev/null 2>&1; then
  log "  Dumping libvirt domain XMLs..."
  mkdir -p "$DUMP_DIR/libvirt"
  for dom in $(virsh list --all --name | grep -v '^$'); do
    run_dump "libvirt domain $dom" "$DUMP_DIR/libvirt/${dom}.xml" virsh dumpxml "$dom"
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
