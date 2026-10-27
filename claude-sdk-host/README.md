# Personal Claude SDK host

Private executor for one owner's applications: official Claude Agent SDK, local Playwright Chromium and a small completion API. TMS keeps business state, permanent credentials and deterministic test execution. The executor owns the SDK session, browser and temporary session secrets.

Requirements and acceptance status: [feature documentation](../docs/features/INDEX.md), [approved design](../docs/superpowers/specs/2026-10-27-claude-sdk-host-design.md), [implementation ledger](../docs/plans/2026-10-27-sdk-host-status.md). Public requests and limitations: [API contract](API.md).

## Stack

Python 3.12+, FastAPI, SQLite, official `claude-agent-sdk`, Playwright/Chromium. One application container shares a guarded network namespace. GOST shares a second guarded namespace and forwards through the operator's mandatory SOCKS5/HTTP(S) parent. Only the two small guards have `NET_ADMIN`; application and forwarder drop all capabilities. The application runs as UID 1000 with a read-only root filesystem, private IPC and the official Playwright seccomp profile plus the documented `chroot` allowance for its user-namespace sandbox.

Four dedicated Docker networks separate callers, registered internal peers, the forwarder, and its uplink. Default subnets are four `/28` ranges inside `10.253.240.0/24`; adjust them before deployment if they overlap existing routes. Static addresses and `/etc/hosts` entries are intentional: runtime Docker DNS, direct external TCP, IPv6 and UDP are blocked. External name resolution belongs to the upstream proxy. Do not attach the application to an unrestricted network.

## Configure and build

1. Copy `.env.example` to `.env`; choose non-overlapping networks and the numeric upstream proxy IP/port.
2. Create `HOST_SECRETS_DIR` **outside Git**, with `host-config.json` based on `config.example.json`, `gost-config.json` based on `deploy/egress/gost.example.json`, and the referenced application/provider/idempotency secret files. Generate independent random values of at least 24 characters. Never use example tokens in a running installation.
3. Set ownership of the mounted directory and its children to UID/GID 1000; directories require mode `0700`, secret files `0600`. Provider CA certificates can be public, but tokens and GOST URLs can contain credentials. The directory must be traversable by the container's UID.
4. Register the exact MCP URL, HTTPS credential provider, model aliases, internal peer IPs/ports and bypass names. For TMS tunnel stands, also register its stable Docker relay and leased port range (default `42000-42999`). Attach TMS or its internal TLS gateway to the corresponding Docker networks; the default addresses are examples, not discovery.

```sh
./deploy/scripts/preflight-check.sh
./deploy/scripts/generate-peers.sh /etc/claude-sdk-host/secrets/host-config.json ./deploy/hosts
docker compose build
./deploy/scripts/provision-auth.sh
```

Validate the mounted config without network access:

```sh
docker run --rm --network none --read-only --cap-drop ALL --user 1000:1000 \
  -v /etc/claude-sdk-host/secrets:/run/secrets:ro \
  claude-sdk-host:local check-config
```

For an internal hostname in `proxy_bypass`, pass a third JSON argument to `generate-peers.sh` mapping that exact name to its stable IPv4 address. Missing mappings fail closed; no live DNS lookup is used. Configure the corresponding firewall peer IPs/ports separately.

Image pulls and dependency installation happen in the build environment. Configure that builder's proxy separately; the runtime firewall does not govern the Docker daemon or build network. Runtime performs no package installation.

## Official login and start

```sh
./deploy/scripts/login-maintenance.sh
docker compose up -d
```

The maintenance command uses the SDK's bundled official CLI, the guarded namespace and the restricted auth volume. It does not extract OAuth credentials. Complete the official owner login interactively. Do not inject an API key or an OAuth token into request bodies or the application environment. This repository does not mark live subscription inference or concurrent auth refresh as verified by a synthetic test.

No host port is published by default. Applications reach `http://claude-sdk-host:8080` from the private clients network. The optional `docker-compose.debug.yml` publishes only `127.0.0.1:8080`; private application authentication still applies.

`/health/live` reports process/queue/drain state. `/health/ready` checks the guarded-namespace marker, storage, presence of official auth state and TCP reachability of the fixed local forwarder, and reports `inference_verified:false`; it is not an account, proxy-exit or paid inference probe. Use the acceptance checks below before go-live.

## Operate and verify

```sh
./deploy/scripts/smoke-test.sh       # shell/JSON/Compose validation with fake files
./deploy/scripts/verify-egress.sh    # live network probes on your prepared private stack
./deploy/scripts/drain-recreate.sh  # SIGUSR1, wait for idle, stop and recreate namespace unit
```

Drain rejects new work while allowing accepted queued work to finish. The script waits up to 60 seconds, then stops remaining sessions. Recreate is sequential; active side effects are never replayed automatically. Auth and accounting volumes survive `down`; never use `down -v` for a real installation.

For local source checks:

```sh
python3.12 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/python -m compileall -q src
uvx ruff check src
```

This API/infra project has `ui:false`; acceptance consists of manual HTTP/SSE, SDK-message and disposable-container probes, recorded in the ledger. No browser regression suite is generated for the host. Existing TMS tests remain in the TMS repository. Secrets, prompts, browser content and generated source must never be written into acceptance reports.


## TMS tunnel network attachment

The TMS `testcase-tunnel` service must also join the host's `claude_sdk_tools` network with its registered static address (example `10.253.240.22`). Its existing SSH entry remains a TMS operation; the executor connects only to the selected reverse-forward port inside Docker. An override in the TMS Compose project can attach the existing service:

```yaml
services:
  testcase-tunnel:
    networks:
      default: {}
      claude_sdk_tools:
        ipv4_address: 10.253.240.22
networks:
  claude_sdk_tools:
    external: true
    name: claude_sdk_tools
```

Use the same port range in TMS `STAND_TUNNEL_PORT_RANGE`, the host provider registry and the guard's internal port set. The guard accepts explicit numeric ports/ranges; it never exempts the entire Docker/RFC1918 address space. A saved `http://localhost:3000` stand is routed to the granted Docker relay port while its browser origin stays unchanged. This attachment is documented setup, not a production change performed by this task.
