# Always-on access via VNC to the console (UltraVNC) — the real fix

**Why:** RDP always generates a "session disconnected" event when the view
drops, and the corp VPN is bound to that event, so it tears down the tunnel
the instant the tab closes — `tscon` can't win that race (confirmed: the
keepalive task fires with result 0 and the session goes back to Active, yet
the VPN still drops).

A VNC server inside Windows serves the **console session**, which is always
`Active`. A VNC viewer connecting/disconnecting is invisible to Windows — like
plugging/unplugging a monitor. **No session-disconnect event is ever raised, so
the VPN never sees an interruption and never drops.** Close the tab whenever you
like; the desktop and the VPN keep running until you shut the VM down.

```
Browser → NPM (rdp.gigglin.tech) → Guacamole → guacd ── VNC ──→ 192.168.122.179:5900 (Win10 console)
                                                                  corp VPN runs in this always-Active session
```

---

## 1. Install UltraVNC Server in the VM (as a service)

1. In the VM, download UltraVNC from <https://uvnc.com/downloads/ultravnc.html>.
2. Run the installer. Select **UltraVNC Server** (the viewer is optional).
3. Tick **"Register UltraVNC Server as a system service"** and
   **"Start or restart UltraVNC service"**. Service mode is what makes it serve
   the console session before/independent of any interactive login.

## 2. Configure it (this part matters)

Open **UltraVNC Server → Admin Properties** (right-click the tray icon →
*Admin Properties*, or Start menu → "UltraVNC Server (Service mode)"). Set:

- **Authentication → VNC Password:** set a real password (you'll paste it into
  Guacamole). Leave **"Require MS Logon"** *unchecked* for simplicity.
- **When Last Client Disconnects:** select **"Do Nothing"**. ← critical. The
  default may lock or log off the session when you close the tab, which would
  re-introduce exactly the drop we're killing.
- **Ports:** Main = **5900** (default).
- **Multi viewer connections:** "Keep existing connections" (so a stale tab
  doesn't kick your new one — optional).
- Apply / OK, then restart the service (tray → *Close / restart service*, or
  `net stop uvnc_service && net start uvnc_service` in an elevated cmd).

## 3. Open the firewall path

- **Windows Firewall:** the installer usually adds a rule for 5900. Confirm
  inbound TCP 5900 is allowed (Windows Defender Firewall → Inbound Rules →
  look for UltraVNC / winvnc). If missing:
  ```cmd
  netsh advfirewall firewall add rule name="UltraVNC 5900" dir=in action=allow protocol=TCP localport=5900
  ```
- **Host FORWARD rules (libvirt ↔ Docker):** the existing Guacamole rules are
  subnet-to-subnet (172.31.0.0/16 ↔ 192.168.122.0/24), so port 5900 should
  already be allowed — same path RDP uses. Verify on the host:
  ```bash
  sudo iptables -S FORWARD | grep 192.168.122
  ```
  If you see the two ACCEPT rules without a `--dport 3389` restriction, you're
  done. (If they *are* port-restricted, add 5900 the same way 3389 was added.)

## 4. Add the VNC connection in Guacamole

Guacamole admin → Settings → Connections → **New Connection**:

- **Protocol:** `VNC`
- **Hostname:** `192.168.122.179`  (confirm with `sudo virsh domifaddr win10`)
- **Port:** `5900`
- **Password:** the VNC password from step 2
- Color depth / other settings: defaults are fine.

Keep the old RDP connection around as an emergency backup, but use the VNC one
for daily work.

## 5. Daily workflow (what you asked for)

1. Morning: open the **VNC** connection in Guacamole. You see the console
   desktop (unlock if needed — it stays unlocked afterward, see note below).
2. Launch the corporate VPN **in this session**.
3. Work. Close the tab, refresh, let the laptop sleep, lose Wi-Fi — Windows
   never sees a session change, so the VPN stays up.
4. It keeps running until you deliberately shut the VM down or disconnect the
   VPN yourself.

## 6. Make sure nothing locks the session

The earlier `install-keepalive.cmd` already disabled screensaver, idle
auto-lock (`InactivityTimeoutSecs=0`) and all sleep — keep those. Combined with
UltraVNC's "When last client disconnects: Do Nothing", the console session
stays unlocked and Active indefinitely.

## 7. Clean up the now-redundant RDP keepalive (optional)

The `tscon` scheduled task only triggers on **RDP** disconnects, which you'll
stop using daily. It's harmless to leave as a backup, but if you want it gone:

```cmd
schtasks /Delete /TN "RDP-KeepConsoleAttached" /F
```

## 8. Still worth doing: raise the NPM idle timeout

Whether RDP or VNC, NPM/nginx closes an idle WebSocket after 60 s, which causes
needless reconnects. NPM admin → Hosts → `rdp.gigglin.tech` → Edit → **Advanced**:

```nginx
proxy_read_timeout    3600s;
proxy_send_timeout    3600s;
proxy_connect_timeout 3600s;
```

---

### Security note

The VNC password is weak crypto, but port 5900 is only reachable on the
internal guacd↔libvirt path — **never expose it publicly**. Public access stays
behind Guacamole + TOTP at `https://rdp.gigglin.tech`, exactly as today. The
console session is left logged-in and unlocked (the "always on" trade-off you
accepted earlier).
