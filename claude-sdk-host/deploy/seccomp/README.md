# Playwright Docker Seccomp Profile

- **Source Repository:** `microsoft/playwright`
- **Tag:** `v1.64.1`
- **Source Path:** `utils/docker/seccomp_profile.json`
- **Source URL:** https://raw.githubusercontent.com/microsoft/playwright/v1.64.1/utils/docker/seccomp_profile.json
- **License / Attribution:** Copyright (c) Microsoft Corporation. Licensed under the Apache License, Version 2.0.

This profile is the official, unprivileged Chromium sandbox profile provided by the Playwright maintainers. It restricts Linux syscalls using `SCMP_ACT_ERRNO` while permitting necessary unprivileged operations (such as non-root user namespaces, clone, etc.) required for Chromium's internal sandbox.

It is pinned exactly to Playwright version 1.64.1 to avoid broad hand-written allowlists, `seccomp:unconfined`, `SYS_ADMIN` capabilities, host IPC, or `--no-sandbox` flags.
