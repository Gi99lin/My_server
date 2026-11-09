# HomeLab on Proxmox

Proxmox runs the HomeLab workloads as isolated VLANs behind an OpenWrt router. The repository contains the routing templates, backup scripts, and deployment manifests reviewed against the running environment.

| VLAN | Contour | VM ID | Workloads | Internet egress |
| --- | --- | --- | --- | --- |
| 10 | Edge | 111 | Reverse proxy and public sites | Direct |
| 20 | Personal | 120 | Nextcloud, dashboards, monitoring, Telegram MCP | Proxy failover, with DoH through the proxy |
| 30 | Apps | 130 | Production applications and LiveKit | Direct with selected proxy routes |
| 40 | Dev | 140 | Staging and CI | Proxy failover |
| 50 | Agents | 150 | Agent runtimes and the Dify pilot | Fixed proxy |
| 60 | LLM | 160 | OmniRoute | Fixed proxy |
| 70 | Corporate | 170, 171 | Windows VM and remote desktop gateway | Direct |

[Proxmox configuration](infra/proxmox/) defines the bridges and backup job. [OpenWrt configuration](infra/openwrt-router/) defines the VLANs, forwarding policy, and sing-box routing. Fill in the WireGuard and proxy credentials from the deployment's private configuration before applying the templates.

## Backups

- The [Proxmox job](infra/proxmox/jobs.cfg) backs up all nine active VMs to local storage at 03:30 in the hypervisor's timezone.
- The [off-site job](backup/pve-restic-backup.sh) exports host and router configuration and backs up read-only snapshots of the seven Linux workload VMs to Backblaze B2 at 04:30 in the hypervisor's timezone.
- The [Nextcloud backup](backup/backup.sh) covers the dedicated data disk and database separately.

## Deployment manifests

The repository mirrors the verified manifests for [Telegram MCP](mcp-telegram/docker-compose.yml), [OmniRoute](omniroute/docker-compose.yml), and the [Dify pilot](dify/compose.pilot.yml). Other application Compose files serve as deployment templates. Per-VM overlays and application repositories hold their environment-specific settings.

[Contour checks](infra/openwrt-router/test-contours.sh) include deliberate proxy and router failover tests. Run the full suite during a maintenance window.
