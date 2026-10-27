# Claude SDK Host Service

Private, fail-closed runtime executor for the official Claude Agent SDK, Playwright/Chromium, and OpenAI-compatible completion APIs.

---

## 1. Architecture Overview

The deployable stack is organized into a three-service unit within dedicated Docker networks:

```
+---------------------------------------------------------------------------------+
| Docker Host Network Namespace                                                   |
|                                                                                 |
|  +---------------------------------------------------------------------------+  |
|  | Shared Network Namespace (owned by sdk-netguard)                          |  |
|  |                                                                           |  |
|  |  +--------------------+         +-------------------------------------+   |  |
|  |  | sdk-netguard       |         | claude-sdk-host                     |   |  |
|  |  | - NET_ADMIN        |         | - Non-root pwuser (1000:1000)       |   |  |
|  |  | - Atomic nftables  |         | - Chromium Sandbox (seccomp)        |   |  |
|  |  | - Default DROP     |         | - Python 3.12 + FastAPI + Agent SDK |   |  |
|  |  +---------+----------+         | - Private shm (512m), init: true    |   |  |
|  |            |                    | - No Docker socket, cap_drop ALL    |   |  |
|  |            |                    +------------------+------------------+   |  |
|  +------------|---------------------------------------|----------------------+  |
|               |                                       |                          |
|    sdk_clients (172.31.240.0/28, internal)            |                          |
|    sdk_tools   (172.31.240.16/28, internal)           |                          |
|    sdk_proxy   (172.31.240.32/28, internal)           |                          |
|               |                                       |                          |
|  +------------v---------------------------------------v----------------------+  |
|  | sdk-egress (172.31.240.35)                                                |  |
|  | - GOST HTTP Frontend (:8080)                                               |  |
|  | - Mandatory Upstream Chaining (SOCKS5/HTTP from secret config)            |  |
|  | - No direct bypass; fail closed on absent secret or upstream              |  |
|  | - No HTTP header or body logging                                          |  |
|  +------------------------------------+--------------------------------------+  |
|                                       |                                         |
|    sdk_upstream (172.31.240.48/28)    |                                         |
|                                       v                                         |
|  +---------------------------------------------------------------------------+  |
|  | Configured Upstream Proxy (External / Host SOCKS5/HTTP Exit)              |  |
|  +---------------------------------------------------------------------------+  |
+---------------------------------------------------------------------------------+
```

### Security & Isolation Principles
- **Fail-Closed Networking**: `sdk-netguard` applies atomic nftables IPv4/IPv6 rules dropping all inbound and outbound traffic by default. Outbound direct external IPv4/IPv6, UDP/QUIC, and all DNS (including Docker resolver `127.0.0.11`) are dropped.
- **Mandatory Egress Chaining**: All external traffic MUST transit through `sdk-egress` (GOST) to the configured upstream. If the upstream fails or secret config is missing, traffic fails closed.
- **Unprivileged Execution**: `claude-sdk-host` runs as non-root `pwuser` (`1000:1000`), drops all capabilities (`cap_drop: [ALL]`), enables `no-new-privileges: true`, runs Chromium with its native sandbox via `deploy/seccomp/chromium.json`, mounts 512 MiB private shared memory, and has no Docker socket.
- **Zero Secrets in Repository**: Secrets and credentials are provided exclusively via operator-mounted files outside the repository.

---

## 2. Directory & Network Layout

### Network Subnets
The stack reserves four non-overlapping `/28` CIDR blocks:
- `sdk_clients` (`172.31.240.0/28`): Internal network connecting client applications (e.g. TMS) to the API.
- `sdk_tools` (`172.31.240.16/28`): Internal network connecting netguard to registered tool/MCP/stand endpoints.
- `sdk_proxy` (`172.31.240.32/28`): Internal network connecting netguard to `sdk-egress` (`172.31.240.35:8080`).
- `sdk_upstream` (`172.31.240.48/28`): Uplink network connecting `sdk-egress` to the external upstream proxy.

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

2. Prepare operator secret configuration files on the host (outside repository):
   - `/etc/claude-sdk-host/secrets/host-config.json` (structure based on `config.example.json`)
   - `/etc/claude-sdk-host/secrets/gost-config.json` (structure based on `deploy/egress/gost.example.json`)

3. Ensure secret file permissions are restricted:
   ```bash
   chmod 600 /etc/claude-sdk-host/secrets/*.json
   ```

---

## 5. Auth Volume Provisioning

The official authentication volume (`claude_sdk_auth`) must be initialized with explicit non-root ownership (`1000:1000`, `0700`) without opening unauthenticated network ports:

```bash
./deploy/scripts/provision-auth.sh
```

---

## 6. Official Claude Login Maintenance

To authenticate your personal Claude subscription with the official Claude Code CLI:

```bash
./deploy/scripts/login-maintenance.sh
```

This starts a one-off interactive maintenance container attached to `sdk_proxy`, runs official `claude login`, and stores the refreshable session tokens safely in `claude_sdk_auth`. No tokens are printed or stored in git.

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
  -v /etc/claude-sdk-host/secrets/host-config.json:/run/secrets/host-config.json:ro \
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
1. `sdk-netguard` loads nftables ruleset and reports healthy.
2. `sdk-egress` verifies secret configuration, connects upstream, and reports healthy.
3. `claude-sdk-host` starts only after both sidecars are healthy.

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

### Drain, Cancel & Recreate Whole Namespace
When performing maintenance or updating configuration, recreate the stack atomically to avoid unmanaged network namespaces:
```bash
./deploy/scripts/drain-recreate.sh
```

---

## 9. Local API Usage (curl Examples)

*(Execute from an authorized container on `sdk_clients` or via loopback debug port `127.0.0.1:8080`)*

### 1. Health Endpoints
```bash
# Liveness probe
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
    "model": "claude-personal-default",
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
    "model": "claude-personal-default",
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
This tests shell syntax for all scripts (`bash -n`), verifies JSON configuration templates (`jq`), and runs `docker compose config` against temporary mock secret files.
