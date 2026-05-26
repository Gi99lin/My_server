# Guacamole

HTML5 RDP/VNC gateway. Used to reach the Windows 10 VM (libvirt/KVM) running
on this host from a browser, without installing an RDP client on the laptop.

## Topology

```
Mac (browser)
   ↓  SSH tunnel  -L 8080:127.0.0.1:8080
homelab:8080 → guacamole (Tomcat)
                  ↓
               guacd (1.5.5) ── RDP ──→ 192.168.122.x:3389 (Win10 VM)
                  ↓
               postgres:15 (connection metadata, users)
```

Guacamole listens only on `127.0.0.1:8080` by design — exposure happens via
SSH tunnel or, later, via Nginx Proxy Manager on the `proxy_network`.

## Install

```bash
cd ~/Projects/My_server/guacamole   # or wherever the project lives on the host
./install.sh
```

On first run the script:
1. creates `.env` with a random `POSTGRES_PASSWORD`,
2. generates `init/initdb.sql` from the Guacamole image (DB schema),
3. starts the three containers,
4. opens iptables `FORWARD` between Guacamole's Docker subnet (`172.31.0.0/16`)
   and libvirt's VM subnet (`192.168.122.0/24`), then installs
   `iptables-persistent` so the rules survive reboot.

Re-running is safe: it skips already-completed steps and does not wipe `pgdata/`.

### Why the FORWARD rules?

Guacamole's `guacd` container connects to the Win10 VM at `192.168.122.179:3389`.
Docker and libvirt live on separate bridges; the default `FORWARD` chain does
not bridge them and `guacd` gets `Connection refused`. The two ACCEPT rules
allow that specific subnet-to-subnet path (not the whole world).

The Docker subnet is pinned to `172.31.0.0/16` in `docker-compose.yml` so the
rules stay valid even after `docker compose down/up`.

## First-time access

From the laptop:

```bash
ssh -L 8080:127.0.0.1:8080 <user>@homelab
```

Open <http://localhost:8080/guacamole>.

Default credentials: `guacadmin / guacadmin` — **change immediately** under
top-right menu → Settings → Preferences.

## Adding a connection (Win10 VM)

Settings → Connections → New Connection:

- Protocol: `RDP`
- Hostname: `192.168.122.X` (from `sudo virsh domifaddr win10` on the host)
- Port: `3389`
- Username / Password: Windows local account
- Ignore server certificate: ✓
- Security mode: `Any` (or `NLA` if the VM enforces it)

## Backup

The `backup/` stack at the repo root snapshots `pgdata/`. The DB is small
(connection definitions + users); credentials stored there are encrypted at
rest by Guacamole.

To restore on a fresh host: copy `pgdata/` back, copy `.env` (must match the
password the encrypted credentials were stored with), `./install.sh`.

## Exposing on a real domain (later)

To put Guacamole behind NPM with HTTPS:

1. Attach the `guacamole` service to the top-level `proxy_network`
   (add `networks: [proxy_network]` and a top-level `networks:` block with
   `proxy_network: { external: true }`).
2. Remove the `127.0.0.1:8080:8080` port mapping (NPM reaches it via the
   shared network).
3. In NPM, add a proxy host pointing at `guacamole-web:8080`, enable
   WebSocket support, attach an LE cert.
4. **Enable TOTP** in Guacamole before exposing publicly:
   add `TOTP_ENABLED: "true"` env to the `guacamole` service.
