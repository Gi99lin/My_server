#!/usr/bin/env bash
# =============================================================
# sync-credentials.sh — populate backup/.env from per-service .env
# =============================================================
# Reads DB passwords from each service's own .env (../<service>/.env)
# and writes them into backup/.env so backup.sh can do mysqldump /
# pg_dump without manually maintaining duplicate secrets.
#
# Idempotent and safe by default:
#   - never overwrites an already-set value (use --force to do so)
#   - reads only; the source .env files are not modified
#   - does not print password values, only status per key
#
# Usage:
#   ./sync-credentials.sh            # fill empty/missing keys
#   ./sync-credentials.sh --force    # overwrite even if already set
#   ./sync-credentials.sh --dry-run  # show plan, don't write
# =============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
TARGET="$SCRIPT_DIR/.env"
EXAMPLE="$SCRIPT_DIR/.env.example"

FORCE=0
DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --force)   FORCE=1 ;;
    --dry-run) DRY_RUN=1 ;;
    -h|--help)
      sed -n '2,/^=*$/p' "$0" | sed 's/^# \?//'
      exit 0 ;;
    *)
      echo "Unknown arg: $arg (use --help)" >&2
      exit 1 ;;
  esac
done

# Bootstrap target from example if missing.
if [[ ! -f "$TARGET" ]]; then
  if [[ ! -f "$EXAMPLE" ]]; then
    echo "[!] Neither $TARGET nor $EXAMPLE exists" >&2
    exit 1
  fi
  echo "[+] $TARGET missing — copying from .env.example"
  if [[ $DRY_RUN -eq 0 ]]; then
    cp "$EXAMPLE" "$TARGET"
    chmod 600 "$TARGET"
  fi
fi

# Read a KEY=VALUE pair from a .env file. Strips surrounding quotes/whitespace.
# Prints empty string if file or key is missing.
read_env() {
  local file="$1" key="$2"
  [[ -f "$file" ]] || return 0
  awk -F= -v k="$key" '
    $1 == k {
      sub(/^[^=]*=/, "")
      gsub(/^[ \t"\x27]+|[ \t"\x27]+$/, "")
      print
      exit
    }' "$file"
}

# Set a variable in $TARGET. Echoes a one-word status:
#   updated | added | kept | skipped
set_env() {
  local key="$1" value="$2"
  if [[ -z "$value" ]]; then
    echo "skipped"
    return
  fi
  if grep -qE "^${key}=" "$TARGET" 2>/dev/null; then
    local current
    current="$(read_env "$TARGET" "$key")"
    if [[ -n "$current" && $FORCE -eq 0 ]]; then
      echo "kept"
      return
    fi
    if [[ $DRY_RUN -eq 0 ]]; then
      awk -v k="$key" -v v="$value" '
        $0 ~ "^" k "=" { print k "=" v; next }
        { print }
      ' "$TARGET" > "${TARGET}.tmp" && mv "${TARGET}.tmp" "$TARGET"
    fi
    echo "updated"
  else
    if [[ $DRY_RUN -eq 0 ]]; then
      printf '%s=%s\n' "$key" "$value" >> "$TARGET"
    fi
    echo "added"
  fi
}

# Resolve candidates from sibling service .env files.
MARZ_PASS="$(read_env "$PROJECT_DIR/marzneshin/.env" "DB_ROOT_PASSWORD")"
TC_PASS="$(read_env "$PROJECT_DIR/ai-testcase-generator/.env" "POSTGRES_PASSWORD")"
TC_USER="$(read_env "$PROJECT_DIR/ai-testcase-generator/.env" "POSTGRES_USER")"
[[ -z "$TC_USER" ]] && TC_USER="postgres"

# Mapping: env var in backup/.env  →  resolved source value.
# Last two are hardcoded in repo compose files (no .env), included
# so a clean install populates them too without manual editing.
declare -a KEYS=(
  "MARZNESHIN_DB_ROOT_PASSWORD"
  "TESTCASE_DB_PASSWORD"
  "TESTCASE_DB_USER"
  "NEXTCLOUD_DB_ROOT_PASSWORD"
  "NPM_DB_ROOT_PASSWORD"
)
declare -A VALUES=(
  ["MARZNESHIN_DB_ROOT_PASSWORD"]="$MARZ_PASS"
  ["TESTCASE_DB_PASSWORD"]="$TC_PASS"
  ["TESTCASE_DB_USER"]="$TC_USER"
  ["NEXTCLOUD_DB_ROOT_PASSWORD"]="mariadbroot"
  ["NPM_DB_ROOT_PASSWORD"]="npm_root_password"
)

echo "[+] Syncing credentials into $TARGET"
if [[ $FORCE -eq 1 ]]; then
  echo "    Mode: overwrite (--force)"
else
  echo "    Mode: fill empty / missing only"
fi
[[ $DRY_RUN -eq 1 ]] && echo "    Mode: --dry-run (no writes)"
echo

for key in "${KEYS[@]}"; do
  result="$(set_env "$key" "${VALUES[$key]}")"
  printf "  [%-7s] %s\n" "$result" "$key"
done

echo
if [[ $DRY_RUN -eq 1 ]]; then
  echo "[dry-run] Nothing written."
else
  echo "[✓] Done. Verify with: grep -v PASSWORD $TARGET | grep -v KEY"
  echo "    Test:               sudo $SCRIPT_DIR/backup.sh"
fi
