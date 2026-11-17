# Corporate desktop memory comparison

## Linux baseline

Captured on 2026-11-16 at 13:50:11–13:50:31 Europe/Helsinki (11:50 UTC),
after the owner confirmed the corporate Horizon session works with H.264/HEVC
disabled. Windows was subsequently measured at 13:53:15–13:53:36 Europe/Helsinki
with an active Horizon session, after the owner confirmed login.

| Metric | Linux VM 172 | Windows VM 170, same active workload |
| --- | --- | --- |
| Configured memory | 2048 MiB | 4096 MiB |
| Guest-visible memory | 1963.6 MiB | 4095.4 MiB |
| Guest available memory, three samples | 945.5 / 945.3 / 944.6 MiB | 1828 / 1820 / 1825 MiB |
| Guest total minus available | 1018.1 / 1018.3 / 1019.0 MiB | 2267.4 / 2275.4 / 2270.4 MiB |
| Swap used | 0 MiB; no swap configured | Not measured |
| Proxmox host process footprint (`memhost`) | 1,678,962,688 bytes, about 1.56 GiB | 4,398,047,232 bytes, about 4.10 GiB |

The guest estimate is stable across the 20-second sample interval. The earlier
`free -m` snapshot showed 838 MiB in its `used` column and 953 MiB available;
that column uses a different cache accounting formula. Use total minus available
consistently for the cross-OS comparison. The Proxmox host process footprint
includes guest cache and VM overhead; it is not guest application memory alone.

Process groups measured using proportional set size (PSS, shared pages divided
between their users), rather than summing overlapping RSS values:

| Linux process group | PSS |
| --- | --- |
| Continent ZTN GUI and services | 441.4 MiB |
| TigerVNC desktop server | 146.4 MiB |
| Horizon client and protocol processes | 127.3 MiB |

These are selected groups, not the entire operating system. Do not add them to
the guest or host totals; they are already included in those totals.

## Windows measurement procedure

After the owner connects through Windows, use the same remote desktop and
roughly the same applications/activity. Take three guest available-memory
samples 10 seconds apart, record Windows' total visible memory and process
working sets, and take a simultaneous Proxmox `memhost` reading. Compare both
guest demand and host footprint; configured memory alone is not usage.

Leave Windows, Linux, and `corp-socks` unchanged until the owner reviews the
comparison and corporate access/reconnect checks are complete.

## Result

Mean guest total minus available was 1018.5 MiB on Linux versus 2271.1 MiB on
Windows: about 1252.6 MiB (1.22 GiB), or 55.2%, less on Linux in these samples.
The active Linux host footprint was about 2.53 GiB lower. Host footprints include
cached memory and hypervisor overhead; the configured allocation difference is
exactly 2 GiB and must not be confused with a guaranteed usage reduction.

At the Windows sampling time, Linux's `memhost` was 1,638,969,344 bytes (1.53 GiB),
but its corporate session was no longer the active comparison workload; the table
retains the earlier active Linux baseline instead.

Windows process working sets were: vmware-view 205.2 MiB, vmware-remotemks
79.7 MiB, horizon_client_service 12.6 MiB, vmware-usbarbitrator64 10.8 MiB, and
ZtnClient 183.3 MiB. These are RSS/working sets, not Linux PSS, and must not be
compared directly with the process-group PSS table.

This is a short operational comparison, not a controlled benchmark: client
versions/codecs differ and measurements include the diagnostic process overhead.
Both VMs remain running. No Windows shutdown or SOCKS target change was made.

## Subsequent owner decision

After reviewing this comparison, the owner requested Windows VM 170 be stopped
and prevented from starting automatically. On 2026-11-16, it was shut down and
set to `onboot: 0`. The Windows VM and disk were retained; Linux VM 172 remains
running with automatic boot enabled. The earlier statement that both VMs were
running describes only the measurement interval.
