# Dify pilot

Private evaluation of Dify as an agent platform for TMS and possible future applications. OmniRoute supplies inference; tools execute in Dify or an explicitly integrated execution service. Production TMS still uses its existing route during evaluation.

## Placement and source

- SSH host: `gigglin-agents`, VM 150, `10.10.50.10`.
- Pilot resources: 4 CPU cores, 6144 MiB RAM, 80 GiB root disk.
- Pinned upstream release: `langgenius/dify`, tag `1.18.0`.
- Upstream commit: `50abea97062110044f15d0e03ccecadd9ccc87ca`.
- All 16 service image references are pinned by digest in `images.lock.yml`.
- Agent Backend now uses a separate [cancellation-fix image and override](cancel-fix/README.md); the original base pin remains available for rollback.
- Upstream checkout: `/home/gigglin/services/dify-pilot/upstream`.
- Operator overrides: `/home/gigglin/My_server/dify`.
- Secrets and credentials: `/home/gigglin/.config/dify-pilot`, outside Git.
- Runtime data remains under the upstream Docker deployment's `volumes` directory and named volumes.

## Run

Clone the pinned upstream release, provision its environment from upstream defaults plus `.env.pilot.example` and separately generated server-only secrets, then run:

Generate distinct random values for `SECRET_KEY`, `DB_PASSWORD`, `REDIS_PASSWORD`, `PLUGIN_DAEMON_KEY`, `PLUGIN_DIFY_INNER_API_KEY`, `DIFY_AGENT_API_TOKEN`, and `DIFY_AGENT_LOCAL_SANDBOX_AUTH_TOKEN`. Use the same generated value for `SANDBOX_API_KEY` and `CODE_EXECUTION_API_KEY`, and another shared value for `WEAVIATE_API_KEY` and `WEAVIATE_AUTHENTICATION_APIKEY_ALLOWED_KEYS`. `DIFY_AGENT_SERVER_SECRET_KEY` must encode 32 random bytes as **unpadded base64url**. Keep the resulting environment in `/home/gigglin/.config/dify-pilot/compose.env` with mode `0600`; the upstream Docker directory's `.env` is a symlink to it. Owner console credentials are stored separately as `admin.json` in that private directory.

```bash
cd /home/gigglin/services/dify-pilot/upstream/docker
docker compose -p dify-pilot \
  -f docker-compose.yaml \
  -f /home/gigglin/My_server/dify/images.lock.yml \
  -f /home/gigglin/My_server/dify/compose.pilot.yml up -d
```

Initialize the owner account through the loopback-only console before adding `compose.apps-access.yml` as the final Compose override. That optional override exposes `10.10.50.10:8080` to the existing permitted apps-contour route. No public reverse-proxy entry is created.

The running pilot's private `compose.env` persists `COMPOSE_FILE` with the upstream file, image lock, pilot override, apps-access override, and the cancellation-fix override in that order. Normal `docker compose -p dify-pilot ...` commands from the upstream Docker directory therefore retain the private port bindings and image pins.

Use an SSH forward for workstation access:

```bash
ssh -N -L 18780:127.0.0.1:18080 gigglin-agents
```

Then open `http://127.0.0.1:18780`. Configure the OpenAI-compatible provider with internal URL `http://10.10.60.10:20131/v1`, exact model `cx/gpt-6.1-sol-medium`, and the supplied key from server-only secret storage.

The initialized console is also available over the HomeLab VPN at `http://agents.home.arpa:8080`. Read owner credentials from `/home/gigglin/.config/dify-pilot/admin.json` on `gigglin-agents`; do not paste them into documentation or chat.

## Model and pilot agent

- Provider plugin: `langgenius/openai_api_compatible`, version `0.0.73`, package digest `4cf123ffaa4556f079bed6c47f3a462cc825504b859b183239e74eb19136a4b5`.
- Provider/model ID: `langgenius/openai_api_compatible/openai_api_compatible` / `cx/gpt-6.1-sol-medium`.
- Agent strategy plugin (installed 2026-11-11 for the TMS workflows): `langgenius/agent` `0.0.51`, package digest
  `3c6c32e593b33476cb52f4e5aaf1bf23e1c71b3d07ba64d40690e0dbce3a7e34`, marketplace install with signature verification
  on; strategies `function_calling` and `ReAct`. Its provider meta version is `0.0.2`: Dify's workflow Agent node drops
  MCP tools for strategies whose meta version is `0.0.1` or lower (`core/workflow/nodes/agent/runtime_support.py`,
  `_filter_mcp_type_tool`), so do not downgrade below a release with meta `0.0.2`. Install record:
  `/home/gigglin/.config/dify-pilot/plugin-install-agent.json`.

## TMS workflows (2026-11-11)

Step 2b of `ai-testcase-generator/docs/plans/2026-11-11-dify-harness-design.md`. Built and published by
[`apps/build_tms_apps.py`](apps/build_tms_apps.py) (run on the server from `/home/gigglin/.config/dify-pilot`; it is
idempotent and prints no secrets). Exported definitions, without secrets: [`apps/tms-execution.yml`](apps/tms-execution.yml),
[`apps/tms-authoring.yml`](apps/tms-authoring.yml).

- MCP provider `TMS execution`, server identifier `tms-execution`, URL
  `https://tms.gigglin.tech/mcp/tms-execution-dify/`, header `Authorization: Bearer <bridge token>`. The bridge token is
  generated on `gigglin-apps` (`/home/gigglin/.config/tms-dify-bridge/bridge.token`) and copied server to server into
  `/home/gigglin/.config/dify-pilot/tms-bridge.token` (0600). Dify lists 15 tools.
- `tms-execution` (workflow, app `8d4b4dc0-30ca-4753-bc2f-d1a93c4f55ec`): Start inputs `instruction`, `task`, `run_token`
  → Agent node (`langgenius/agent` `function_calling`, `cx/gpt-6.1-sol-medium`, at most 300 iterations, all 15 tools)
  → End `text`. Every tool's `run_token` is fixed to the Start variable, so the model never sees it.
- `tms-authoring` (workflow, app `a15b123a-09eb-4f48-9727-09e695019532`): Start `instruction`, `task` → one LLM node →
  End `text`. Authoring uses no tools.
- App API keys: `/home/gigglin/.config/dify-pilot/tms-execution.app-key` and `tms-authoring.app-key` (0600). The TMS
  adapters (step 3) need them; they are not in Git.
- The first smoke run on 2026-11-11 reached the model through both apps and got OmniRoute 429: «All codex accounts
  reached configured quota threshold». The `cx/…` aliases share the Codex subscription quota with the Codex coding
  lanes. The owner kept `cx/gpt-6.1-sol-medium` (2026-11-11).
- Smoke after the reset, 2026-11-11 14:15: `tms-authoring` returned `AUTHOR_OK` (31 tokens, 3.4 s); `tms-execution`
  called `next_point` with a made-up `run_token` and returned the TMS refusal «Нужен действующий токен» (1961 tokens,
  6.2 s). The agent log shows `run_token` only in `tool_call_input`, which Dify fills after the model's call; the
  model's messages and tool schemas never contained it.
- **Redis fix, 2026-11-11.** `CELERY_BROKER_URL` in the private `compose.env` carried a different password from
  `REDIS_PASSWORD`, so Celery could not log in (`redis.exceptions.AuthenticationError`): blocking runs worked, streamed
  workflow runs sent only `event: ping` and never started. The Redis password was also exposed in an operator session
  that day, so it was rotated: a new random `REDIS_PASSWORD`, the same value in `CELERY_BROKER_URL`, all services
  recreated with volumes kept (backup of the old file: `compose.env.bak-2026-11-11-redis`, 0600). Checked afterwards: the
  old password gets `WRONGPASS`, the new one `PONG`, no authentication errors in api or worker, and a streamed run goes
  `workflow_started` → nodes → `text_chunk` → `workflow_finished`. When editing `compose.env`, keep the password inside
  `CELERY_BROKER_URL` equal to `REDIS_PASSWORD`.
- Provider credentials use `mode=chat`, `api_type=chat_completions`, `function_calling_type=tool_call`, `stream_function_calling=supported`, and `stream_include_usage=enabled`.
- Pilot model settings use a 128000-token configured context limit, a 4096-token provider output ceiling, and a 2048-token agent output limit. These are pilot configuration values, not claims about the model's maximum capabilities.
- Published agent: `TMS Dify Pilot`, ID `01a1a0b0-66b7-7175-a045-ee18798441c1`.
- App API keys and console cookies remain in the private operator directory, not in this checkout.

## Verify

Use `docker compose ps --all`, the private console, and disposable pilot app API requests. Verify inference and actual tool execution separately, including usage and cancellation where available. Confirm API reachability from `gigglin-apps`; do not infer TMS browser/credential integration from that connectivity alone.

Feature requirements and coverage are in [the feature index](../docs/features/INDEX.md). This repository has `ui: false`; upstream Dify UI checks are bounded operator probes rather than a new application regression suite. Actual results and integration gaps are recorded in [ACCEPTANCE.md](ACCEPTANCE.md).

Stop the pilot with `docker compose ... stop`. Keep its data and do not use `down --volumes` for routine restart or rollback. Retire the existing Claude runtime only after a separately verified replacement.
