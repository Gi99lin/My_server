# Server deployment — 2026-10-29

The SDK host is deployed on SSH alias `gigglin-server`, release code `32f19d3` (Linux x86_64). Source is pushed on `codex/claude-sdk-host`; TMS integration is pushed separately on `codex/claude-host-integration`. The owner completed official login. TMS backend and worker now use `claude-host`, restricted to the sole active owner's UUID, with image `ai-testcase-generator-backend:claude-host-657025a8`.

## Official personal login

From the owner's computer with the configured SSH alias, run:

```sh
ssh -t gigglin-server /home/gigglin/.config/claude-sdk-host/login.sh
```

The helper opens the bundled official `auth login --claudeai` inside the guarded container. Open the displayed official link and complete the interactive flow in that terminal. Do not send OAuth codes/tokens in chat. Account credentials stay in Docker volume `claude_sdk_auth`; never delete it during restart/update. No API billing credential is used as a fallback.

Without login, `/health/ready` returns503 `reauthentication_required`, while `/health/live` stays healthy. After the owner's login, real sync and SSE completion probes passed (616 and 619 tokens). A separate request through TMS's actual owner client passed and persisted a `claude-host` usage record of 615 tokens. These probes print markers/status/counters only.

## API addresses

- Server host-side applications: `http://127.0.0.1:18090/v1`.
- Application containers attached to `claude_sdk_clients`: `http://claude-sdk-host:8080/v1`.
- Owner's workstation over SSH: `ssh -N -L 18091:127.0.0.1:18090 gigglin-server`, then `http://127.0.0.1:18091/v1`. Port18091 avoids the earlier local prototype on18080.

No public ingress or `0.0.0.0` host publication was created. The access bridge enables loopback port publication; namespace firewall still rejects direct Internet access.

## Application authentication

A completion-only application registration `personal-app` is ready. Its token is stored on the server at:

`/home/gigglin/.config/claude-sdk-host/secrets/apps/personal-app.token`

Mount that file read-only into the application's backend (for example `/run/secrets/claude-host.token`) or securely copy it into the owner's private application config directory. Keep values out of Git, browser bundles, command arguments and logs. For several independent apps, create separate host registrations/tokens rather than distribute one shared token broadly.

Python/OpenAI client example **inside an attached application container**:

```python
from pathlib import Path
from openai import OpenAI

client = OpenAI(
    base_url="http://claude-sdk-host:8080/v1",
    api_key=Path("/run/secrets/claude-host.token").read_text().strip(),
    max_retries=0,
)
answer = client.chat.completions.create(
    model="claude-personal-default",
    messages=[{"role": "user", "content": "Reply briefly."}],
)
```

Both `/v1/chat/completions` and `/v1/completions` support text and SSE. Do not send unsupported `temperature`, `max_tokens`, tool or multimodal fields; see [API.md](API.md).

For a Compose application, preserve its existing networks and add external `claude_sdk_clients`. Use an explicit unused client IP starting at `10.253.240.5`; `.2` belongs to the host and `.3/.4` are reserved by the TMS integration plan. A one-off `docker network connect --ip 10.253.240.5 claude_sdk_clients APP_CONTAINER` can test connectivity; keep the attachment in the application's own Compose config for persistence. Do not attach applications to `claude_sdk_proxy` or grant network-admin capabilities.

## TMS-specific connection

TMS uses its explicit `claude-host` adapter from commit `657025a879701bbaa10d283581af6658b0c0fd23`; changing only its generic OpenAI base URL is insufficient. The server's `testcase-*` service names use `deploy/tms/docker-compose.testcase-host.yml` and `Caddyfile.testcase` as the public template. The generic release template remains `docker-compose.host.yml`. Build the credential gateway with `Dockerfile.credentials`: it removes the upstream binary's file capability, allowing non-root execution with all capabilities dropped on port8443.

Application/provider tokens and the trusted provider CA remain in the operator secret directory. The TLS server certificate/key are in `/home/gigglin/.config/claude-sdk-host/tms-provider-tls`, outside Git. SDK-to-provider certificate verification passed; invalid credential leases return403, unrelated gateway paths return404, and unauthenticated execution MCP returns401. The gateway has no published port.

The actual private overlay is `/home/gigglin/.config/claude-sdk-host/tms-active.override.json`. Deployment `.env` selects it with `COMPOSE_FILE`, so normal Compose operations in `/home/gigglin/My_server/ai-testcase-generator` retain the switch. Existing environment, networks, uploads, repository and license mounts were preserved. The tunnel was attached live without restarting it; runner and tunnel retain their original containers. No schema migration was introduced or applied. **Future TMS releases must contain the host integration and update the overlay's backend/worker image pin.**

Real completion is verified. Full browser execution, authoring and repair against a user stand still require a pilot job; protected MCP/TLS connectivity and the earlier integration tests do not substitute for that evidence.

## TMS routing rollback

The original Compose/environment and image manifest are saved privately in `/home/gigglin/.config/claude-sdk-host/tms-before-host`. After draining active model jobs, restore its `.env` to the TMS deployment directory, then run `docker compose up -d --no-deps testcase-backend testcase-worker` there. This restores the original API images/routing. Preserve the Claude auth/journal and all TMS volumes/results; do not delete volumes or automatically replay interrupted model calls.

## Operations and acceptance

Operator environment: `/home/gigglin/.config/claude-sdk-host/server.env`. Source releases: `/home/gigglin/services/claude-sdk-host/releases/`. Secrets and environment files are private and outside the checkout. The environment points to the current release; source publication never copies operational secrets.

All four services became healthy after normalizing public source-file permissions. Actual x86_64 Chromium launched with its sandbox enabled and fetched HTTPS through the parent proxy. Application-token/model discovery and anonymous401 checks passed. With both parent endpoints rejected only inside this new egress namespace, the API/worker/browser could not access the Internet directly or through a proxy; DNS/DoT/UDP/QUIC/metadata denial passed and local API remained available. Fault rules were removed and proxied HTTPS recovered. No global kernel/AppArmor setting or existing TMS service was changed.

Use `login.sh` for account access, and source `server.env` from a private administrative shell before `docker compose ps/logs`. Drain before updates, preserve auth/journal volumes and recreate the namespace unit together. Never use `down --volumes` to update or roll back a real account.
