---
feature: corp-linux-desktop
title: Corporate Linux desktop through Guacamole
status: approved
source: user request and explicit design approval 2026-11-16; reduce corporate VM memory while retaining Guacamole, Horizon, and Continent ZTN
entry_points: https://rdp.gigglin.tech
related:
code_paths: guacamole, infra/proxmox, infra/openwrt-router
updated: 2026-11-16
---

# Corporate Linux desktop through Guacamole

## Purpose
Replace the Windows corporate desktop with a Linux desktop that uses less
allocated memory while retaining browser access and corporate connectivity.

## Actors and permissions
The existing authorized Guacamole user accesses the desktop through the existing
authentication and TOTP flow. The desktop remains inside the isolated corporate
contour; it must not gain access to HomeLab service VLANs or the home LAN.

## Main flow
1. The user opens `https://rdp.gigglin.tech` and signs in as usual.
2. The user selects `Corp Linux (pilot)` and sees a graphical desktop.
3. The user starts the installed Continent ZTN client and completes corporate
   authentication using a company-supported Linux configuration.
4. The user starts the installed Horizon client and opens the corporate desktop.
5. Closing and reopening the browser reconnects to the existing Linux desktop
   session without terminating the VPN or Horizon session.

## Proposed migration and resource budget
- Build a separate pilot VM in VLAN 70, keeping Windows VM 170 and its disk as
  a rollback path. Do not reuse its IP while Windows is running.
- Proposed platform: Ubuntu 22.04 x86_64 with a lightweight X11 desktop, subject
  to the supplied Continent Linux package's OS and kernel requirements.
- Start with 2 vCPU, 2 GiB RAM, and a 24 GiB disk. Increase memory temporarily
  if installation requires it; measure usage during a real corporate session
  before deciding the final allocation. The proposed steady allocation saves
  2 GiB versus the current Windows allocation, if it proves sufficient.
- Keep the public hostname and gateway. Prefer a persistent desktop session
  through VNC; use RDP only if reconnect and nested Horizon behavior pass.
- Shut Windows down after the Linux corporate workflow passes. Do not delete
  the Windows VM or disk as part of this migration.
- Preserve the Mac `corp-socks` workflow when cutting over, including SSH
  reachability through the corporate gateway and corporate DNS resolution.
- Owner-authorized proxy cutover (2026-11-16): `corp-socks` on the Mac must
  continue listening on `127.0.0.1:1082`, with SSH targeting the Linux corporate
  VM through `gigglin-corp-gw`. SOCKS hostname resolution must use the Linux
  VM's connected corporate VPN. Preserve the stopped Windows VM for rollback.
- Add the new Linux VM to the appropriate existing Restic backup coverage
  before treating it as the replacement; do not add local full-VM backup jobs.

## Alternatives
- Replace Windows in place: avoids a second VM, but loses the simple fallback
  and risks interrupting corporate access before Linux compatibility is proven.
- Keep Windows with a lower RAM allocation: a fallback if the corporate Linux
  client, certificate mechanism, or endpoint policy prevents the migration.

## Validation and edge cases
- Verify Guacamole login, desktop connection, browser reconnect, clipboard,
  and any currently required file transfer behavior.
- Verify the desktop is still reachable from Guacamole and SSH after VPN
  connection, including any full-tunnel routes or client firewall changes.
- Verify corporate VPN authentication, DNS, a Horizon desktop launch, normal
  interaction, and reconnect after browser closure; repeat after a Linux reboot.
- Verify `corp-socks` reaches the corporate destinations the owner uses.
- Verify corporate contour isolation remains intact. Router changes, if any,
  require the repository's contour regression command and expected pass count.
- If an installer, license, supported kernel, certificate import, or corporate
  device policy is unavailable, report the specific dependency and keep the
  Windows fallback usable. Never commit certificates, keys, or credentials.
- Confirm whether the installed Check Point VPN is also required before final
  cutover; its presence alone does not establish a requirement.

## Investigation evidence (2026-11-16)
Read-only checks found Windows VM 170 running with 4096 MiB, 4 vCPU, a 120 GiB
disk, and VLAN 70. Guacamole currently has RDP and VNC connections targeting
10.10.70.20. Windows has Horizon 8.6.0.29364, Continent ZTN 4.5.0.1089,
Security Code CSP 4.0.1224.0, and Check Point VPN installed. Linux installer
availability, certificate portability, and corporate policy remain unverified.

Vendor references:
- https://www.securitycode.net/products/skzi-kontinent-ap/ (Linux ZTN 4.4 lists Ubuntu 22.04.3)
- https://docs.omnissa.com/HorizonClientLinuxGuide-V2406/SystemRequirementsforLinuxClientSystems

These references establish a candidate platform, not compatibility of the
company's particular Linux ZTN build or authentication configuration.

## Supplied installation material (2026-11-16)
The owner supplied an external Downloads folder containing a Linux connection
guide, an encrypted connection profile, and amd64 DEB/RPM installers. Package
metadata identifies ZTN version 4.5.0-1269, with xsltproc and iptables as declared
dependencies. The guide illustrates an older build, so its steps require
validation against the supplied package.

The guide describes online registration, profile import, account/password
authentication, and a one-time code. It does not establish that an existing
Windows certificate container must be migrated. Registration details, account
passwords, and OTP entry remain interactive owner steps when needed.

The helper script disables CRL checks, and the guide describes disabling
scheduled OS integrity checks. These document instructions are not independent
authorization to weaken checks. Start with default checks enabled; investigate
and report a concrete failure before considering an exception. The package
post-install script also introduces a pre-login service and changes display
manager startup, which must be verified with the chosen persistent desktop.

Keep the supplied profile and installers outside the repository. Never copy
the guide's embedded profile password into project documents or logs.

## Pilot deployment status (2026-11-16)
VM 172 is deployed at 10.10.70.21 with 2 vCPU, 2048 MiB RAM and a 24 GiB disk.
Horizon and ZTN registration windows render. The existing Guacamole daemon has
returned the desktop image and SFTP filesystem channel for the new connection.
An initial encrypted B2 backup succeeded, and nightly coverage includes the VM.
Windows and the Mac SOCKS target remain unchanged. Corporate registration,
profile import, VPN authentication, a real Horizon session and reconnect under
VPN are pending owner interaction. See `guacamole/corp-linux/README.md` for
operational evidence and the private setup-file locations.
