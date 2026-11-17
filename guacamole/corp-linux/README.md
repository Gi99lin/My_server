# Corporate Linux desktop pilot

Ubuntu desktop for the owner to use Continent ZTN and Horizon through the existing
Guacamole gateway. Corporate authentication and a real Horizon session must pass
before Windows is stopped or the Mac SOCKS target changes.

Functional requirements and manual coverage are in
[`docs/features/INDEX.md`](../../docs/features/INDEX.md).

## Deployment

| Setting | Value |
| --- | --- |
| Proxmox VM | `172`, `corp-linux`, automatic boot enabled |
| OS | Ubuntu 22.04.5 amd64, ext4 root, XFCE/X11 |
| Resources | 2 vCPU, 2048 MiB RAM, 24 GiB disk on `local-lvm` |
| Network | `vmbr1`, VLAN 70, `10.10.70.21/24`, gateway `10.10.70.1` |
| Browser entry | `https://rdp.gigglin.tech` → `Corp Linux (pilot)` |
| Persistent desktop | TigerVNC display `:1`, TCP 5901, `corp-desktop.service` |
| Corporate clients | ZTN 4.5.0-1269, Horizon Classic 2609 / 8.20.0 build 39006907675 |
| File transfer | Guacamole SFTP, restricted dedicated SSH key, pinned ECDSA server host key |
| Other desktop tools | Firefox, Evince, XFCE terminal |

The VM firewall permits VNC only from `10.10.70.10`. SSH is allowed from the
gateway, router and HomeLab VPN subnet; password-based SSH remains disabled.
No router or public desktop-port changes were made.

SSH administration uses the owner's existing HomeLab SSH key:

```bash
ssh -J gigglin-corp-gw -i ~/.ssh/id_ed25519_gigglin gigglin@10.10.70.21
```

The Linux account password is stored in the owner's macOS Keychain as service
`HomeLab corp-linux desktop`, account `gigglin`. Use Keychain Access to view it
if the desktop asks for administrator authentication. Never copy it into git.

## First corporate login

1. Sign in to the existing Guacamole website and open `Corp Linux (pilot)`.
2. Open `ZTN-Registration` on the desktop. Complete online registration with the
   owner's corporate details, then the interactive entropy collection when asked.
3. Use `ZTN-guide.pdf` on the desktop for the company's profile import and account
   setup. The profile is `Documents/Corporate-setup/AVT.ts4`; its supplied password
   remains in the private guide, not in this repository.
4. Open `ZTN`, import the profile, select account/password authentication, and
   connect using the corporate account and one-time code.
5. Open `Horizon`, add the company's server, and verify a usable remote desktop.
6. Close and reopen the browser connection. Check that VPN and Horizon stayed
   connected, and test the needed clipboard/file-transfer behavior.

Profile preparation through the CLI did not finish before registration. No
successful profile import or VPN connection has been claimed. Corporate details
and OTP have not been requested in chat or stored by the migration tooling.

The supplied helper script disables CRL checks; it was not run. The guide also
describes disabling periodic OS integrity checks; that step was not applied.
ZTN's service reported a successful integrity check after reboot.

## Desktop service

Install the versioned configuration as follows, after creating the account and
configuring its VNC password privately:

```bash
sudo install -m 644 corp-desktop.service /etc/systemd/system/corp-desktop.service
install -d -m 700 ~/.vnc
install -m 755 Xtigervnc-session ~/.vnc/Xtigervnc-session
sudo loginctl enable-linger gigglin
sudo systemctl daemon-reload
sudo systemctl enable --now corp-desktop
```

The TigerVNC `-interface` argument must precede `-localhost no`: in Ubuntu's
wrapper, setting the interface clears the earlier localhost option.

The service owns its child processes directly, rather than starting a separate
PAM login session. This keeps shutdown bounded and prevents orphaned desktop
processes from delaying reboot. The user runtime directory is provided by the
lingering user manager. ZTN's optional console pre-greeter (`ctsx`) and LightDM
are disabled because this VM uses the independent VNC desktop; the ZTN VPN
services and integrity checks remain active. The default target is multi-user.

Launch interactive apps from the desktop. For administrative GUI checks over
SSH, launch them through `systemd-run --user --collect --setenv=DISPLAY=:1`
so they do not leave a lingering SSH login session.

## Client installation sources

The owner supplied the ZTN DEB and private guide/profile. The DEB is retained in
`Documents/Corporate-setup`, outside the repository.

Horizon came directly from the vendor:

```text
https://download3.omnissa.com/software/CART27FQ3_LIN_2609_TARBALL/Omnissa-Horizon-Client-Linux-2609-8.20.0-39006907675.tar.gz
SHA256 c1f6c9de0c2bc5cfe213bd0acbdb27ade8d2e145e14c51b5b20f9d05039391b9
```

The vendor's tarball deployment instructions were followed for the x64 Client
and mandatory PCoIP components. Both components support Horizon Blast. The
download/extracted archives are cached in `/var/cache/corp-linux-installers`.
Installed paths must be owned by root, including parent `/usr` directories;
extracting as an unprivileged account and using `cp -a` requires correcting
ownership on the copied manifest paths. Use the `/usr/bin/horizon-client`
wrapper, which selects the bundled C++ libraries when Ubuntu's are insufficient.

Reference: [vendor Linux deployment instructions](https://docs.omnissa.com/horizon-client-linux-rn-V2609/HorizonClientLinux-ReleaseNotes/).

## Backups and rollback

VM 172 is included in `backup/pve-restic-backup.sh`. Its home, `/etc` and
`/opt/securitycode` are backed up through read-only ext4 LVM snapshots to the
existing encrypted B2 repository. An initial separate snapshot tagged
`corp-linux-pilot,manual` succeeded on 2026-11-16 (`df106de9`, 916 files).
The regular job continues to use its existing `contours,daily` tag group.

Windows VM 170 was shut down at the owner's request on 2026-11-16, and
`onboot` was set to `0`. Its 120 GiB disk and both Guacamole connections remain
intact. No matching HA resource or scheduled startup was found. `corp-socks`
now targets Linux; the Windows SSH alias remains available for manual rollback. The pre-migration Windows config and previous backup script are in
`/root/corp-linux-migration` on Proxmox. A private Guacamole database dump from
before the connection was added is in
`/home/gigglin/guacamole/migration-backups` on `gigglin-corp-gw`.

Until corporate validation passes, the pilot adds 2 GiB to the existing running
VMs. After successful cutover, stopping the 4 GiB Windows VM would yield a net
2 GiB reduction. Do not delete the Windows disk as part of cutover.

## Verification

- Ubuntu image checksum, SSH and guest agent verified.
- XFCE and Horizon UI rendered; ZTN registration UI rendered.
- Guacd protocol handshake returned a ready connection and image data, including
  the SFTP filesystem channel. Restricted SFTP authentication/listing verified.
- Root ownership checked on installed Horizon manifest paths.
- ZTN integrity check and VM filesystem freeze/thaw succeeded.
- Initial encrypted B2 backup succeeded; daily backup script passed `bash -n`.
- Clean reboot restored SSH and the desktop in 40 seconds; no failed services.
- Eight TCP probes to the other contours and home LAN endpoints were blocked.
- Corporate authentication, Horizon remote interaction, VPN-route reachability,
  browser reconnect with active corporate sessions and final memory sizing remain
  owner-assisted checks. Windows shutdown and SOCKS cutover are intentionally pending.

Feature-case generation was submitted, but the generator returned HTTP 500.
The manual workflow above remains the verification checklist until generation
recovers; no browser regression suite was run for this infrastructure project.

## Owner-approved Windows shutdown (2026-11-16)

After successful Linux use and the memory comparison, the owner requested a
Windows shutdown without deletion and disabled automatic startup. VM 170 now
remains available for an explicit manual rollback:

```bash
ssh gigglin-pve 'qm start 170'
```

This manual start does not re-enable automatic boot. VM 172 remains running
with `onboot: 1`. Windows backup coverage and disk retention are unchanged.

## Mac corporate SOCKS cutover (2026-11-16)

At the owner's request, `~/.ssh/config` now defines `corp-linux` for Linux VM 172
and targets `corp-socks` at the same Linux address. Both use `ProxyJump
gigglin-corp-gw`, user `gigglin`, and the existing HomeLab SSH key. `corp-vm`
continues to identify the retained Windows VM. A private timestamped SSH config
backup remains in `~/.ssh/config.before-corp-linux-socks-*`.

Proxifier's Proxy 102 endpoint remains `127.0.0.1:1082`, so its corporate-domain
rules do not need to change. The SSH SOCKS server resolves corporate hostnames
on Linux through the connected ZTN VPN. The corporate `/8` route and more
specific local corporate-contour route are present. Do not change the relative
priority of HomeLab and corporate Proxifier rules.

The live tunnel was started as a session-only macOS launchd job so that it
survives the provisioning shell's exit. No persistent login LaunchAgent file
was installed, and this is not an automatic ZTN login mechanism.

```bash
# Inspect the current job/listener:
launchctl list com.ivan.corp-socks
lsof -nP -iTCP:1082 -sTCP:LISTEN

# Stop the job:
launchctl remove com.ivan.corp-socks

# Start the tunnel after it has been stopped (or after a Mac restart):
launchctl submit -l com.ivan.corp-socks -- /usr/bin/ssh -N -oBatchMode=yes -oConnectTimeout=10 corp-socks
```

Alternatively, after stopping/removing the job, the original `ssh -f -N
corp-socks` command can still be run from a normal user terminal. Do not start
both methods at once because they bind the same local port. ZTN must be
connected on Linux for corporate routes/DNS to work.

Validation: the Mac SOCKS request using remote hostname resolution reached the
corporate Horizon HTTPS endpoint and received HTTP 200. Certificate verification
in the first curl probe failed because its trust store lacks the issuing CA;
the HTTP reachability probe used `--insecure` for that request only. No system
certificate-validation setting or browser trust setting was changed. Direct
Linux TCP checks to the Horizon endpoint and 10.30.176.222:443 also succeeded.

Windows VM 170 has no running QEMU process; its configured 4 GiB is not reserved
while stopped. The host reported about 7.6–7.7 GiB available after shutdown.
Do not drop caches or reduce the retained Windows configuration to free memory.
