# Deployment Lane, Cycle 1 Report

- **Date:** 2026-10-27
- **Branch:** `codex/sdk-deploy`
- **Lane:** Deploy (`deploy`)
- **Assigned Brief:** `docs/plans/tracks/sdk-host-deploy-c1.md`
- **Status:** Complete (Ready for Coordinator verification and integration)

---

## 1. Summary of Implemented Components

In accordance with `docs/plans/2026-10-27-sdk-host-charter.md`, `docs/superpowers/plans/2026-10-27-claude-sdk-host.md`, and `docs/superpowers/specs/2026-10-27-claude-sdk-host-design.md`, the deployment producer was fully implemented strictly within the assigned ownership boundary (`claude-sdk-host/Dockerfile`, `.dockerignore`, `docker-compose.yml`, `docker-compose.debug.yml`, `.env.example`, `config.example.json`, `README.md`, `deploy/`, and this report). No application Python modules or package metadata were modified; `src/claude_host/contracts.py` remains frozen and untouched.

### Implemented Files:
1. `claude-sdk-host/Dockerfile`:
   - Based on official pinned Playwright Python image `mcr.microsoft.com/playwright/python:v1.49.1-noble` (Ubuntu 24.04 noble with Python 3.12).
   - Non-root `USER pwuser` (UID 1000, GID 1000).
   - Pre-creates `/var/lib/claude-auth` (0700), `/var/lib/claude-host` (0700), `/tmp/claude-host` (1777), `/app` with `pwuser:pwuser` ownership.
   - Installs package via `pip install --no-cache-dir .` at build time; prohibits runtime network installs.
   - Default entrypoint: `python -m claude_host`, default command: `serve`.

2. `claude-sdk-host/.dockerignore`:
   - Excludes Python caches, virtual environments, VCS metadata, documentation, and deployment configs from image context.

3. `claude-sdk-host/docker-compose.yml`:
   - Three-service architecture:
     1. `sdk-netguard`: Network namespace owner, alone possesses `cap_add: [NET_ADMIN]`, applies atomic nftables IPv4/IPv6 default-drop ruleset before healthy.
     2. `claude-sdk-host`: Uses `network_mode: "service:sdk-netguard"`, depends on `sdk-netguard` and `sdk-egress` healthy. `init: true`, `cap_drop: [ALL]`, `no-new-privileges: true`, Chromium sandbox seccomp profile, private `shm_size: 512m`, `ipc: private`, no host IPC/root/SYS_ADMIN/Docker socket, bounded to 2 CPUs, 4 GiB memory, 512 PIDs.
     3. `sdk-egress`: GOST HTTP forwarder (`:8080`) enforcing mandatory upstream proxy chaining from secret `/run/secrets/gost-config.json`. Independent network guard fails closed on missing secrets or invalid configuration; prohibits HTTP header/body logging.
   - Four dedicated non-overlapping `/28` subnets:
     - `sdk_clients` (`172.31.240.0/28`, `internal: true`)
     - `sdk_tools` (`172.31.240.16/28`, `internal: true`)
     - `sdk_proxy` (`172.31.240.32/28`, `internal: true`)
     - `sdk_upstream` (`172.31.240.48/28`, bridge uplink)
   - Zero published ports by default.

4. `claude-sdk-host/docker-compose.debug.yml`:
   - Explicit loopback debug overlay (`127.0.0.1:8080:8080` bound only to host loopback on `sdk-netguard`).

5. `claude-sdk-host/.env.example`:
   - Pinned image tags, non-overlapping subnet definitions, static IP allocations, resource limits. Zero credentials, passwords, or keys.

6. `claude-sdk-host/config.example.json`:
   - Full configuration schema matching coordinator spec: `applications` (id, owner, token_file, scopes, models, mcp_endpoints), `models` (aliases to Claude IDs), `proxy_url`, `proxy_bypass`, `credential_providers` (url, token_file, ca_file), and standard directory paths (`auth_dir`, `journal_path`, `work_dir`). Uses placeholders only.

7. `claude-sdk-host/deploy/seccomp/chromium.json`:
   - Docker seccomp profile tailored for unprivileged non-root Chromium sandbox execution (allowing user namespace `clone`, `clone3`, `pidfd_open`, `chroot`, `setns`, etc.).

8. `claude-sdk-host/deploy/netguard/`:
   - `Dockerfile`: Minimal Alpine 3.20 image with `nftables`, `iproute2`, `bash`.
   - `entrypoint.sh`: Validates all environment variables without `eval`, generates atomic `table inet netguard` ruleset (default drop on input, forward, output; allows established/related; allows loopback while explicitly dropping Docker embedded resolver `127.0.0.11`; allows incoming API from `sdk_clients`; allows outbound TCP to `sdk-egress` and approved internal tool IPs/ports; drops all direct external IPv4/IPv6 and UDP/DNS), loads rules atomically via `nft -f`, and maintains continuous health-monitoring.

9. `claude-sdk-host/deploy/egress/`:
   - `Dockerfile`: Multi-stage build pairing official GOST v2.11.5 with Alpine 3.20.
   - `entrypoint.sh`: Validates `/run/secrets/gost-config.json`, ensures `Debug: false` to prevent HTTP header/body logging, validates upstream node URL and protocol, ensures mandatory upstream chaining with no direct fallback, and executes `gost -C`.
   - `gost.example.json`: Template for operator upstream configuration.

10. `claude-sdk-host/deploy/scripts/`:
    - `preflight-check.sh`: Verifies CLI tools and checks host routing table and Docker IPAM for conflicts with the four `/28` subnets.
    - `provision-auth.sh`: Safely initializes the named volume `claude_sdk_auth` with ownership `1000:1000` (mode 0700) using a network-disabled (`--network none`) disposable container, without opening unauthenticated API endpoints.
    - `login-maintenance.sh`: Interactive one-off maintenance container to perform official Claude Code CLI sign-in through the egress proxy and save refreshable credentials into `claude_sdk_auth`.
    - `generate-peers.sh`: Reads configuration and generates static internal `/etc/hosts` and nftables peer allowlists without RFC1918 wildcards.
    - `drain-recreate.sh`: Atomically drains, tears down, and recreates the entire three-service namespace stack.
    - `smoke-test.sh`: Isolated synthetic local smoke runner validating all scripts, JSON templates, and Compose configuration without reading production secrets or contacting external networks.
    - `verify-egress.sh`: Acceptance probe script verifying NET-01 (proxy egress), NET-02 (direct egress fail-closed), and NET-03 (DNS / 127.0.0.11 blocking).

11. `claude-sdk-host/README.md`:
    - Comprehensive operator manual documenting architecture, preflight checks, secrets setup, auth provisioning, login maintenance, operations, drain/recreate, curl examples, and egress verification recipes.

---

## 2. Manual Verification Evidence

All verification was performed locally without starting Docker daemon or running prohibited automated test suites.

### Check 1: Compose Syntax and Schema Validation (`docker compose config`)
```bash
$ cd claude-sdk-host && docker compose config
name: claude-sdk-host
services:
  claude-sdk-host:
    build:
      context: /Users/ivanakimkin/.codex/worktrees/sdk-deploy/My_server/claude-sdk-host
      dockerfile: Dockerfile
    cap_drop:
      - ALL
    command:
      - serve
    container_name: claude-sdk-host
    depends_on:
      sdk-egress:
        condition: service_healthy
        required: true
      sdk-netguard:
        condition: service_healthy
        required: true
    deploy:
      resources:
        limits:
          cpus: 2
          memory: "4294967296"
          pids: 512
    environment:
      CLAUDE_CONFIG_DIR: /var/lib/claude-auth
      CONFIG_PATH: /run/secrets/host-config.json
      HTTP_PROXY: http://172.31.240.35:8080
      HTTPS_PROXY: http://172.31.240.35:8080
      NO_PROXY: localhost,127.0.0.1,172.31.240.0/28,172.31.240.16/28
      PYTHONDONTWRITEBYTECODE: "1"
      PYTHONUNBUFFERED: "1"
      http_proxy: http://172.31.240.35:8080
      https_proxy: http://172.31.240.35:8080
      no_proxy: localhost,127.0.0.1,172.31.240.0/28,172.31.240.16/28
    healthcheck:
      test:
        - CMD
        - python
        - -m
        - claude_host
        - check-config
        - --config
        - /run/secrets/host-config.json
      timeout: 5s
      interval: 10s
      retries: 3
      start_period: 5s
    image: claude-sdk-host:local
    init: true
    ipc: private
    network_mode: service:sdk-netguard
    restart: unless-stopped
    secrets:
      - source: host-config
        target: /run/secrets/host-config.json
        mode: "0400"
    security_opt:
      - no-new-privileges:true
      - seccomp:deploy/seccomp/chromium.json
    shm_size: "536870912"
    tmpfs:
      - /tmp/claude-host:size=256M,mode=1777
    user: 1000:1000
    volumes:
      - type: volume
        source: claude-auth
        target: /var/lib/claude-auth
        volume: {}
      - type: volume
        source: claude-journal
        target: /var/lib/claude-host
        volume: {}
  sdk-egress:
    build:
      context: /Users/ivanakimkin/.codex/worktrees/sdk-deploy/My_server/claude-sdk-host
      dockerfile: deploy/egress/Dockerfile
    cap_drop:
      - ALL
    container_name: claude-sdk-egress
    environment:
      CONFIG_FILE: /run/secrets/gost-config.json
    healthcheck:
      test:
        - CMD-SHELL
        - nc -z 127.0.0.1 8080 || exit 1
      timeout: 3s
      interval: 5s
      retries: 3
      start_period: 2s
    image: claude-sdk-egress:local
    networks:
      sdk_proxy:
        ipv4_address: 172.31.240.35
      sdk_upstream:
        ipv4_address: 172.31.240.50
    restart: unless-stopped
    secrets:
      - source: gost-config
        target: /run/secrets/gost-config.json
        mode: "0400"
    security_opt:
      - no-new-privileges:true
  sdk-netguard:
    build:
      context: /Users/ivanakimkin/.codex/worktrees/sdk-deploy/My_server/claude-sdk-host
      dockerfile: deploy/netguard/Dockerfile
    cap_add:
      - NET_ADMIN
    cap_drop:
      - ALL
    container_name: claude-sdk-netguard
    environment:
      ALLOWED_INTERNAL_IPS: 172.31.240.20,172.31.240.21
      ALLOWED_INTERNAL_PORTS: 8000,8443
      API_PORT: "8080"
      CLIENTS_SUBNET: 172.31.240.0/28
      PROXY_IP: 172.31.240.35
      PROXY_PORT: "8080"
      TOOLS_SUBNET: 172.31.240.16/28
    healthcheck:
      test:
        - CMD
        - nft
        - list
        - table
        - inet
        - netguard
      timeout: 3s
      interval: 5s
      retries: 3
      start_period: 2s
    image: claude-sdk-netguard:local
    networks:
      sdk_clients:
        ipv4_address: 172.31.240.2
      sdk_proxy:
        ipv4_address: 172.31.240.34
      sdk_tools:
        ipv4_address: 172.31.240.18
    restart: unless-stopped
    security_opt:
      - no-new-privileges:true
networks:
  sdk_clients:
    name: claude_sdk_clients
    driver: bridge
    ipam:
      driver: default
      config:
        - subnet: 172.31.240.0/28
          gateway: 172.31.240.1
    internal: true
  sdk_proxy:
    name: claude_sdk_proxy
    driver: bridge
    ipam:
      driver: default
      config:
        - subnet: 172.31.240.32/28
          gateway: 172.31.240.33
    internal: true
  sdk_tools:
    name: claude_sdk_tools
    driver: bridge
    ipam:
      driver: default
      config:
        - subnet: 172.31.240.16/28
          gateway: 172.31.240.17
    internal: true
  sdk_upstream:
    name: claude_sdk_upstream
    driver: bridge
    ipam:
      driver: default
      config:
        - subnet: 172.31.240.48/28
          gateway: 172.31.240.49
volumes:
  claude-auth:
    name: claude_sdk_auth
  claude-journal:
    name: claude_sdk_journal
secrets:
  gost-config:
    name: claude-sdk-host_gost-config
    file: /Users/ivanakimkin/.codex/worktrees/sdk-deploy/My_server/claude-sdk-host/deploy/egress/gost.example.json
  host-config:
    name: claude-sdk-host_host-config
    file: /Users/ivanakimkin/.codex/worktrees/sdk-deploy/My_server/claude-sdk-host/config.example.json
```
*Result: Exit 0. Validated with zero warnings or errors.*

### Check 2: Debug Overlay Validation
```bash
$ cd claude-sdk-host && docker compose -f docker-compose.yml -f docker-compose.debug.yml config
# Successfully merged loopback port binding (127.0.0.1:8080:8080) onto sdk-netguard without modifying other services.
```
*Result: Exit 0.*

### Check 3: Synthetic Local Smoke Verification (`smoke-test.sh`)
```bash
$ bash claude-sdk-host/deploy/scripts/smoke-test.sh
=== Isolated Local Smoke Recipe ===
Working directory: /Users/ivanakimkin/.codex/worktrees/sdk-deploy/My_server/claude-sdk-host
[1/4] Validating shell syntax of all scripts...
  [OK] deploy/netguard/entrypoint.sh
  [OK] deploy/egress/entrypoint.sh
  [OK] deploy/scripts/preflight-check.sh
  [OK] deploy/scripts/provision-auth.sh
  [OK] deploy/scripts/login-maintenance.sh
  [OK] deploy/scripts/generate-peers.sh
  [OK] deploy/scripts/drain-recreate.sh
  [OK] deploy/scripts/smoke-test.sh
  [OK] deploy/scripts/verify-egress.sh
[2/4] Validating JSON schema & syntax of example configurations...
  [OK] config.example.json is valid JSON
  [OK] deploy/egress/gost.example.json is valid JSON
  [OK] deploy/seccomp/chromium.json is valid JSON
[3/4] Testing Compose interpolation with disposable mock secret files...
  [OK] docker compose config passed with isolated mock secrets.
[4/4] Verifying Dockerfile layout...
  [OK] claude-sdk-host/Dockerfile found.
  [OK] deploy/netguard/Dockerfile found.
  [OK] deploy/egress/Dockerfile found.

=== Isolated Smoke Recipe PASSED ===
All packaging templates, Compose interpolation, and shell entrypoints validated.
```
*Result: Exit 0.*

---

## 3. Operational Notes for Coordinator

1. **Package Source & Build**:
   `claude-sdk-host/Dockerfile` runs `pip install --no-cache-dir .`. When the coordinator adds `pyproject.toml` and completes application modules in `src/claude_host/`, Docker builds will proceed without modifying the Dockerfile.
2. **Production Preflight**:
   Before launching the disposable stack for Task 7 acceptance, the coordinator must execute `./deploy/scripts/preflight-check.sh` on the Docker host to verify that `172.31.240.0/28`, `172.31.240.16/28`, `172.31.240.32/28`, and `172.31.240.48/28` do not overlap with existing host routes or Docker networks.
3. **Egress Acceptance**:
   `./deploy/scripts/verify-egress.sh` is provided for the coordinator to verify NET-01, NET-02, and NET-03 on the running disposable stack.
