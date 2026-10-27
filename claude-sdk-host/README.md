# Claude SDK Host Service

Private, fail-closed runtime executor for the official Claude Agent SDK, Playwright/Chromium, and OpenAI-compatible completion APIs.

---

## 1. Architecture Overview

The deployable stack is organized into a four-service unit within dedicated Docker networks:

```
+---------------------------------------------------------------------------------------------------+
| Docker Host Network Namespace                                                                     |
|                                                                                                   |
|  +---------------------------------------------------------------------------------------------+  |
|  | Host Network Namespace (owned by sdk-netguard)                                              |  |
|  |                                                                                             |  |
|  |  +---------------------------+         +-------------------------------------------------+  |  |
|  |  | sdk-netguard              |         | claude-sdk-host                                 |  |  |
|  |  | - NET_ADMIN (only guard)  |         | - Non-root pwuser (1000:1000), read_only: true  |  |  |
|  |  | - Atomic nftables inet    |         | - Playwright v1.64.1 seccomp profile            |  |  |
|  |  | - Default DROP            |         | - Python 3.12 + FastAPI + Agent SDK             |  |  |
|  |  | - /etc/hosts mounted      |         | - Private shm (512m), init: true, tmpfs work    |  |  |
|  |  +-------------+-------------+         | - No Docker socket, cap_drop: [ALL]             |  |  |
|  |                |                       +------------------------+------------------------+  |  |
|  +----------------|------------------------------------------------|---------------------------+  |
|                   |                                                |                              |
|    sdk_clients (172.31.240.0/28, internal)                         |                              |
|    sdk_tools   (172.31.240.16/28, internal)                        |                              |
|    sdk_proxy   (172.31.240.32/28, internal)                        |                              |
|                   |                                                |                              |
|  +----------------v------------------------------------------------v---------------------------+  |
|  | Egress Network Namespace (owned by sdk-egress-guard)                                         |  |
|  |                                                                                             |  |
|  |  +---------------------------+         +-------------------------------------------------+  |  |
|  |  | sdk-egress-guard          |         | sdk-egress                                      |  |  |
|  |  | - NET_ADMIN (only guard)  |         | - Unprivileged GOST v2 (:8080), read_only: true |  |  |
|  |  | - Uplink strictly to      |         | - Mandatory Upstream Chaining (SOCKS5/HTTP)     |  |  |
|  |  |   numeric upstream IP     |         | - No direct bypass; fail-closed on missing conf |  |  |
|  |  | - Drops DNS, IPv6, UDP    |         | - Credential URL & header logging suppressed    |  |  |
|  |  +-------------+-------------+         +-------------------------------------------------+  |  |
|  +----------------|----------------------------------------------------------------------------+  |
|                   |                                                                               |
|    sdk_upstream (172.31.240.48/28, uplink)                                                        |
|                   |                                                                               |
|                   v                                                                               |
|  +---------------------------------------------------------------------------------------------+  |
|  | Configured Upstream Proxy (External / Host SOCKS5/HTTP Exit at numeric IP:port)             |  |
|  +---------------------------------------------------------------------------------------------+  |
+---------------------------------------------------------------------------------------------------+
```

### Security & Isolation Principles
- **Fail-Closed Networking**: `sdk-netguard` and `sdk-egress-guard` alone receive `NET_ADMIN`. They atomically apply managed `table inet netguard` rulesets (preserving Docker NAT), dropping all inbound and outbound traffic by default. Outbound direct external IPv4/IPv6, UDP/QUIC, and all DNS (including Docker resolver `127.0.0.11`) are dropped.
- **Mandatory Egress Chaining & Guarded Uplink**: All external traffic from `claude-sdk-host` transits through `sdk-egress` (GOST) over internal `sdk_proxy`. `sdk-egress` is strictly isolated inside `sdk-egress-guard`'s namespace; its uplink is restricted at the packet level to only the configured numeric upstream proxy IP and port. No direct bypass is possible.
- **Unprivileged Non-Root Execution**: Both `claude-sdk-host` and `sdk-egress` drop all Linux capabilities (`cap_drop: [ALL]`), enforce `no-new-privileges: true`, and have root filesystems mounted `read_only: true` with writable tmpfs mounts for `/tmp` and `/tmp/claude-host`.
- **Official Playwright Seccomp Profile**: Uses the official pinned profile from `microsoft/playwright` tag `v1.64.1` (`deploy/seccomp/seccomp_profile.json`). No broad hand-written allowlists, `seccomp:unconfined`, `SYS_ADMIN`, host IPC, or `--no-sandbox` flags are used.
- **Zero Secrets in Repository**: Secrets and credentials are provided exclusively via an operator-mounted directory outside the repository (`HOST_SECRETS_DIR`, mounted read-only as `/run/secrets`).

---

## 2. Directory & Network Layout

### Network Subnets
The stack reserves four non-overlapping `/28` CIDR blocks:
- `sdk_clients` (`172.31.240.0/28`, `internal: true`): Internal network connecting client applications (e.g. TMS) to the API.
- `sdk_tools` (`172.31.240.16/28`, `internal: true`): Internal network connecting netguard to registered tool/MCP/stand endpoints.
- `sdk_proxy` (`172.31.240.32/28`, `internal: true`): Internal network connecting netguard to `sdk-egress` (`172.31.240.35:8080`).
- `sdk_upstream` (`172.31.240.48/28`, `internal: false`): Uplink network connecting `sdk-egress-guard` to the external upstream proxy.

---

## 3. Preflight Conflict Check

Before creating networks or launching containers, run the preflight verification script to ensure no host routing or Docker IPAM conflicts exist:

```bash
./deploy/scripts/preflight-check.sh
```

---

## 4. Configuration & Secrets Setup

1. Copy `.env.example` to `.env` (never commit `.env` with live paths):
   ```bash
   cp .env.example .env
   ```

2. Prepare the operator secret directory outside Git (e.g. `/etc/claude-sdk-host/secrets/`):
   - `host-config.json` (structure matching coordinator `Settings`, based on `config.example.json`)
   - `gost-config.json` (structure based on `deploy/egress/gost.example.json`)
   - `idempotency.key` (random secret key file >= 24 chars)
   - `apps/tms-app.token` (token file for client app >= 24 chars)
   - `providers/tms-credentials.token` (token file for credential provider >= 24 chars)
   - `providers/tms-credentials-ca.crt` (custom CA certificate if required)

3. Ensure secret file permissions are readable by UID 1000 (`pwuser`):
   ```bash
   chmod 700 /etc/claude-sdk-host/secrets
   chmod 644 /etc/claude-sdk-host/secrets/*.json /etc/claude-sdk-host/secrets/*.key
   chmod 644 /etc/claude-sdk-host/secrets/apps/* /etc/claude-sdk-host/secrets/providers/*
   ```

4. Generate static internal hosts file:
   ```bash
   ./deploy/scripts/generate-peers.sh /etc/claude-sdk-host/secrets/host-config.json ./deploy/hosts
   ```

---

## 5. Auth & Journal Volume Provisioning

Both the official authentication volume (`claude_sdk_auth`) and durable journal volume (`claude_sdk_journal`) must be initialized with explicit non-root ownership (`1000:1000`, `0700`) without opening unauthenticated network ports:

```bash
./deploy/scripts/provision-auth.sh
```

---

## 6. Official Claude Login Maintenance

To authenticate your personal Claude subscription via the official Claude Code CLI:

```bash
./deploy/scripts/login-maintenance.sh
```

This runs an interactive session strictly inside the guarded SDK namespace (inheriting the same auth volume, netguard firewall, and egress proxy). It dynamically discovers the bundled Claude Code CLI binary inside `claude-agent-sdk` via Python (rather than assuming a global `claude` binary on PATH) and executes `auth login`. It does not print `HTTP_PROXY` or read/print any credentials.

---

## 7. Build & Config Validation

### Build Container Images
```bash
docker compose build
```

### Validate Host Configuration
Verify the host configuration secret without running the API service:
```bash
docker run --rm \
  -v /etc/claude-sdk-host/secrets:/run/secrets:ro \
  claude-sdk-host:local \
  check-config --config /run/secrets/host-config.json
```

---

## 8. Service Operations

### Start the Service Stack
```bash
docker compose up -d
```

### Health Check Gating
Startup is strictly gated:
1. `sdk-netguard` loads atomic nftables ruleset and reports healthy.
2. `sdk-egress-guard` loads uplink restriction ruleset and reports healthy.
3. `sdk-egress` validates secret configuration, verifies upstream chaining, and reports healthy.
4. `claude-sdk-host` starts only after both netguard and egress are healthy.

Check status:
```bash
docker compose ps
docker compose logs -f
```

### Loopback Debug Mode (Optional)
If local host debugging is needed, bind the API to loopback (`127.0.0.1:8080`) using the debug overlay:
```bash
docker compose -f docker-compose.yml -f docker-compose.debug.yml up -d
```

### Graceful Drain, Cancel & Recreate
To drain in-flight sessions and recreate the namespace unit according to coordinator process contracts:
```bash
./deploy/scripts/drain-recreate.sh
```
1. Sends `SIGUSR1` to `claude-sdk-host` to set `draining: true` (rejecting new incoming requests).
2. Executes an in-container urllib probe to `http://127.0.0.1:8080/health/live` to poll `active == 0` and `queued == 0` within a bounded timeout (`DRAIN_TIMEOUT_SECONDS`, default 60s).
3. If timeout expires, proceeds with `SIGTERM` shutdown.
4. Tears down existing namespace containers and recreates the stack (`docker compose down` then `docker compose up -d`). Note that teardown and startup are distinct, sequential operations rather than an atomic kernel operation.

---

## 9. Local API Usage (curl Examples)

*(Execute from an authorized container on `sdk_clients` or via loopback debug port `127.0.0.1:8080`)*

### 1. Health Endpoints
```bash
# Liveness probe (exposes active, queued, draining)
curl -s http://claude-sdk-host:8080/health/live

# Readiness probe (verifies nftables, proxy reachability, auth state)
curl -s http://claude-sdk-host:8080/health/ready
```

### 2. OpenAI-Compatible Chat Completion (max_turns=1)
```bash
curl -s -X POST http://claude-sdk-host:8080/v1/chat/completions \
  -H "Authorization: Bearer <APP_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-sonnet-5-5",
    "messages": [
      {"role": "user", "content": "Write three test cases for password reset."}
    ],
    "stream": false
  }'
```

### 3. Create Agent Session
```bash
curl -s -X POST http://claude-sdk-host:8080/v1/agent-sessions \
  -H "Authorization: Bearer <APP_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "client_request_id": "req-001",
    "model": "claude-sonnet-5-5",
    "profile": "tms-execution",
    "task_prompt": "Run UI sanity inspection on stand.",
    "deadline_seconds": 600,
    "token_budget_remaining": 500000,
    "max_turns": 10
  }'
```

---

## 10. Manual Egress Acceptance Verification

Verify fail-closed firewall enforcement (NET-01, NET-02, NET-03) on a running stack:

```bash
./deploy/scripts/verify-egress.sh
```

Verification assertions:
- **NET-01**: Outbound HTTPS through the proxy succeeds and displays the upstream-observed exit IP.
- **NET-02**: Outbound connection with `--noproxy '*'` immediately fails closed (connection timed out / rejected).
- **NET-03**: Outbound DNS packets to `127.0.0.11` (Docker embedded resolver) and `8.8.8.8` are dropped by nftables.

---

## 11. Isolated Local Smoke Recipe

Run full synthetic smoke verification without connecting to a Docker daemon or reading production proxy secrets:

```bash
./deploy/scripts/smoke-test.sh
```
This tests shell syntax for all scripts (`bash -n`), verifies JSON configuration templates (`jq`), tests static peers generation, and runs `docker compose config` against temporary mock secret files.
