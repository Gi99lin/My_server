# My HomeLab Server (`gigglin-pve`)

Infrastructure-as-Code, Docker Compose stacks, OpenWrt router configurations, and backup tooling for a segmented **Proxmox VE 9.2** HomeLab behind an **OpenWrt 25.12.6** security/routing appliance (`AmneziaWG` + `sing-box` + `nftables`).

> **For AI Agents**: Read [`AGENTS.md`](./AGENTS.md) for complete operational rules, inter-VLAN pinhole matrix, per-service deploy gotchas (`hrBot` dev/prod split, `omniroute`, `qa-lab`, VDI reverse tunnels), and Mac 3-tunnel client routing.

---

## 🏗 Architecture & Isolated VLAN Contours

All workloads are isolated into **7 L3-segmented VLAN contours** on internal trunk `vmbr1` behind `gigglin-router` (`VM 110`, WAN `192.168.1.13`, VPN `10.10.99.1/24`). Inter-VLAN forwarding defaults to `REJECT`, with explicit pinholes only where required.

| Contour | VMID | IP / VLAN | SSH Alias & VPN DNS | Internet Egress Policy | Deployed Services |
|---|---|---|---|---|---|
| **mgmt** | `pve`<br>`110` | `192.168.1.12`<br>`192.168.1.13` | `gigglin-pve` (`https://pve.home.arpa`)<br>`gigglin-router` (`http://router.home.arpa`) | Direct ISP | Proxmox VE 9.2 hypervisor (`ext4` + `LVM-thin`); OpenWrt router (`AmneziaWG`, `sing-box`, `nftables`, `dnsmasq`) |
| **1. edge** | `111` | `10.10.10.10/24` (`VLAN 10`) | `gigglin-edge` (`http://npm.home.arpa`) | Direct ISP | `nginx-proxy-manager` + MariaDB, portfolio `landing`, `life-dashboard-demo` (`demo.gigglin.tech`), `status-dashboard-demo` (`infra.gigglin.tech`) |
| **2. personal** | `120` | `10.10.20.10/24` (`VLAN 20`) | `gigglin-personal` (`personal.home.arpa`) | Direct, except Telegram & `*.open-meteo.com` → `proxy-failover` | `nextcloud` (`cloud.gigglin.tech`, 4 TB HDD `/srv/nextcloud-data`), `life-dashboard` (`dash.gigglin.tech`), `status-dashboard-api`, `mcp-telegram-cloud` (`mcp-tg.gigglin.tech`), `prometheus` + `grafana` (`grafana.gigglin.tech`) |
| **3. apps** | `130` | `10.10.30.10/24` (`VLAN 30`) | `gigglin-apps` (`apps.home.arpa`) | Direct, except Telegram → `proxy-failover` | `youtrack` (`youtrack.gigglin.tech`), `fluxer` (`fluxer.gigglin.tech` + LiveKit `7881/tcp`, `7882/udp`), `ai-testcase-generator` (`tms.gigglin.tech` + `testcase-tunnel`), `hrbot_prod`, `manager-helper`, `ai-presentation` |
| **4. dev** | `140` | `10.10.40.10/24` (`VLAN 40`) | `gigglin-dev` (`dev.home.arpa`) | **All traffic** → `proxy-failover` (`212.*` → `194.*`, fail-closed) | `dmaic-studio` (`dmaic.gigglin.tech`), `dmaic-old` (`dmaic-old.gigglin.tech`), `hrbot_dev`, `github-runner` (`tms-ci-dind`), `actions-runner-dmaic.service` |
| **5. agents** | `150` | `10.10.50.10/24` (`VLAN 50`) | `gigglin-agents` (`agents.home.arpa`) | **Strict single proxy** `proxy-kz` (`212.116.240.211`, **no rotation**, fail-closed) | `claude-sdk-host` (`:18090` + `tms-credentials` + `egress`/`netguard`), `hermes-tasks` |
| **6. llm** | `160` | `10.10.60.10/24` (`VLAN 60`) | `gigglin-llm` (`http://omni.home.arpa`) | **Strict single proxy** `proxy-kz` (`212.116.240.211`, **no rotation**, fail-closed) | `omniroute` (`:20131` `/v1/*` API gateway + VPN-only `:20130` Dashboard) |
| **7. corp** | `171`<br>`170` | `10.10.70.10/24`<br>`10.10.70.20/24` (`VLAN 70`) | `gigglin-corp-gw` (`corp-gw.home.arpa`)<br>`corp-vm` (`corp-win10.home.arpa`) | Direct ISP; zero access to internal VLANs | `corp-gw`: `guacamole` (`rdp.gigglin.tech`), `trueconf` (+ daily cron), VDI reverse-tunnel SSH endpoint (`18080–18090`).<br>`corp-win10`: native Windows 10 VM (`corp-socks`) |

---

## 🔒 Security & Routing Invariants

1. **Single LLM Gateway (`omniroute`)**:
   - Every internal service across `personal`, `apps`, `dev`, and `agents` calls LLMs exclusively through `http://10.10.60.10:20131/v1` (with zero internal proxies inside `omniroute`'s `storage.sqlite`, since `VLAN 60` is routed at L3 through `proxy-kz`).
   - `gigglin-router` rejects direct DNS/TLS connections to external LLM providers from `VLAN 20/30/40` (and non-Anthropic providers from `VLAN 50`, preserving Claude OAuth for `claude-sdk-host`).
   - External clients access `https://omniroute.gigglin.tech/v1/*` via NPM forwarding strictly to port `20131` (`/` returns `404`; Admin UI `:20130` is reachable only over AmneziaWG VPN at `http://omni.home.arpa`).
2. **Router-Enforced Fail-Closed Proxying & Public DNS**:
   - Upstream proxy credentials exist in a single place: `/etc/sing-box/config.json` on `gigglin-router` (template in [`infra/openwrt-router/sing-box.config.example.json`](./infra/openwrt-router/sing-box.config.example.json)).
   - `dnsmasq` on `gigglin-router` uses public upstream DNS (`8.8.8.8`, `1.1.1.1`) with `noresolv=1` (never querying the ISP router), while `sing-box` resolves proxied traffic remotely over `proxy-kz`.
   - Internal NAT hairpinning ([`infra/openwrt-router/20-hairpin-dnat.nft`](./infra/openwrt-router/20-hairpin-dnat.nft)) routes internal contour requests for `128.0.130.144:80/443` (`*.gigglin.tech`) directly to `10.10.10.10` (`edge` NPM) in `<1 ms`.
   - Automated verification suite: [`infra/openwrt-router/test-contours.sh`](./infra/openwrt-router/test-contours.sh) (`ssh gigglin-pve /root/test-contours.sh`, 46 checks).
3. **VPN-Only Admin Endpoints (Zero Port Numbers Required)**:
   - `https://pve.home.arpa` → Proxmox VE Web UI
   - `http://router.home.arpa` → OpenWrt LuCI
   - `http://npm.home.arpa` → Nginx Proxy Manager Admin UI (bound via isolated VIP `10.10.10.11`, unreachable from WAN)
   - `http://omni.home.arpa` → OmniRoute Admin Dashboard (`AUTH_COOKIE_SECURE=false` for HTTP VPN access)

---

## 💾 Two-Tier Backup Strategy

1. **Local Full-VM Snapshots (`03:30` daily on `gigglin-pve`)**:
   - Proxmox `vzdump` ([`infra/proxmox/jobs.cfg`](./infra/proxmox/jobs.cfg)) takes `zstd`-compressed QEMU snapshots of all 9 active VMs (`110..171`) into `/mnt/backups/dump` (`keep-daily=4, keep-weekly=2`).
2. **Centralized Off-Site Backblaze B2 Restic Backups**:
   - **`04:30` on `gigglin-pve` ([`backup/pve-restic-backup.sh`](./backup/pve-restic-backup.sh))**: Triggers consistent DB dumps (`Postgres`/`MariaDB`) inside all contour VMs over `qemu-guest-agent` (virtio-serial, zero network pinholes and zero B2 keys inside application VMs), exports Proxmox & OpenWrt configs, mounts brief `fsfreeze` read-only LVM-thin snapshots of all 7 Linux VMs, and pushes deduplicated backups to Backblaze B2 (`--host gigglin-pve`) with Telegram status alerts.
   - **`03:00` UTC on `VM 120` ([`backup/backup.sh`](./backup/backup.sh))**: Incrementally backs up the 4 TB raw HDD (`/srv/nextcloud-data`) + `nextcloud-db` dump to Backblaze B2 (`--host homelab`).

---

## 🤖 AI & Feature Documentation

- Agent operational guide & post-migration reference: [`AGENTS.md`](./AGENTS.md).
- Feature documentation and coverage: [`docs/features/INDEX.md`](./docs/features/INDEX.md).
- Personal Claude SDK service architecture: [`docs/superpowers/specs/2026-10-27-claude-sdk-host-design.md`](./docs/superpowers/specs/2026-10-27-claude-sdk-host-design.md) & [`claude-sdk-host/docker-compose.contours.yml`](./claude-sdk-host/docker-compose.contours.yml) (deployed in `agents`, `VM 150`).
- Auto-deploy via [`watchtower/`](./watchtower): runs per contour VM (`edge`, `apps`, `dev`), polling GHCR every 2 minutes for containers labeled `com.centurylinklabs.watchtower.enable=true`.

---

## 📂 Repository Layout

- `AGENTS.md` / `CLAUDE.md` — Comprehensive context, rules, and deploy reference for AI coding agents.
- `infra/proxmox/` — Proxmox VE network trunk (`vmbr0`/`vmbr1`) and `vzdump` backup schedule.
- `infra/openwrt-router/` — Sanitized OpenWrt `network`, `firewall`, `dhcp`, `20-hairpin-dnat.nft`, `95-webrtc-dnat`, `99-singbox-route`, `sing-box.config.example.json`, and `test-contours.sh`.
- `backup/` — Centralized Proxmox QGA+LVM Restic script (`pve-restic-backup.sh`) and Nextcloud HDD Restic script (`backup.sh`).
- `claude-sdk-host/` — Contour network override for `claude-sdk-host` (`VM 150`).
- `omniroute/` — Unified LLM API gateway (`VM 160`).
- `hermes/` — Mission Control `hermes-tasks` agent (`VM 150`).
- `ai-testcase-generator/`, `youtrack/`, `manager-helper/`, `ai-presentation/` — Application stacks (`VM 130`).
- `github-runner/` — Ephemeral DinD CI runner (`VM 140`).
- `nextcloud/`, `life-dashboard/`, `status-dashboard/`, `mcp-telegram/`, `monitoring/` — Personal & observability stacks (`VM 120`).
- `docker-compose.yml`, `life-dashboard-demo/`, `status-dashboard-demo/` — Edge NPM + portfolio landing + public demo stacks (`VM 111`).
- `guacamole/` — Remote desktop gateway (`VM 171`).
- `_archive/` — Retired pre-Proxmox single-node stacks (`matrix`, `k3s`, `openclaw`, `librechat`, `marzneshin`, `syncthing`).
