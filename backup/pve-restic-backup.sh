#!/usr/bin/env bash
# ==============================================================================
# pve-restic-backup.sh — Centralized Off-Site Backup to Backblaze B2 from PVE
# ==============================================================================
# 1. Triggers consistent DB dumps inside each contour VM via qemu-guest-agent
#    (virtio-serial, zero inter-VLAN firewall holes, zero DB passwords on PVE).
# 2. Exports Proxmox (/etc/pve + host network/LVM) & OpenWrt router configs.
# 3. Takes brief fsfreeze + read-only LVM-thin snapshots of all 7 Linux VMs,
#    mounts them read-only (ro,norecovery), and runs a single deduplicated
#    restic backup to Backblaze B2 (--host gigglin-pve).
# 4. Cleans up mounts/snapshots via EXIT trap and sends Telegram report via QGA.
# ==============================================================================

set -Eeuo pipefail

# Cron does not include administrative tool directories in its default PATH.
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"
LOG_FILE="/var/log/pve-restic-backup.log"
HOST_CFG_DIR="/var/backups/pve-host-configs"
SNAP_MNT_BASE="/mnt/restic-snaps"

CONTOURS=(
  "111:edge"
  "120:personal"
  "130:apps"
  "140:dev"
  "150:agents"
  "160:llm"
  "171:corp-gw"
)

# Windows corporate VM: no guest agent and an NTFS disk, so it is backed up
# as one raw, crash-consistent disk image instead of mounted files.
WIN_VMID=170
WIN_SNAP="snap_bkp_${WIN_VMID}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "[$(date "+%F %T")] ERROR: $ENV_FILE not found" | tee -a "$LOG_FILE"
  exit 1
fi

set -a
# shellcheck source=/dev/null
source "$ENV_FILE"
set +a
export RESTIC_REPOSITORY="b2:${B2_BUCKET_NAME}"

log() {
  echo "[$(date "+%F %T")] $*" | tee -a "$LOG_FILE"
}

notify() {
  local msg="$1"
  if [[ -n "${TELEGRAM_BOT_TOKEN:-}" && -n "${TELEGRAM_CHAT_ID:-}" ]]; then
    qm guest exec 120 -- curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
      -d "chat_id=${TELEGRAM_CHAT_ID}" \
      --data-urlencode "text=🖥️ PVE Backup (B2): ${msg}" >/dev/null 2>&1 || true
  fi
}

cleanup() {
  set +e
  for entry in "${CONTOURS[@]}"; do
    local vmid="${entry%%:*}"
    local name="${entry##*:}"
    local mnt="${SNAP_MNT_BASE}/${name}"
    local snap="snap_bkp_${vmid}"
    qm guest cmd "$vmid" fsfreeze-thaw >/dev/null 2>&1 || true
    if mountpoint -q "$mnt" 2>/dev/null; then
      umount -l "$mnt" >/dev/null 2>&1 || true
    fi
    kpartx -d "/dev/pve/${snap}" >/dev/null 2>&1 || true
    if lvs "/dev/pve/${snap}" >/dev/null 2>&1; then
      lvremove -f "/dev/pve/${snap}" >/dev/null 2>&1 || true
    fi
  done
  if lvs "/dev/pve/${WIN_SNAP}" >/dev/null 2>&1; then
    lvremove -f "/dev/pve/${WIN_SNAP}" >/dev/null 2>&1 || true
  fi
  rm -rf "$HOST_CFG_DIR"
}
trap cleanup EXIT

on_error() {
  local code=$? line="$1"
  log "ABORTED at line $line (exit $code)"
  notify "❌ FAILED at line $line (exit $code) — check $LOG_FILE on gigglin-pve"
}
trap 'on_error $LINENO' ERR

if [[ -f "$LOG_FILE" ]] && [[ $(wc -l < "$LOG_FILE") -gt 5000 ]]; then
  tail -5000 "$LOG_FILE" > "${LOG_FILE}.tmp" && mv "${LOG_FILE}.tmp" "$LOG_FILE"
fi

BACKUP_START=$(date +%s)
WARNINGS=0
log "=========================================="
log "Starting centralized PVE -> Backblaze B2 backup"
log "=========================================="

# --- Step 1: Pre-snapshot DB dumps inside each contour VM via QGA ---
log "Step 1: Running consistent DB dumps inside contour VMs via QGA..."
read -r -d '' DUMP_SNIPPET <<'EOS' || true
set -e
OUT=/var/backups/contour-db-dumps
rm -rf "$OUT" && mkdir -p "$OUT" && chmod 700 "$OUT"
for c in $(docker ps --format '{{.Names}}' 2>/dev/null || true); do
  case "$c" in
    nginx-proxy-manager-db|nextcloud-db)
      docker exec "$c" sh -c 'exec mariadb-dump --all-databases -uroot -p"${MYSQL_ROOT_PASSWORD:-${MARIADB_ROOT_PASSWORD}}" --single-transaction --quick' > "$OUT/${c}.sql" 2>/dev/null \
      || docker exec "$c" sh -c 'exec mysqldump --all-databases -uroot -p"${MYSQL_ROOT_PASSWORD}" --single-transaction --quick' > "$OUT/${c}.sql"
      ;;
    testcase-db|manager-helper-db|hrbot_prod_db|hrbot_dev_db|dmaic-studio-db-1|dmaic-old-db|fluxer-postgres-1|guacamole-postgres)
      docker exec "$c" sh -c 'PGPASSWORD="${POSTGRES_PASSWORD}" exec pg_dumpall -U "${POSTGRES_USER:-postgres}"' > "$OUT/${c}.sql"
      ;;
  esac
done
EOS

for entry in "${CONTOURS[@]}"; do
  vmid="${entry%%:*}"
  name="${entry##*:}"
  res=$(qm guest exec "$vmid" --timeout 180 -- bash -c "$DUMP_SNIPPET" 2>&1 || true)
  if echo "$res" | grep -q '"exitcode" *: *0'; then
    log "  OK: DB dumps prepared on VM $vmid ($name)"
  else
    log "  WARNING: QGA DB dump non-zero on VM $vmid ($name): $res"
    WARNINGS=$((WARNINGS + 1))
  fi
done

# --- Step 2: Export Proxmox & OpenWrt router configs ---
log "Step 2: Exporting Proxmox & OpenWrt router configs..."
rm -rf "$HOST_CFG_DIR"
mkdir -p "$HOST_CFG_DIR/pve" "$HOST_CFG_DIR/router"
chmod 700 "$HOST_CFG_DIR"
cp -a /etc/pve/. "$HOST_CFG_DIR/pve/etc-pve/"
cp -a /etc/network/interfaces "$HOST_CFG_DIR/pve/"
cp -a /etc/lvm/lvm.conf "$HOST_CFG_DIR/pve/"
cp -a /etc/modprobe.d /etc/modules /etc/kernel "$HOST_CFG_DIR/pve/" 2>/dev/null || true

if ssh -o BatchMode=yes -o ConnectTimeout=5 root@192.168.1.13 \
  "tar -C / -czf - etc/config etc/sing-box etc/nftables.d etc/hotplug.d/iface/95-webrtc-dnat etc/rc.local" \
  > "$HOST_CFG_DIR/router/openwrt-configs.tar.gz"; then
  log "  OK: OpenWrt router configs exported"
else
  log "  WARNING: Could not export OpenWrt router configs"
  WARNINGS=$((WARNINGS + 1))
fi

# --- Step 3: Take fsfreeze + RO LVM-thin snapshots and mount read-only ---
log "Step 3: Creating and mounting read-only LVM-thin snapshots..."
mkdir -p "$SNAP_MNT_BASE"
BACKUP_PATHS=("$HOST_CFG_DIR")

for entry in "${CONTOURS[@]}"; do
  vmid="${entry%%:*}"
  name="${entry##*:}"
  snap="snap_bkp_${vmid}"
  mnt="${SNAP_MNT_BASE}/${name}"
  mkdir -p "$mnt"

  qm guest cmd "$vmid" fsfreeze-freeze >/dev/null 2>&1 || true
  lvcreate -s -kn -pr "pve/vm-${vmid}-disk-0" -n "$snap" >/dev/null
  qm guest cmd "$vmid" fsfreeze-thaw >/dev/null 2>&1 || true

  kpartx -ar "/dev/pve/${snap}"
  mount -o ro,norecovery "/dev/mapper/pve-${snap}p1" "$mnt"
  log "  Mounted RO snapshot for VM $vmid ($name) at $mnt"

  for sub in home/gigglin var/lib/docker/volumes var/backups/contour-db-dumps etc; do
    [[ -e "$mnt/$sub" ]] && BACKUP_PATHS+=("$mnt/$sub")
  done
done

if [[ "${DRY_RUN_MOUNT_TEST:-0}" == "1" ]]; then
  log "DRY_RUN_MOUNT_TEST=1: checking dumped SQL files & B2 access..."
  for entry in "${CONTOURS[@]}"; do
    name="${entry##*:}"
    ls -lh "${SNAP_MNT_BASE}/${name}/var/backups/contour-db-dumps/" 2>/dev/null || true
  done
  restic snapshots --latest 2 | tee -a "$LOG_FILE"
  exit 0
fi

# --- Step 4: Single deduplicated Restic backup to Backblaze B2 ---
log "Step 4: Running restic backup (${#BACKUP_PATHS[@]} paths)..."
restic backup \
  --host gigglin-pve \
  --group-by host,tags \
  --tag contours \
  --tag daily \
  "${BACKUP_PATHS[@]}" \
  --exclude="*/.cache" \
  --exclude="*/.local/share/Trash" \
  --exclude="*/node_modules" \
  --exclude="*/__pycache__" \
  --exclude="*/.git/objects/pack" \
  --exclude="*.tmp" \
  --exclude="*.log.gz" \
  --verbose=1 \
  2>&1 | tee -a "$LOG_FILE"

# --- Step 4b: Raw disk image of the Windows VM (separate snapshot) ---
# Restic chunks the image content-defined, so only changed regions upload;
# unallocated thin blocks read as zeros and compress to almost nothing.
log "Step 4b: Backing up raw disk image of VM ${WIN_VMID} (corp-win10)..."
if lvcreate -s -kn -pr "pve/vm-${WIN_VMID}-disk-0" -n "$WIN_SNAP" >/dev/null \
  && restic backup \
    --host gigglin-pve \
    --tag vm170 \
    --tag daily \
    --stdin-filename "vm-${WIN_VMID}-disk-0.raw" \
    --stdin-from-command -- cat "/dev/pve/${WIN_SNAP}" \
    2>&1 | tee -a "$LOG_FILE"; then
  log "  OK: VM ${WIN_VMID} disk image uploaded"
else
  log "  WARNING: VM ${WIN_VMID} disk image backup failed"
  WARNINGS=$((WARNINGS + 1))
fi
lvremove -f "/dev/pve/${WIN_SNAP}" >/dev/null 2>&1 || true

# --- Step 5: Retention & prune (strictly scoped to --host gigglin-pve) ---
# Group by tags so the contours and vm170 snapshots keep their own history.
log "Step 5: Applying retention policy (--host gigglin-pve)..."
if ! restic forget \
  --host gigglin-pve \
  --group-by host,tags \
  --keep-daily 14 \
  --keep-weekly 8 \
  --keep-monthly 6 \
  --prune \
  2>&1 | tee -a "$LOG_FILE"; then
  log "WARNING: restic forget/prune failed"
  WARNINGS=$((WARNINGS + 1))
fi

DURATION=$(( $(date +%s) - BACKUP_START ))
log "Completed in $((DURATION/60))m $((DURATION%60))s (${WARNINGS} warning(s))"
if [[ "$WARNINGS" -gt 0 ]]; then
  notify "⚠️ Contours backup finished in $((DURATION/60))m $((DURATION%60))s with ${WARNINGS} warning(s)"
else
  notify "✅ Contours backup (7 VMs + VM 170 image + PVE + Router) finished in $((DURATION/60))m $((DURATION%60))s"
fi
