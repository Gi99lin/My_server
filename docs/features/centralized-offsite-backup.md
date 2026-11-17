---
feature: centralized-offsite-backup
title: Centralized off-site HomeLab backup
status: approved
source: user request 2026-11-03 to repair the failed nightly backup, rerun it, and sync the successful server change to the repository
entry_points: root cron on gigglin-pve, /root/backup/pve-restic-backup.sh
related: []
code_paths: backup/pve-restic-backup.sh
updated: 2026-11-13
---

# Centralized off-site HomeLab backup

## Purpose

The owner receives a recoverable off-site copy of the Linux service contours and host/router configuration. Scheduled and manual recovery runs must work without an interactive shell's environment.

## Actors and permissions

- The root account on `gigglin-pve` runs the backup with access to QEMU guest agents, LVM snapshots, and server-side Backblaze credentials.
- Credentials remain on the server and are never copied into the repository.

## Entry points

- Root cron runs `/root/backup/pve-restic-backup.sh` at `04:30` in the Proxmox host's timezone. At the time of this request the host uses UTC+5, so this is `02:30` Moscow time.
- After repairing a failed scheduled job, the operator can invoke the same script manually.

## Main flow

1. The job starts with a minimal cron environment, including an inherited `PATH=/usr/bin:/bin`, and makes the required administrative tools available.
2. It prepares database dumps in the seven Linux service VMs: `111`, `120`, `130`, `140`, `150`, `160`, and `171`.
3. It exports Proxmox and OpenWrt configuration and mounts read-only snapshots of the seven service VMs.
4. It uploads the selected service data, database dumps, and configuration to Backblaze B2 under Restic host `gigglin-pve`.
5. It takes a read-only snapshot of the Windows corporate VM `170` disk and uploads the whole raw disk image as a separate snapshot tagged `vm170`, so the VM can be restored in full.
6. It applies retention for this host, reports completion and the warning count in `/var/log/pve-restic-backup.log`, and releases the temporary snapshots and mounts.
7. The operator verifies that new `gigglin-pve` snapshots (`contours` and `vm170`) exist in B2. After a successful repair, the repository script must match the deployed server script.

## Validation and business rules

- `qm`, `lvcreate`, `lvremove`, `lvs`, `kpartx`, and `restic` must resolve when the job starts from the minimal cron environment.
- Retention keeps 14 daily, 8 weekly, and 6 monthly snapshots for `gigglin-pve`, counted separately for the `contours` and `vm170` snapshots; snapshots belonging to the separate `homelab` backup are outside this retention scope.
- The repair does not change the existing schedule or the independent Nextcloud HDD backup.
- Restic in Backblaze B2 is the only backup tier. There is no local full-VM `vzdump` job (retired 2026-11-13), and the Windows VM `170` is covered as a raw disk image.
- The B2 repository holds only post-migration snapshots; Ubuntu-era `homelab` snapshots older than 2026-11-03 were forgotten and pruned on 2026-11-13.
- This infrastructure feature has no browser UI. Regression cases are an operator checklist, not browser automation.

## Errors and edge cases

- A fatal failure produces an `ABORTED at line ... (exit ...)` log entry and must not be described as a successful backup.
- A run with database-dump, router-export, or retention warnings reports a nonzero warning count for operator review.
- VM `170` has no guest agent, so its image is crash-consistent: restoring it is like booting after a power loss.
- If the VM `170` image upload fails, the run counts a warning and still keeps the Linux contour snapshot; it is not reported as fully successful.
- A successful mount-only dry run is not proof of an uploaded off-site backup; a new B2 snapshot is required.

## Data

- The `contours` snapshot contains the selected paths from all seven Linux contours plus exported host/router configuration.
- The `vm170` snapshot contains one file, `vm-170-disk-0.raw`, the full 120 GB virtual disk; its VM config is in the `contours` snapshot under `/etc/pve`. To restore: create the VM from that config, then `restic dump <snapshot> /vm-170-disk-0.raw > /dev/pve/vm-170-disk-0`.
- Root credentials and `.env` values are server-side inputs. Verification output and repository changes must not expose them.
