# Guacamole

HTML5 RDP/VNC gateway. Used to reach the Windows 10 VM (libvirt/KVM) running
on this host from a browser, without installing an RDP client on the laptop.

## Topology

```
Mac (browser)
   ↓  SSH tunnel  -L 8080:127.0.0.1:8080
homelab:8080 → guacamole (Tomcat)
                  ↓
               guacd (1.5.5) ── VNC (UltraVNC) ──→ 192.168.122.x:5900 (Win10 VM)
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

Guacamole's `guacd` container connects to the Win10 VM.
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

The primary connection uses **VNC (UltraVNC)** on port 5900, which natively prevents session-drop and VPN disconnect issues. **RDP** can still be configured as a fallback.

### Primary: VNC (UltraVNC)

Settings → Connections → New Connection:

- Protocol: `VNC`
- Hostname: `192.168.122.X` (from `sudo virsh domifaddr win10` on the host)
- Port: `5900`
- Password: VNC access password (configured in UltraVNC inside the VM)

### Fallback: RDP

Settings → Connections → New Connection:

- Protocol: `RDP`
- Hostname: `192.168.122.X`
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

## Public access at https://rdp.gigglin.tech

`guacamole-web` is attached to both `default` (to reach guacd/postgres) and
`proxy_network` (so NPM can reach it by container name). TOTP 2FA is enforced
via `TOTP_ENABLED=true` — each user enrolls on next login.

The `127.0.0.1:8080:8080` port mapping is kept as an SSH-tunnel fallback in
case TOTP/NPM/DNS break; it is loopback-only on the server, not publicly
exposed. With `WEBAPP_CONTEXT=ROOT` the fallback URL is
`http://localhost:8080/` (no `/guacamole/` suffix).

### Nginx Proxy Manager setup

1. NPM admin → Hosts → Proxy Hosts → **Add Proxy Host**.
2. **Details** tab:
   - Domain Names: `rdp.gigglin.tech`
   - Scheme: `http`
   - Forward Hostname / IP: `guacamole-web`
   - Forward Port: `8080`
   - Block Common Exploits: ✓
   - **Websockets Support: ✓** (Guacamole's RDP stream rides on WebSocket;
     without this the connection establishes but immediately drops)
3. **SSL** tab:
   - SSL Certificate: *Request a new SSL Certificate with Let's Encrypt*
   - Force SSL: ✓
   - HTTP/2 Support: ✓
4. Save and wait ~30 s for LE issuance.

### File transfer (shared drive)

The Win10 VM connection has RDP Drive Redirection enabled. A directory on
the host (`guacamole/shared/`) is bind-mounted into `guacd` at `/shared`
and surfaced inside Windows as a network drive (default letter `G:` or
whatever Windows assigns).

Two ways to move files:

1. **From browser**: open the Guacamole sidebar inside an RDP session
   (`Ctrl+Cmd+Shift` on Mac, `Ctrl+Alt+Shift` on PC) → drag files into the
   file panel. They appear in the shared drive immediately.
2. **From server shell**: `cp` / `rsync` / `scp` straight to
   `guacamole/shared/` on the host. Files appear in Windows next time it
   refreshes the drive listing.

The directory is persistent (lives on the host, not inside the container)
and untracked by git. Don't put secrets there if anyone else has shell
access to the host.

### TOTP enrollment

On the next login at `https://rdp.gigglin.tech` Guacamole shows a QR code.
Scan with any RFC 6238 TOTP app (Google Authenticator, Authy, Bitwarden,
1Password). Save the recovery key shown alongside — without it, loss of the
phone means manual recovery from the `guacamole_user_totp_key` table in
postgres.
