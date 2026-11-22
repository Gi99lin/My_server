# Project Context (`My_server` — HomeLab Infrastructure)

This repository is the authoritative source of truth for the user's **Proxmox VE 9.2** HomeLab (`gigglin-pve`) and its **7 isolated L3/VLAN contours** behind **OpenWrt 25.12.6** (`gigglin-router`). Global agent memories intentionally hold only a brief summary and point here for full operational context.

---

## 1. Hardware & Hypervisor (`gigglin-pve`)

- **Host**: `gigglin-pve` (`192.168.1.12/24`, gateway `192.168.1.1`, WAN public IP `128.0.130.144`)
- **CPU / RAM**: AMD Ryzen 5 7600X (6C / 12T), 32 GB DDR5 RAM (`29 GiB` allocated across 9 running VMs after the Dify pilot resize; legacy `VM 100` is an empty stopped shell; the pre-migration Ubuntu disk image was deleted on 2026-11-13)
- **Storage**:
  - `2 TB NVMe`: `local` (`100 GB` ext4 root; the `backups` thin LV at `/mnt/backups` is empty since local `vzdump` was retired on 2026-11-13) + `nvme-2tb` (`1.79 TB` LVM-thin pool for all VM root disks)
  - `4 TB WD Red Plus HDD` (`/dev/disk/by-id/ata-WDC_WD40EFZX-...`): passed through directly via `scsi1` to `VM 120` (`gigglin-personal`) and mounted at `/srv/nextcloud-data`
- **Bridges** ([`infra/proxmox/interfaces`](./infra/proxmox/interfaces)):
  - `vmbr0` (`192.168.1.12/24`, physical `enp6s0`): Home LAN & WAN transit bridge.
    - **Critical `iptables` invariant on `gigglin-pve`**: The port `443 -> 8006` redirect on `vmbr0` MUST stay destination-scoped (`iptables -t nat -A PREROUTING -i vmbr0 -d 192.168.1.12/32 -p tcp --dport 443 -j REDIRECT --to-ports 8006`). Never omit `-d 192.168.1.12/32`, or bridged HTTPS traffic to `gigglin-router` (`192.168.1.13:443`) will be hijacked by Proxmox's TLS cert.
  - `vmbr1` (`bridge-vlan-aware yes`, `bridge-vids 2-4094`): Internal isolated VLAN trunk connecting `gigglin-router` (`VM 110`) to contour VMs (`VLAN 10..70`).

---

## 2. The 7 Isolated Contours (`VLAN 10..70`) & Placement Principles

All contour VMs use SSH key `~/.ssh/id_ed25519_gigglin` (via `ProxyJump gigglin-router` in `~/.ssh/config`) except `corp-vm` (`~/.ssh/id_ed25519_corpvm` via `ProxyJump gigglin-corp-gw`).

| Contour | VMID | RAM / Disk | VLAN / IP | SSH Alias & VPN Hostname | Placement Principle & Egress Policy | Running Workloads |
|---|---|---|---|---|---|---|
| **mgmt** | `pve`<br>`110` | Host<br>`1 GB` / `4G` | `192.168.1.12`<br>`192.168.1.13` (`awg0` `10.10.99.1/24`) | `gigglin-pve` (`https://pve.home.arpa`)<br>`gigglin-router` (`http://router.home.arpa`) | Hypervisor & L3 security/routing appliance. Public DNS (`8.8.8.8`, `1.1.1.1`), `AmneziaWG` (`43821/udp`), `sing-box` (`sb0`), `nftables`. | Proxmox VE 9.2; OpenWrt 25.12.6 |
| **1. edge** | `111` | `1.5 GB` / `20G` | VLAN 10 — `10.10.10.10` (`.11` NPM Admin VIP) | `gigglin-edge` (`edge.home.arpa`, `http://npm.home.arpa`) | **Public ingress & static/demo frontends** (zero private data). Egress: **Direct ISP**. | `nginx-proxy-manager` + `npm-db`, `landing` (`gigglin.tech`), `life-dashboard-demo` (`demo.gigglin.tech`), `status-dashboard-demo` (`infra.gigglin.tech`), `watchtower` |
| **2. personal** | `120` | `5 GB` / `60G` + `4 TB HDD` | VLAN 20 — `10.10.20.10` | `gigglin-personal` (`personal.home.arpa`) | **Owner-only personal cloud, dashboards & monitoring**. Egress is **100% via `proxy-failover`** with DoH via the same proxy (fail-closed). | `nextcloud` (`cloud.gigglin.tech` + MariaDB + Redis; personal hub — Calendar, Tasks, Notes — operated by Claude via local MCP, see [`docs/features/personal-hub.md`](./docs/features/personal-hub.md)), `life-dashboard` (`dash.gigglin.tech`), `status-dashboard-api`, `mcp-telegram-cloud` (`mcp-tg.gigglin.tech`), `prometheus` + `grafana` (`grafana.gigglin.tech`) |
| **3. apps** | `130` | `8 GB` / `160G` | VLAN 30 — `10.10.30.10` | `gigglin-apps` (`apps.home.arpa`, `youtrack.home.arpa`) | **Multi-user & production applications**. Egress: **Direct ISP**, except Telegram → `proxy-failover` (fail-closed). | `youtrack` (`youtrack.gigglin.tech`), `fluxer` (`fluxer.gigglin.tech` + LiveKit `7881/tcp`, `7882/udp`), `ai-testcase-generator` (`tms.gigglin.tech`, `tms-files.gigglin.tech`, `testcase-tunnel`), `hrbot_prod` (DB `:5432`), `manager-helper`, `ai-presentation`, `watchtower` |
| **4. dev** | `140` | `3.5 GB` / `80G` | VLAN 40 — `10.10.40.10` | `gigglin-dev` (`dev.home.arpa`) | **Dev/staging stacks & CI runners**. Egress: **100% via `proxy-failover`** (`212.116.240.211` → `194.60.132.37`, fail-closed). | `dmaic-studio` (`dmaic.gigglin.tech`), `dmaic-old` (`dmaic-old.gigglin.tech`), `hrbot_dev` (DB `:5433`), `github-runner` (`tms-ci-dind`), `actions-runner-dmaic.service`, `watchtower` |
| **5. agents** | `150` | `6 GiB` / `80G` (4 vCPU) | VLAN 50 — `10.10.50.10` | `gigglin-agents` (`agents.home.arpa`) | **Autonomous AI agent runtimes**. Egress: **strict single proxy `proxy-kz`** (`212.116.240.211`, **never rotates to US**, fail-closed). | `claude-sdk-host` (`:18090` + `tms-credentials` + `egress`/`netguard`), `hermes-tasks`; Dify pilot deployment and evidence in [`dify/README.md`](./dify/README.md) |
| **6. llm** | `160` | `1.5 GB` / `25G` | VLAN 60 — `10.10.60.10` | `gigglin-llm` (`llm.home.arpa`, `http://omni.home.arpa`) | **Single LLM API gateway**. Egress: **strict single proxy `proxy-kz`** (`212.116.240.211`, **never rotates to US**, fail-closed). | `omniroute` (`:20131` `/v1/*` API gateway + VPN-only `:20130` Admin UI) |
| **7. corp** | `171`<br>`170` | `1 GB` / `20G`<br>`4 GB` / `90G` | VLAN 70 — `10.10.70.10`<br>VLAN 70 — `10.10.70.20` | `gigglin-corp-gw` (`corp-gw.home.arpa`)<br>`corp-vm` (`corp-win10.home.arpa`, retained Windows rollback) | **Isolated corporate contour** (zero access to `VLAN 10..60` or home LAN). Egress: **Direct ISP**. | `corp-gw`: `guacamole` (`rdp.gigglin.tech`), `trueconf` (daily cron), VDI reverse-tunnel SSH endpoint (`18080–18090`).<br>`corp-win10`: native Windows 10 corp-VPN VM |

---

## 3. Firewall, Proxy & Routing Rules (`gigglin-router`)

Config files live in [`infra/openwrt-router/`](./infra/openwrt-router). After any router change, run `/root/test-contours.sh` on `gigglin-pve` (versioned at [`infra/openwrt-router/test-contours.sh`](./infra/openwrt-router/test-contours.sh)) and confirm `TOTAL SUMMARY: PASS=46 FAIL=0`.

1. **Inter-VLAN Forwarding (`DEFAULT REJECT`)**:
   - `edge` (`10.10.10.10`) → `personal`, `apps`, `dev`, `corp-gw:8080` (`guacamole`), and `llm:20131` (`omniroute` API port ONLY; Admin UI `:20130` is blocked from `edge`).
   - `personal`, `apps`, `dev`, `agents` → `llm` (`10.10.60.10:20131` for `omniroute` `/v1/*`).
   - `apps` (`10.10.30.10`) → `agents` (`10.10.50.10:8080,18090` for `claude-sdk-host`).
   - `personal` (`10.10.20.10`) → `edge`, `apps`, `dev`, `agents`, `llm`, `corp-gw` on `:9100,:9101` (Prometheus `node-exporter` / `cadvisor`) and `apps:5432`, `dev:5433` (Grafana read-only Postgres for `hrBot`).
   - **Internal NAT Hairpinning** ([`infra/openwrt-router/20-hairpin-dnat.nft`](./infra/openwrt-router/20-hairpin-dnat.nft) + `Hairpin-*-to-edge-NPM` in [`firewall`](./infra/openwrt-router/firewall)): Any request from `edge`, `personal`, `apps`, `dev`, `agents`, or `vpn` (`awg0`) to `128.0.130.144:80/443` is DNAT'ed in `prerouting` to `10.10.10.10` (`edge` NPM), where policy rule `100: to 10.10.0.0/16 lookup main` routes it locally in `<1 ms` without traversing `sing-box`.
2. **Router-Level `sing-box` Egress (`sb0`) & LLM Bypass Prevention**:
   - Upstream SOCKS5 credentials exist **only** in `/etc/sing-box/config.json` on `gigglin-router` (template: [`sing-box.config.example.json`](./infra/openwrt-router/sing-box.config.example.json)).
   - Never configure `PROXY_URL`, `HTTP_PROXY` (to external VPS IPs), or internal proxy registries inside app containers (`hrBot`, `omniroute`, `hermes-tasks`).
   - `VLAN 20/30/40` are blocked at the router (`dnsmasq` + `sing-box` route reject) from calling external LLM domains (`openrouter.ai`, `api.openai.com`, `api.anthropic.com`, `generativelanguage.googleapis.com`, `openai.bothub.chat`, etc.) directly — they must use `http://10.10.60.10:20131/v1`. `VLAN 50` (`agents`) is allowed `api.anthropic.com` / `claude.ai` for `claude-sdk-host` OAuth, and blocked from all other direct LLM providers.
   - Public DNS (`8.8.8.8`, `1.1.1.1`) is configured on `gigglin-router` with `noresolv=1` and `peerdns=0` so the ISP router (`192.168.1.1`) is never queried.

---

## 4. Per-Service Operational Details & Gotchas

### `omniroute` (`gigglin-llm`, `10.10.60.10`)
- **Internal URL**: `http://10.10.60.10:20131/v1` (used by `hrBot`, `hermes-tasks`, `ai-testcase-generator`, `manager-helper`, `ai-presentation`, `life-dashboard`).
- **External URL**: `https://omniroute.gigglin.tech/v1/*` (NPM on `gigglin-edge` forwards `/v1/*` and `/api/v1/*` to `10.10.60.10:20131`; `/` returns `404` on `:20131`).
- **VPN Admin UI**: `http://omni.home.arpa` (`gigglin-edge` NPM forwards `omni.home.arpa:80` to `10.10.60.10:20130`). `.env` in `/home/gigglin/My_server/omniroute/.env` sets `AUTH_COOKIE_SECURE=false` so login cookies work over VPN HTTP while `X-Forwarded-Proto: https` still sets `Secure`.
- **Version pinned, 2026-11-22**: `diegosouzapw/omniroute:3.8.54` (was the floating `:latest`, 3.8.52). 3.8.54 adds `POST /v1/systemone` for decision models: a model id `openrouter/<vendor>/<model>` (e.g. `openrouter/typesafe/jev-1.14`) goes to OpenRouter's `/api/alpha/decisions` through the existing `openrouter` connection; `cloudflare-ai/jev` would need a `cloudflare-ai` connection and `SYSTEMONE_CLOUDFLARE_BACKEND_ENABLED` (not set). The upgrade applied 31 migrations, so rolling back needs the data archive `/home/gigglin/backups/omniroute_data-pre-3.8.54-2026-11-22.tgz` together with the image tagged `diegosouzapw/omniroute:3.8.52-rollback` (compose backup `docker-compose.yml.bak-2026-11-22`). Upgrade a pinned version deliberately: stop, archive `/var/lib/docker/volumes/omniroute_data/_data`, change the tag, start, then check a chat model on each provider in use.
- **No Internal Proxies**: `proxy_registry` and `proxy_assignments` in `/app/data/storage.sqlite` (and `key_value` `namespace='proxyConfig'`) are intentionally empty (`provider_connections.proxy_enabled = 0`) because `gigglin-router` already routes 100% of `VLAN 60` through `proxy-kz` (`212.116.240.211`, fail-closed).

### `hrBot` (`DEV` on `gigglin-dev`, `PROD` on `gigglin-apps`)
- **Split Architecture**:
  - `DEV` (`hrbot_dev_app`, `hrbot_dev_db` `:5433->5432`): `ssh gigglin-dev`, `/home/gigglin/My_server/hrBot`, `docker-compose.yml` (`--env-file .env.dev`).
  - `PROD` (`hrbot_prod_app`, `hrbot_prod_db` `:5432->5432`): `ssh gigglin-apps`, `/home/gigglin/My_server/hrBot`, `docker-compose.prod.yml` (`--env-file .env.prod`).
- **Deploy & Promote (`~/Projects/hrBot/`)**:
  - `./deploy.sh` builds `resumatch-bot:vX.Y.Z` on `gigglin-dev` and restarts `hrbot_dev`.
  - `./promote.sh` streams `resumatch-bot:vX.Y.Z` from `gigglin-dev` to `gigglin-apps` (`docker save | gzip | ssh gigglin-apps gunzip | docker load`), updates `.version.prod`, and restarts `hrbot_prod`.
- **Database `ai_configs`**: `AIService` reads `api_url` from PostgreSQL `ai_configs` first, overriding `.env`. Both `hrbot_dev_db` and `hrbot_prod_db` have `api_url = 'http://10.10.60.10:20131/v1'`. Never set `https://omniroute.gigglin.tech/v1` or `PROXY_URL` inside `hrBot`.

### `ai-testcase-generator` & Mac `qa-lab` Tunnel (`gigglin-apps`)
- Runs on `gigglin-apps` (`10.10.30.10`).
- On the Mac, `~/.config/qa-lab/config.env` sets `QA_LAB_TUNNEL_SSH_HOST=gigglin-apps` (`QA_LAB_TUNNEL_CONTAINER=testcase-backend`), managed by LaunchAgent `com.ivan.qa-lab-tunnel` (`http://127.0.0.1:18011`).

### Corporate Contour (`gigglin-corp-gw` `10.10.70.10` & `corp-vm` `10.10.70.20`)
- **VDI Reverse Tunnel**:
  - External TCP port `22` (`128.0.130.144:22` → `192.168.1.13:22` from `!192.168.1.0/24`) is DNAT'ed by `DNAT-WAN-SSH-VDI` on `gigglin-router` to `10.10.70.10:22` (`gigglin-corp-gw`).
  - `~/.ssh/authorized_keys` on `gigglin-corp-gw` contains the restricted `vdi-reverse-tunnel` key (`permitlisten` on `18080–18090`).
  - On the Mac, `sudo bash ~/corp-tunnel.sh` (canonical copy: `~/skills/runbooks/corp-tunnel/corp-tunnel.sh`) connects via `root@192.168.1.13` → `gigglin@10.10.70.10` so it works on both home Wi-Fi and AmneziaWG VPN (falling back to `gigglin@128.0.130.144` if outside without VPN).
- **Windows 10 Corporate VPN VM (`corp-win10`, `VM 170`, `10.10.70.20`)**:
  - Desktop access via `https://rdp.gigglin.tech` (`guacamole` on `corp-gw`).
  - The Mac `corp-socks` tunnel now targets Linux VM 172, not this retained Windows VM. It listens on `127.0.0.1:1082`; see the Linux pilot runbook.
  - **Windows OpenSSH note**: Win10 uses MSI `Win32-OpenSSH` in `C:\Program Files\OpenSSH`. If `sshd` service needs re-registration inside Windows PowerShell (Admin):
    ```powershell
    & "C:\Program Files\OpenSSH\install-sshd.ps1"
    Set-Service -Name sshd -StartupType Automatic
    Start-Service sshd
    New-NetFirewallRule -Name "ssh-from-corp-gw" -DisplayName "OpenSSH from corp-gw and VPN" -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22 -RemoteAddress 10.10.70.0/24,10.10.99.0/24
    ```

### Corporate Linux pilot (`VM 172`, `10.10.70.21`)
- Ubuntu 22.04.5, XFCE/X11, 2 vCPU / 2 GiB RAM / 24 GiB ext4 disk in VLAN 70.
- Existing Guacamole gateway has a `Corp Linux (pilot)` VNC connection to `10.10.70.21:5901`, with restricted-key SFTP and a pinned server host key.
- Continent ZTN 4.5.0-1269 and Horizon 2609 (8.20.0) are installed. Registration, corporate authentication, real Horizon use and VPN routing validation are pending.
- Windows VM 170 is stopped with `onboot: 0` at the owner's request (2026-11-16); its 120 GiB disk and Guacamole entries are retained. `corp-socks` now targets Linux VM 172 through `gigglin-corp-gw`, using user `gigglin` and the HomeLab SSH key.
- SSH: `ssh -J gigglin-corp-gw -i ~/.ssh/id_ed25519_gigglin gigglin@10.10.70.21`.
- Desktop service/configuration and operational checks: [`guacamole/corp-linux/README.md`](./guacamole/corp-linux/README.md). The Linux account password is in macOS Keychain under service `HomeLab corp-linux desktop`, account `gigglin`.
- Central Restic coverage includes VM 172 home, `/etc`, and `/opt/securitycode`; no local full-VM backup job was added.

### Mac 3-Tunnel Client Architecture (`Proxifier` + `awg-wireproxy`)
- **Tunnels**:
  1. `127.0.0.1:10808` (`Proxy 100`) — `Happ` (`xray`) for general geo-blocked sites AND `dash.gigglin.tech` (`104.21.44.30; 172.67.194.85`, which sits behind Cloudflare Proxy and would otherwise hit RKN's 19 KB TCP block over `Direct`).
  2. `127.0.0.1:1081` (`Proxy 101`) — `awg-wireproxy` LaunchAgent (`local.awg-wireproxy`, config `~/.config/wireproxy/awg-homelab.conf`) for `192.168.1.12; 192.168.1.13; 10.10.0.0/16; *.home.arpa`.
  3. `127.0.0.1:1082` (`Proxy 102`) — SSH `corp-socks` to Linux VM 172 (`10.10.70.21`, connected ZTN VPN) for corporate domains/subnets (`*.rshbank.ru; *.rshb.ru; *.sberbank.ru; 172.16.0.0/12; 10.0.0.0/8`), placed **below** HomeLab `10.10.0.0/16` (`Proxy 101`) and VDI local aliases `10.26.5.79; 10.30.176.222` (`Direct`).

---

## 5. Backups (Restic → Backblaze B2 only)

Local `vzdump` was retired on 2026-11-13 (it filled the 600 GB `backups` LV and failed). All backups are Restic snapshots in one B2 repository, as on the pre-Proxmox Ubuntu server. Never re-add a local full-VM job without asking the owner.

1. **Daily `04:30` host time (`gigglin-pve`, currently UTC+5: `02:30` MSK)**: `/root/backup/pve-restic-backup.sh` ([`backup/pve-restic-backup.sh`](./backup/pve-restic-backup.sh)) runs pre-backup DB dumps inside all contour VMs via `qm guest exec`, exports Proxmox & OpenWrt configs, mounts read-only LVM-thin snapshots of all 7 Linux VMs (`110..171`), backs them up to Backblaze B2 (`--host gigglin-pve`, tag `contours`), uploads the Windows `corp-win10` (`VM 170`) disk as one crash-consistent raw image (tag `vm170`, restore with `restic dump`), runs retention prune per tag group, and sends a Telegram notification. The script sets its own administrative `PATH` so root cron can resolve `qm`, LVM tools, and `kpartx`.
   - **B2 goes through the router, not direct ISP** (since 2026-11-22): the host's direct path to the account's cluster (`f003.backblazeb2.com`, `45.11.36.16`) is cut, which made restic hang at `open repository` on 2026-11-19/21. The script exports `HTTPS_PROXY=http://192.168.1.13:1081`, the sing-box inbound `pve-backup-http-in` on `gigglin-router`. That inbound accepts only `192.168.1.12` (firewall rule `PVE-to-backup-proxy`) and only `*.backblazeb2.com` / `*.backblaze.com` (uploads go to `pod-*.backblaze.com`), and sends them via `proxy-failover`. `test-contours.sh` restarts sing-box, so don't run it during a backup.
   - **Guards**: a `flock` on `/run/pve-restic-backup.lock` (a second run exits before touching snapshots), stale `snap_bkp_*` cleanup at start, `lvcreate` retried 3×, restic wrapped in `timeout` (3 h backup, 2 h prune) so a stall ends as a logged, notified failure, and stderr goes to `/var/log/pve-restic-backup.log`.
2. **Daily `03:00` UTC (`gigglin-personal`, `VM 120`)**: `/home/gigglin/My_server/backup/backup.sh` backs up `/srv/nextcloud-data` (4 TB HDD) + `nextcloud-db` dump to Backblaze B2 (`--host homelab`).
