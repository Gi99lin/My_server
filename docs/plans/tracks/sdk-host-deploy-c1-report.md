# Deployment Lane, Cycle 1 Report (Correction)

- **Date:** 2026-10-27
- **Branch:** `codex/sdk-deploy`
- **Lane:** Deploy (`deploy`)
- **Assigned Brief:** `docs/plans/tracks/sdk-host-deploy-c1-correction.md`
- **Status:** Complete (Ready for Coordinator verification and integration)

---

## 1. Summary of Implemented Components & Corrections

In accordance with `docs/plans/tracks/sdk-host-deploy-c1-correction.md`, the deployment producer was corrected and completed strictly within assigned ownership boundaries (`claude-sdk-host/Dockerfile`, `.dockerignore`, `docker-compose.yml`, `docker-compose.debug.yml`, `.env.example`, `config.example.json`, `README.md`, `deploy/`, and this report). Application Python code in `src/claude_host/` remains frozen and untouched.

### Concrete Findings Resolved:

1. **Playwright Pinning (Finding 1)**:
   - Updated `claude-sdk-host/Dockerfile` base image from `v1.49.1-noble` to the official matching pinned release `mcr.microsoft.com/playwright/python:v1.64.1-noble` (Ubuntu 24.04 noble with Python 3.12), matching coordinator's `playwright==1.64.1` and `claude-agent-sdk==0.2.174`.
   - No external or global CLI packages are installed at image build or runtime; the official Claude Code CLI bundled in `claude-agent-sdk` wheel is utilized.

2. **Fourth Sidecar: Dedicated Egress Guard (Finding 2)**:
   - Recorded and implemented the fourth sidecar container `sdk-egress-guard` as a necessary correction to the earlier three-service simplification.
   - `sdk-egress-guard` uses the same netguard image and owns the network namespace for `sdk-egress` (`network_mode: service:sdk-egress-guard`).
   - Only the two guard containers (`sdk-netguard` and `sdk-egress-guard`) receive `cap_add: [NET_ADMIN]`.
   - `ROLE=egress` strictly restricts packet transmission: allows input from `sdk_proxy` (`172.31.240.32/28`) to port 8080, loopback (with 127.0.0.11 blocked), and permits output ONLY to configured numeric upstream IPs and TCP port (`UPSTREAM_IPS` / `UPSTREAM_PORTS`). Denies all DNS, IPv6, UDP/QUIC, and direct routes.
   - No application container shares the proxy uplink network (`sdk_upstream`).
   - Both guards install policy and verify table state before signaling healthy.

3. **Official Pinned Playwright Seccomp Profile (Finding 3)**:
   - Replaced handwritten broad seccomp syscall allowlist with the official pinned Playwright profile `deploy/seccomp/seccomp_profile.json` from `microsoft/playwright` tag `v1.64.1` (`utils/docker/seccomp_profile.json`).
   - Retained source URL and Apache-2.0 Microsoft attribution in `deploy/seccomp/README.md` and `README.md`.
   - Avoids broad allowlists, `seccomp:unconfined`, `SYS_ADMIN`, host IPC, or `--no-sandbox`.

4. **Atomic Netguard Ruleset & DNS Blocking (Finding 4)**:
   - Replaced disruptive `flush ruleset` in `deploy/netguard/entrypoint.sh` with atomic creation/replacement of only the managed table (`table inet netguard`), preserving Docker-owned NAT rules.
   - Explicitly drops Docker embedded resolver `127.0.0.11` before loopback allowance in both input and output chains.
   - Strict validation of all input variables without `eval`.
   - Fails closed on missing or invalid upstream configuration; strictly prohibits broad RFC1918 wildcards.
   - Never prints URLs containing credentials or sensitive parameters.

5. **Config Schema Alignment with Coordinator Settings (Finding 5)**:
   - Corrected `claude-sdk-host/config.example.json` to strictly match coordinator's `Settings` model (`src/claude_host/config.py`).
   - Removed `$schema` and `comment` fields (which violated `extra="forbid"`).
   - Added `"idempotency_key_file": "/run/secrets/idempotency.key"`.
   - Added `credential_providers: ["tms-credentials"]` list to application definition.
   - Replaced obsolete model identifiers with `claude-sonnet-5-5` and `claude-haiku`.
   - Corrected `proxy_bypass` to exact hostnames/IPs only (`["localhost", "127.0.0.1", "172.31.240.20", "172.31.240.21"]`), removing invalid CIDRs.
   - Updated TMS MCP endpoint to actual path `/mcp/tms-execution` (`http://172.31.240.20:8000/mcp/tms-execution`).
   - Updated credential provider URL to end with `/api/v1/internal/claude-host/credentials` (`https://172.31.240.21:8443/api/v1/internal/claude-host/credentials`).
   - Zero real credentials in templates.

6. **Compose Secrets Directory, Read-Only FS & Static Hosts (Finding 6)**:
   - Configured operator secret directory mounted read-only as `/run/secrets:ro` via `${HOST_SECRETS_DIR:-./deploy/secrets_example}`, ensuring all app tokens, provider tokens, CAs, and idempotency keys are accessible.
   - Provided standalone example secrets in `deploy/secrets_example/` readable by UID 1000 (`pwuser`).
   - Configured `read_only: true` on containers with writable tmpfs mounts on `/tmp` and `/tmp/claude-host`.
   - Updated `provision-auth.sh` to deliberately provision both `claude_sdk_auth` and `claude_sdk_journal` with UID:GID 1000:1000 and mode 0700.
   - Zero external ports published by default (loopback binding isolated to `docker-compose.debug.yml`).
   - Added consistent service aliases (`claude-sdk-host` and `sdk-egress`) on namespace owner networks.
   - Generated static internal host mappings (`deploy/hosts`) via `generate-peers.sh` and wired them as read-only mounts into namespace owners (`/etc/hosts:ro`).

7. **Bundled CLI Login Maintenance (Finding 7)**:
   - Refactored `deploy/scripts/login-maintenance.sh` to run in the guarded SDK namespace using the persistent auth volume.
   - Dynamically discovers the bundled CLI binary inside the `claude-agent-sdk` package via Python (`Path(claude_agent_sdk.__file__).parent / '_bundled' / 'claude'`) rather than assuming a global `claude` binary on PATH.
   - Invokes `$CLI_PATH auth login`.
   - Never prints inherited `HTTP_PROXY` or reads/prints authentication tokens.

8. **Graceful Drain & Recreate (Finding 8)**:
   - Replaced abrupt stop in `deploy/scripts/drain-recreate.sh` with coordinator's process contract.
   - Sends `SIGUSR1` to `claude-sdk-host` via `docker compose kill -s SIGUSR1` to initiate draining mode.
   - Polls local in-container endpoint `http://127.0.0.1:8080/health/live` using an in-container urllib probe to verify `active == 0` and `queued == 0` within a bounded timeout (`DRAIN_TIMEOUT_SECONDS`, default 60s).
   - Proceeds with `docker compose down` and `docker compose up -d` sequentially; documentation clarifies that container recreation is non-atomic.

9. **Strict GOST Forwarder Validation & Log Redaction (Finding 9)**:
   - Refactored `deploy/egress/entrypoint.sh` to require `jq` unconditionally; removed debug fallback grep parser.
   - Fails closed on absent, empty, or invalid config files.
   - Rejects configurations with `Debug: true`, `Bypass`, `Routes`, or query options (`?`).
   - Requires exactly one HTTP frontend listener in `ServeNodes` and exactly one supported upstream parent (`socks5://`, `http://`, `https://`) in `ChainNodes`.
   - Never outputs ChainNode strings in errors or logs.
   - Executes GOST with an unbuffered stream filter (`sed -u -E`) that suppresses authorization headers and scrubs credential URLs (`://user:pass@`).

10. **Evidence & Verification Integrity (Finding 10)**:
    - Performed only non-destructive, authorized checks (`docker compose config`, shell syntax validation `bash -n`, python schema validation, static file generation).
    - No Docker containers were built or started, respecting the no-Docker brief ownership rule.
    - All verified command invocations and outputs below reflect actual executions.

---

## 2. Actual Verification Evidence

### Check 1: Coordinator Settings Validation with Pydantic
Executed against coordinator's `src/claude_host/config.py`:
```bash
$ uv run --with pydantic python -c "
import sys, json
sys.path.insert(0, '/Users/ivanakimkin/.codex/worktrees/claude-sdk-host/My_server/claude-sdk-host/src')
from claude_host.config import Settings

with open('claude-sdk-host/config.example.json', 'r') as f:
    data = json.load(f)

settings = Settings.model_validate(data)
print('Config validation SUCCEEDED!')
print('Applications:', [a.id for a in settings.applications])
print('Models:', list(settings.models.keys()))
print('Credential Providers:', list(settings.credential_providers.keys()))
print('Idempotency key file:', settings.idempotency_key_file)
"
```
**Output:**
```
Config validation SUCCEEDED!
Applications: ['tms-app']
Models: ['claude-sonnet-5-5', 'claude-haiku']
Credential Providers: ['tms-credentials']
Idempotency key file: /run/secrets/idempotency.key
```
*Result: Exit 0. Pydantic Settings model validation succeeded with zero errors.*

### Check 2: Secret Files Reading Verification
Tested `Settings.verify_secret_files()` with mock secrets in `deploy/secrets_example/`:
```bash
$ uv run --with pydantic python -c "
import sys, json
sys.path.insert(0, '/Users/ivanakimkin/.codex/worktrees/claude-sdk-host/My_server/claude-sdk-host/src')
from claude_host.config import Settings

with open('claude-sdk-host/deploy/secrets_example/host-config.json', 'r') as f:
    data = json.load(f)

data['idempotency_key_file'] = 'claude-sdk-host/deploy/secrets_example/idempotency.key'
data['applications'][0]['token_file'] = 'claude-sdk-host/deploy/secrets_example/apps/tms-app.token'
data['credential_providers']['tms-credentials']['token_file'] = 'claude-sdk-host/deploy/secrets_example/providers/tms-credentials.token'
data['credential_providers']['tms-credentials']['ca_file'] = 'claude-sdk-host/deploy/secrets_example/providers/tms-credentials-ca.crt'

settings = Settings.model_validate(data)
settings.verify_secret_files()
print('Secret files verified successfully!')
"
```
**Output:**
```
Secret files verified successfully!
```
*Result: Exit 0.*

### Check 3: Compose Configuration Validation (`docker compose config`)
```bash
$ cd claude-sdk-host && docker compose config
```
**Output:**
```yaml
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
      NO_PROXY: localhost,127.0.0.1,172.31.240.20,172.31.240.21
      PYTHONDONTWRITEBYTECODE: "1"
      PYTHONUNBUFFERED: "1"
      http_proxy: http://172.31.240.35:8080
      https_proxy: http://172.31.240.35:8080
      no_proxy: localhost,127.0.0.1,172.31.240.20,172.31.240.21
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
    read_only: true
    restart: unless-stopped
    security_opt:
      - no-new-privileges:true
      - seccomp:deploy/seccomp/seccomp_profile.json
    shm_size: "536870912"
    tmpfs:
      - /tmp:size=512M,mode=1777
      - /tmp/claude-host:size=256M,mode=1777
    user: 1000:1000
    volumes:
      - type: bind
        source: /Users/ivanakimkin/.codex/worktrees/sdk-deploy/My_server/claude-sdk-host/deploy/secrets_example
        target: /run/secrets
        read_only: true
        bind: {}
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
    depends_on:
      sdk-egress-guard:
        condition: service_healthy
        required: true
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
    network_mode: service:sdk-egress-guard
    read_only: true
    restart: unless-stopped
    security_opt:
      - no-new-privileges:true
    tmpfs:
      - /tmp:size=16M,mode=1777
    volumes:
      - type: bind
        source: /Users/ivanakimkin/.codex/worktrees/sdk-deploy/My_server/claude-sdk-host/deploy/secrets_example
        target: /run/secrets
        read_only: true
        bind: {}
  sdk-egress-guard:
    build:
      context: /Users/ivanakimkin/.codex/worktrees/sdk-deploy/My_server/claude-sdk-host
      dockerfile: deploy/netguard/Dockerfile
    cap_add:
      - NET_ADMIN
    cap_drop:
      - ALL
    container_name: claude-sdk-egress-guard
    environment:
      LISTEN_PORT: "8080"
      PROXY_SUBNET: 172.31.240.32/28
      ROLE: egress
      UPSTREAM_IPS: 172.31.240.50
      UPSTREAM_PORTS: "1080"
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
      sdk_proxy:
        aliases:
          - sdk-egress
        ipv4_address: 172.31.240.35
      sdk_upstream:
        aliases:
          - sdk-egress
        ipv4_address: 172.31.240.50
    read_only: true
    restart: unless-stopped
    security_opt:
      - no-new-privileges:true
    tmpfs:
      - /tmp:size=16M,mode=1777
    volumes:
      - type: bind
        source: /Users/ivanakimkin/.codex/worktrees/sdk-deploy/My_server/claude-sdk-host/deploy/hosts
        target: /etc/hosts
        read_only: true
        bind: {}
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
      ROLE: host
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
        aliases:
          - claude-sdk-host
        ipv4_address: 172.31.240.2
      sdk_proxy:
        aliases:
          - claude-sdk-host
        ipv4_address: 172.31.240.34
      sdk_tools:
        aliases:
          - claude-sdk-host
        ipv4_address: 172.31.240.18
    read_only: true
    restart: unless-stopped
    security_opt:
      - no-new-privileges:true
    tmpfs:
      - /tmp:size=16M,mode=1777
    volumes:
      - type: bind
        source: /Users/ivanakimkin/.codex/worktrees/sdk-deploy/My_server/claude-sdk-host/deploy/hosts
        target: /etc/hosts
        read_only: true
        bind: {}
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
```
*Result: Exit 0. Four services properly structured, zero published ports, non-overlapping /28 subnets.*

### Check 4: Debug Overlay Validation
```bash
$ cd claude-sdk-host && docker compose -f docker-compose.yml -f docker-compose.debug.yml config
```
*Result: Exit 0. Loopback port `127.0.0.1:8080:8080` attached only to `sdk-netguard`; no other services modified.*

### Check 5: Isolated Local Smoke Runner (`deploy/scripts/smoke-test.sh`)
```bash
$ cd claude-sdk-host && ./deploy/scripts/smoke-test.sh
```
**Output:**
```
=== Isolated Local Smoke Recipe ===
Working directory: /Users/ivanakimkin/.codex/worktrees/sdk-deploy/My_server/claude-sdk-host
[1/5] Validating shell syntax of all scripts...
  [OK] deploy/netguard/entrypoint.sh
  [OK] deploy/egress/entrypoint.sh
  [OK] deploy/scripts/preflight-check.sh
  [OK] deploy/scripts/provision-auth.sh
  [OK] deploy/scripts/login-maintenance.sh
  [OK] deploy/scripts/generate-peers.sh
  [OK] deploy/scripts/drain-recreate.sh
  [OK] deploy/scripts/smoke-test.sh
  [OK] deploy/scripts/verify-egress.sh
[2/5] Validating JSON schema & syntax of configurations...
  [OK] config.example.json is valid JSON
  [OK] deploy/egress/gost.example.json is valid JSON
  [OK] deploy/seccomp/seccomp_profile.json is valid JSON
[3/5] Testing static peers generation...
Wrote static internal peer mappings to /Users/ivanakimkin/.codex/worktrees/sdk-deploy/My_server/claude-sdk-host/deploy/hosts
  [OK] deploy/hosts successfully generated
[4/5] Testing Compose interpolation with disposable mock secret files...
  [OK] docker compose config passed with isolated mock secrets directory.
[5/5] Verifying Dockerfile layout...
  [OK] claude-sdk-host/Dockerfile found.
  [OK] deploy/netguard/Dockerfile found.
  [OK] deploy/egress/Dockerfile found.

=== Isolated Smoke Recipe PASSED ===
All packaging templates, Compose interpolation, and shell entrypoints validated.
```
*Result: Exit 0. All 9 shell scripts pass `bash -n`, JSON files pass `jq empty`, hosts file generation works, mock secrets interpolation passes.*

---

## 3. Operational Notes for Coordinator

1. **Docker Builds & Execution**:
   Per the brief ownership rules, no Docker daemon or container runs were executed by this lane. The images are ready for coordinator build:
   - `claude-sdk-host` uses `mcr.microsoft.com/playwright/python:v1.64.1-noble` and builds with `pip install --no-cache-dir .`.
   - `claude-sdk-netguard` builds from `deploy/netguard/Dockerfile` (Alpine 3.20 + nftables).
   - `claude-sdk-egress` builds from `deploy/egress/Dockerfile` (Alpine 3.20 + GOST v2.11.5).
2. **Volume Initialization**:
   Before launching the stack, run `./deploy/scripts/provision-auth.sh` to initialize both `claude_sdk_auth` and `claude_sdk_journal` with mode 0700 and UID 1000.
3. **Live Egress Verification**:
   When the disposable stack is brought up on a Docker host with actual upstream network exit, execute `./deploy/scripts/verify-egress.sh` to run the acceptance probes (NET-01 proxy exit, NET-02 direct fail-closed, and NET-03 DNS blocking).
