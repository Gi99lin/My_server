# Corporate Linux Desktop Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Deliver a lower-memory Linux corporate desktop through the existing Guacamole gateway.

**Architecture:** Create an independent Ubuntu 22.04 VM in VLAN 70, with a persistent XFCE/X11 desktop. Install the supplied ZTN client and a vendor Horizon client. Keep Windows as rollback until corporate login and real use are verified.

**Tech Stack:** Proxmox, Ubuntu cloud image/cloud-init, XFCE, TigerVNC, Guacamole, Continent ZTN, Horizon.

**Spec:** `docs/superpowers/specs/2026-11-16-corp-linux-desktop-design.md`

## Global Constraints
- Initially 2 vCPU, 2 GiB RAM and 24 GiB disk; increase installation RAM only if necessary.
- VLAN 70, no public desktop port and no extra inter-contour access.
- No credentials, supplied profiles, or private keys in the repository or command logs.
- Preserve Windows and its disk, Guacamole authentication/TOTP, and `corp-socks` until cutover passes.
- Default CRL/integrity checks stay enabled. Corporate credentials and OTP remain owner-entered.
- Keep the Linux replacement in existing Restic coverage before production cutover.

## Review Focus
- ZTN's pre-login service must not prevent persistent graphical session startup after reboot.
- VPN routes and firewall changes must not cut off gateway SSH/VNC.
- Nested Horizon display and clipboard must work through Guacamole.
- Disconnecting a browser must preserve VPN/Horizon and the desktop session.
- Windows fallback and Mac SOCKS must remain functional until verified cutover.

## Task 1: Pilot VM and desktop
**Files:** Create `guacamole/corp-linux/README.md` and deployment configuration as required.
- [x] Verify a free VM ID and IP, storage, and headroom; record current Windows configuration outside the repository.
- [x] Download an official Ubuntu 22.04 cloud image and verify its checksum.
- [x] Create VM with an ext4 root disk, SSH keys, guest agent, and static corporate address.
- [x] Install XFCE and persistent VNC; verify SSH, guest agent, desktop startup, listeners and memory.

## Task 2: Corporate clients and Guacamole
**Files:** Update `guacamole/corp-linux/README.md`; preserve sensitive installation inputs outside git.
- [x] Transfer the supplied ZTN package/profile privately, install dependencies and ZTN without the helper's CRL override.
- [x] Obtain and install the vendor Horizon Linux package; verify missing libraries and executable startup.
- [x] Back up Guacamole metadata privately and add a Linux connection with the existing authorized user's permissions.
- [x] Verify the VNC handshake and rendered desktop; reboot and verify the same desktop returns.
- [ ] Prepare interactive registration/profile import and owner login/OTP, then test corporate DNS, Horizon use and reconnect if authentication is available.

## Task 3: Operational checks and cutover
**Files:** Update `README.md`, `AGENTS.md`, `guacamole/README.md`, `backup/pve-restic-backup.sh`, `docs/features/corp-linux-desktop.md` as warranted by the actual result.
- [x] Verify isolation and that existing Windows/gateway connections remain unchanged.
- [x] Add the Linux disk to existing Restic coverage and validate script syntax and guest freeze/thaw readiness.
- [ ] After real corporate tests pass, move SOCKS targeting, stop Windows, disable its automatic boot, and measure memory savings.
- [x] If owner authentication is pending, leave Windows and SOCKS intact and document exactly which checks remain.
- [x] Review the final changes, run relevant verification commands, sync feature cases, and report observed results without claiming pending corporate checks passed.

## Execution notes
The owner's approval authorizes inline execution of the reviewed design; no additional implementation-method selection is needed. This is infrastructure provisioning, so verification uses live checks and a manual checklist, not a new automated test suite. Preserve all unrelated existing checkout changes.

### Verification ledger
- VM 172 uses the verified official Ubuntu 22.04.5 cloud image; SSH/QGA and ext4 root confirmed.
- Guacd returned ready, two image instructions, 43 image blobs and a sync, with the SFTP filesystem channel. Dedicated restricted SFTP key authentication and directory listing succeeded.
- Horizon and ZTN registration GUIs visually inspected. Vendor C++ runtime selected by the Horizon wrapper; copied manifest ownership verified as root.
- Guest filesystem freeze/thaw passed; read-only LVM snapshot mounted ext4 with norecovery. Initial B2 backup succeeded: snapshot df106de9, 916 files, about 51 MB logical data. Temporary snapshot cleaned up.
- Ruling: disable optional console ctsx/LightDM and use multi-user target — the remote desktop is independent of the console, and no local Xorg console is required. ZTN VPN services and integrity checking stay active.
- Ruling: use a restricted dedicated SFTP key and a pinned ECDSA host key — cloud-init correctly disables SSH password authentication. Guacamole 1.5.5 parses one host-key line, not a multi-key value.
- Ruling: keep Windows running and SOCKS unchanged pending corporate login — owner registration/OTP is required to prove the replacement works. Net memory savings remain unclaimed until cutover.
- No commits or pushes were made; the checkout contains unrelated owner work.
- Clean reboot recovery verified in 40 seconds after removing prior orphaned login sessions. All four required services active; no failed system units. Post-reboot guacd returned ready/image/filesystem and completed a frame sync.
- Eight TCP isolation probes to the other six contours and two home LAN endpoints were blocked. Public Guacamole returned HTTP 200; existing Windows SSH hostname still responds.
- Independent reviewer found no important issues. The minor stale SFTP description in AGENTS.md was corrected.
- Feature sync submitted; the remote generator returned HTTP 500. Manual cases remain pending generation, not a passing automated result.
