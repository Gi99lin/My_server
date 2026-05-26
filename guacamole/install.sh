#!/usr/bin/env bash
# Install / bootstrap Guacamole stack.
# Idempotent: safe to re-run; will not wipe pgdata.

set -euo pipefail

cd "$(dirname "$0")"

# Subnets used by FORWARD rules so guacd (Docker bridge) can reach the
# libvirt VM network. Keep in sync with docker-compose.yml `networks:` block
# and with libvirt's default network (`virsh net-dumpxml default`).
readonly GUAC_SUBNET="172.31.0.0/16"
readonly LIBVIRT_SUBNET="192.168.122.0/24"

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

# 4. Open iptables FORWARD between guacd's bridge and libvirt's virbr0.
#    Without this, guacd gets "Connection refused" trying to reach the VM at
#    192.168.122.x — Docker and libvirt live on separate bridges and the
#    default FORWARD chain does not bridge them.
configure_firewall() {
  echo "[+] Configuring iptables FORWARD: ${GUAC_SUBNET} <-> ${LIBVIRT_SUBNET}"

  local rules=(
    "-s ${GUAC_SUBNET} -d ${LIBVIRT_SUBNET} -j ACCEPT"
    "-s ${LIBVIRT_SUBNET} -d ${GUAC_SUBNET} -j ACCEPT"
  )

  for rule in "${rules[@]}"; do
    # shellcheck disable=SC2086
    if sudo iptables -C FORWARD $rule 2>/dev/null; then
      echo "    already present: ${rule}"
    else
      # shellcheck disable=SC2086
      sudo iptables -I FORWARD $rule
      echo "    added:           ${rule}"
    fi
  done

  # Persist across reboot. iptables-persistent saves /etc/iptables/rules.v4
  # on package install and on `netfilter-persistent save`, then restores on boot.
  if ! dpkg -s iptables-persistent >/dev/null 2>&1; then
    echo "[+] Installing iptables-persistent (one-time)"
    # Preseed debconf so apt does not prompt to save current rules.
    echo iptables-persistent iptables-persistent/autosave_v4 boolean true \
      | sudo debconf-set-selections
    echo iptables-persistent iptables-persistent/autosave_v6 boolean true \
      | sudo debconf-set-selections
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y iptables-persistent
  fi
  sudo netfilter-persistent save >/dev/null
  echo "[✓] iptables rules saved to /etc/iptables/rules.v4"
}

configure_firewall

echo
echo "[✓] Done. Access via SSH tunnel from your laptop:"
echo "    ssh -L 8080:127.0.0.1:8080 <user>@<server>"
echo "    Then open http://localhost:8080/guacamole"
echo
echo "    Default login: guacadmin / guacadmin  (change immediately!)"
