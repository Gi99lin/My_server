# Server deployment — 2026-10-28

The SDK host is deployed on SSH alias `gigglin-server`, release code `32f19d3` (Linux x86_64). Source is pushed on `codex/claude-sdk-host`; TMS integration is pushed separately on `codex/claude-host-integration`. TMS backend/worker still use `api`: this deployment does not switch them.

## Official personal login

From the owner's computer with the configured SSH alias, run:

```sh
ssh -t gigglin-server /home/gigglin/.config/claude-sdk-host/login.sh
```

The helper opens the bundled official `auth login --claudeai` inside the guarded container. Open the displayed official link and complete the interactive flow in that terminal. Do not send OAuth codes/tokens in chat. Account credentials stay in Docker volume `claude_sdk_auth`; never delete it during restart/update. No API billing credential is used as a fallback.

Until login, `/health/ready` returns503 `reauthentication_required`, while `/health/live` stays healthy. A paid model smoke is intentionally pending owner login. After login, the two-turn smoke can be run from the deployed release with the registered app token file; it prints status/usage only.

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

TMS needs its explicit `claude-host` adapter from the pushed integration branch; changing only its generic OpenAI base URL is insufficient. The prepared override is `deploy/tms/docker-compose.host.yml`, and the workflow is [CUTOVER.md](CUTOVER.md). It connects MCP, private HTTPS credential provider and stand tunnel and preserves the existing built-in deterministic runner.

Pre-provisioned server files for that later switch are under the same operator secret directory: `apps/tms-app.token`, `providers/tms-credentials.token`, and a provider CA certificate. The TLS server certificate/key are in `/home/gigglin/.config/claude-sdk-host/tms-provider-tls`, outside Git. No gateway or TMS backend switch was activated by the SDK-only deployment.

## Operations and acceptance

Operator environment: `/home/gigglin/.config/claude-sdk-host/server.env`. Source releases: `/home/gigglin/services/claude-sdk-host/releases/`. Secrets and environment files are private and outside the checkout. The environment points to the current release; source publication never copies operational secrets.

All four services became healthy after normalizing public source-file permissions. Actual x86_64 Chromium launched with its sandbox enabled and fetched HTTPS through the parent proxy. Application-token/model discovery and anonymous401 checks passed. With both parent endpoints rejected only inside this new egress namespace, the API/worker/browser could not access the Internet directly or through a proxy; DNS/DoT/UDP/QUIC/metadata denial passed and local API remained available. Fault rules were removed and proxied HTTPS recovered. No global kernel/AppArmor setting or existing TMS service was changed.

Use `login.sh` for account access, and source `server.env` from a private administrative shell before `docker compose ps/logs`. Drain before updates, preserve auth/journal volumes and recreate the namespace unit together. Never use `down --volumes` to update or roll back a real account.
