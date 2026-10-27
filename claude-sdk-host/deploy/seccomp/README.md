# Chromium sandbox seccomp profile

`seccomp_profile.json` is the unmodified Microsoft Playwright profile at tag `v1.64.1`:
https://github.com/microsoft/playwright/blob/v1.64.1/utils/docker/seccomp_profile.json

Verified upstream SHA-256: `cc3e61cabda6bbc1e53e54d27ba4d55a9d3be829b6dd1a596f4a7b31b1cc7849`.

Compose uses `seccomp-host.json`, the same profile with one additional unconditional `chroot` syscall allowance. No additional Linux capability is granted. The upstream profile conditionally permits `chroot` only when Docker includes `CAP_SYS_CHROOT`; this service drops every initial-namespace capability. Chromium's sandbox creates a user namespace, gains capabilities only inside that namespace, then calls `chroot`. Without the seccomp allowance the real browser fails with `Check failed: sys_chroot("/proc/self/fdinfo/") == 0`.

The single syscall allowance was reproduced with non-root UID 1000, `cap_drop: ALL`, `no-new-privileges`, private IPC, read-only root and `chromium_sandbox=True`. The initial process still cannot perform a privileged chroot because it lacks the kernel capability. Keep the upstream file intact and review this small delta whenever upgrading Playwright. Do not substitute `seccomp:unconfined`, `SYS_ADMIN`, host IPC or `--no-sandbox`.
