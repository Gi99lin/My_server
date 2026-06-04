# Win10 VM — keep the session (and corp VPN) alive 24/7

Goal: log in once in the morning, bring up the corporate VPN + remote desktop,
and have it **stay up no matter what** — random disconnects, deliberately
closing the Guacamole tab, laptop sleep — until you explicitly shut the VM
down.

## Why the VPN dies after a disconnect

When the Guacamole/RDP view drops, the Windows session does **not** close — it
goes to state **`Disconnected`**. The desktop keeps running, but most corporate
VPN agents are bound to the *active interactive session*: a `Disconnected`
(or locked) session looks to them like "nobody's here", so they drop the
tunnel. Disabling **sleep** doesn't help because this isn't sleep — it's a
session-state change.

The fix: on every disconnect, immediately re-attach the session to the
**console** (`tscon … /dest:console`). The session flips back to `Active` and
stays unlocked, so the VPN agent never sees a disconnect or a lock. Works for
both accidental drops and intentionally closing the tab.

> [!NOTE]
> **VNC (UltraVNC) as Primary**: To avoid RDP session-state disconnects entirely, the setup has been migrated to use **VNC (UltraVNC)** on port 5900 as the primary connection method. Since VNC operates directly on the active console session, closing the browser tab does not disconnect the interactive desktop session, and the VPN tunnel stays alive. The RDP keepalive script below remains useful if you connect via RDP fallback.

## Install (inside the VM)

1. Copy this folder into the Win10 VM. Easiest path: drop it on the Guacamole
   shared drive (`guacamole/shared/` on the host → shows up as a drive in
   Windows), then copy it somewhere local.
2. Right-click **`install-keepalive.cmd`** → **Run as administrator**.

That registers a scheduled task (`RDP-KeepConsoleAttached`) plus the supporting
power/lock tweaks. Nothing to keep running manually.

## Verify it works

Open the VM in Guacamole, then **close the tab**. Wait ~5 s, reconnect, open a
terminal in the VM and run:

```cmd
query session
```

Your session should read **`Active`** on **`console`** — not `Disc`. The corp
VPN should still be connected.

## Security trade-off

The desktop is left **logged in and unlocked** on the console whenever you're
not viewing it. Anyone with console/host access to the VM sees an unlocked
desktop. For a personal homelab that's normally fine and is exactly the
"always on" behaviour you asked for — just be aware of it.

## Reduce how often it disconnects in the first place

You reach the VM through Nginx Proxy Manager at `https://rdp.gigglin.tech`.
nginx closes a WebSocket after **60 s** with no data by default, which causes
periodic RDP drops when the screen is static. Bump it:

NPM admin → Hosts → `rdp.gigglin.tech` → **Edit** → **Advanced** tab → paste:

```nginx
proxy_read_timeout   3600s;
proxy_send_timeout   3600s;
proxy_connect_timeout 3600s;
```

Save. (The "Websockets Support" toggle on the Details tab must stay on.)

## If it STILL drops — figure out which problem you have

Run these in the VM after a drop to tell session-state vs. real sleep vs.
network:

- **Is it actually sleeping?** Event Viewer → Windows Logs → System → filter
  source `Kernel-Power`. An **Event ID 42** = the machine entered sleep. If you
  see those, something is still allowed to sleep:
  ```cmd
  powercfg /a              :: which sleep states even exist
  powercfg /requests       :: what's keeping it awake / forcing sleep
  powercfg /lastwake
  ```
  On a VM the cleanest cure is to remove sleep at the host level — add to the
  libvirt domain XML (`sudo virsh edit win10`):
  ```xml
  <pm>
    <suspend-to-mem  enabled='no'/>
    <suspend-to-disk enabled='no'/>
  </pm>
  ```

- **Session-state (this folder fixes it):** Event Viewer →
  `Microsoft-Windows-TerminalServices-LocalSessionManager/Operational` →
  **Event 24** (disconnected) right before the VPN drops, and `query session`
  shows `Disc`.

- **Network-layer (shared root cause):** the VPN drops at the *same second* as
  the disconnect, and on the VM console the VPN is *also* down. Then the host
  uplink / `virbr0` NAT blipped and took both the incoming RDP and the outgoing
  VPN with it. The console trick won't save the tunnel here — look at host
  networking, and lean on the VPN client's own auto-reconnect.

## Remove

```cmd
schtasks /Delete /TN "RDP-KeepConsoleAttached" /F
```
