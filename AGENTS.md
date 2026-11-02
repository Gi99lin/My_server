# Project Context (`My_server`)

## Infrastructure Topology (Proxmox VE 9.2 + 7 Isolated VLAN Contours)

The HomeLab runs on **Proxmox VE 9.2** (`gigglin-pve`, `192.168.1.12`) behind an **OpenWrt 25.12.6** router VM (`gigglin-router`, `VM 110`, WAN `192.168.1.13`, AmneziaWG `10.10.99.1/24`). Workloads are isolated across 7 VLAN contours on internal trunk `vmbr1`:

| Contour | SSH Alias | Internal DNS (`*.home.arpa`) | VLAN / IP | VMID | Egress Policy (enforced on `gigglin-router`) |
|---|---|---|---|---|---|
| **mgmt** | `gigglin-pve`<br>`gigglin-router` | `pve.home.arpa`<br>`router.home.arpa` | `192.168.1.12`<br>`192.168.1.13` | `pve`<br>`110` | Direct ISP |
| **1. edge** | `gigglin-edge` | `edge.home.arpa` (`npm.home.arpa`) | VLAN 10 — `10.10.10.10` (`.11` NPM UI VIP) | `111` | Direct ISP |
| **2. personal** | `gigglin-personal` | `personal.home.arpa` | VLAN 20 — `10.10.20.10` | `120` | Direct, **except** Telegram & `*.open-meteo.com` → `proxy-failover` (fail-closed) |
| **3. apps** | `gigglin-apps` | `apps.home.arpa` (`youtrack.home.arpa`) | VLAN 30 — `10.10.30.10` | `130` | Direct, **except** Telegram → `proxy-failover` (fail-closed) |
| **4. dev** | `gigglin-dev` | `dev.home.arpa` | VLAN 40 — `10.10.40.10` | `140` | **All traffic** → `proxy-failover` (`212.116.240.211` → `194.60.132.37`, fail-closed) |
| **5. agents** | `gigglin-agents` | `agents.home.arpa` | VLAN 50 — `10.10.50.10` | `150` | **Strict single proxy** `proxy-kz` (`212.116.240.211`, **no rotation**, fail-closed) |
| **6. llm** | `gigglin-llm` | `llm.home.arpa` (`omni.home.arpa`) | VLAN 60 — `10.10.60.10` | `160` | **Strict single proxy** `proxy-kz` (`212.116.240.211`, **no rotation**, fail-closed) |
| **7. corp** | `gigglin-corp-gw`<br>`corp-vm` | `corp-gw.home.arpa`<br>`corp-win10.home.arpa` | VLAN 70 — `10.10.70.10`<br>VLAN 70 — `10.10.70.20` | `171`<br>`170` | Direct ISP; complete L3 isolation from all internal VLANs |

*(Legacy single-node VM `100` / `gigglin-server` is powered off with `onboot=0` as cold rollback only — do not deploy to `gigglin-server`.)*

## Mandatory Rules for Agents

1. **Target the specific contour SSH alias** (`ssh gigglin-edge`, `ssh gigglin-personal`, `ssh gigglin-apps`, `ssh gigglin-dev`, `ssh gigglin-agents`, `ssh gigglin-llm`, `ssh gigglin-corp-gw`, `ssh gigglin-router`, `ssh gigglin-pve`) — multiple agents can operate on separate contour VMs independently.
2. **Single LLM Gateway**: All API-key LLM calls across all contours MUST go through `omniroute` at `http://10.10.60.10:20131/v1` (`gigglin-router` rejects direct LLM provider domains from `VLAN 20/30/40`, and non-Anthropic LLM domains from `VLAN 50`).
3. **Router-Level Proxy Only**: Never hardcode `PROXY_URL`, `TELEGRAM_PROXY`, `HTTP_PROXY` (with upstream VPS credentials), or Backblaze B2 secrets inside application containers or contour VMs. Upstream proxy credentials exist solely in `/etc/sing-box/config.json` on `gigglin-router`.
4. **Zero Secrets in Git**: Never commit private keys, `.env` files, tokens, passwords, or internal credentials to this repository.
