# TMS cutover preparation — 2026-10-28

The templates below prepare an explicit switch and do not activate it by themselves. The owner subsequently authorized deployment and completed login: on 2026-10-29 the server backend/worker were switched to `claude-host` using TMS commit `657025a8`. Real TMS completion and persisted usage, private provider TLS/guards and MCP connectivity passed. Full stand execution/authoring/repair pilot remains pending. Current deployed paths and rollback are recorded in [SERVER.md](SERVER.md).

## Coverage of current TMS

| TMS function | Model path after explicit switch |
| --- | --- |
| gen-01 test cases, gen-02 agent specifications, library generation and testing-request generation | Existing `get_ai_client` → private text completion client |
| Agent execution | One `tms-execution` SDK session per run; original claim/run/stand/MCP token |
| New and update authoring | One `tms-authoring` session per deliberate case attempt |
| Repair failed autotests | Existing author job → case-bound browser run under the original author claim → rewrite only if passed |
| Product failure during repair | Product-defect mark/evidence; no rewrite |
| Deterministic source checks, Git publication, ordinary automation | Existing TMS built-in runner/repository; no extra model in host |
| Testing-request orchestration, permissions and other TMS functions | Existing TMS logic, no new model workflow |

A repair shares its token/time budget across waiting, browser pass, rewrite and checks. Source and accounting commit in TMS before host ACK; retries/replays do not duplicate usage. A reclaimed interrupted model job requires an explicit retry. Direct `claude-sdk` and API routing remain available; an allowlisted owner's selected `claude-host` failure never silently falls back to them.

## Prepare without activation

1. Finish the TMS acceptance run. Use the tested `codex/claude-host-integration` source, reviewed with current TMS; canonical master without that integration does not yet understand this backend.
2. Run the read-only code/config gate (replace the ref with the final reviewed commit recorded in the report):

   ```sh
   python3 deploy/scripts/check-tms-cutover.py \
     --tms-root /path/to/ai-testcase-generator \
     --required-ref TESTED_TMS_COMMIT --config /outside/git/host-config.json
   ```

   This checks committed source/interface markers and the supplied default overlay bindings. It neither runs TMS nor proves live inference. It rejects the old canonical checkout so a misspelled/unsupported switch cannot silently keep using the API backend.
3. Prepare independent application/provider tokens, host config and provider TLS files **outside Git**. Set `TMS_HOST_SECRET_DIR` to the same operator directory as host `HOST_SECRETS_DIR`. The override mounts the exact same `apps/tms-app.token` and `providers/tms-credentials.token` files into TMS; no copying of token values is needed. Never send values in chat or command arguments.
4. Use `deploy/tms/docker-compose.host.yml` as an explicit override of TMS `docker-compose.release.yml`. For the server's `testcase-*` deployment use `docker-compose.testcase-host.yml` with `Caddyfile.testcase` and a reviewed backend image instead. Copy `deploy/tms/cutover.env.example` outside Git and initially set `TMS_LLM_BACKEND` to the currently active backend. Set `TMS_HOST_DEPLOY_DIR` to the absolute `deploy/tms` directory and build `sdk-credentials` before starting it. The derived gateway image removes an unnecessary file capability so it runs with `cap_drop: ALL`; no extra capability is granted. Preserve all existing base networks. The override has no published credential port. `docker compose config` is read-only; `up` changes services.
5. Provider TLS certificate must validate `10.253.240.21`; its trusted CA goes in host `providers/tms-credentials-ca.crt`. Mount server certificate/key at the TLS gateway. UID1000 must read those files, and the TMS backend/worker must read their token files. Keep directories private and verify access using the actual image UIDs.
6. Match network/IP/port bindings to `config.example.json`: backend MCP `.20:8000`, provider TLS `.21:8443`, tunnel `.22:42000-42999`. If changing them, update registry, static mappings, firewall and override together. Host default authoring caps cover 240 minutes / 10 million tokens; execution budgets beyond configured host caps fail explicitly rather than being truncated.

No Claude OAuth/API credential is mounted into TMS. The host auth volume belongs only to the official CLI. The TLS gateway forwards only `/api/v1/internal/claude-host/credentials/*`; other paths return404 and request logging is disabled.

## Optional real local owner test

No real proxy or owner login is bundled. For a small local test, use `config.local.example.json`, one random `apps/local-owner.token` and `idempotency.key`, and your real `gost-config.json` in an operator directory outside Git. The parent listener must be reachable from Docker at the numeric IP/port in `.env.local.example`; localhost on the Mac is not localhost inside a container.

From the `claude-sdk-host` directory, copy `.env.local.example` outside Git and fill the operator paths/parent. Then export that trusted file into the shell:

```sh
set -a
. /outside/git/sdk-local.env
set +a
./deploy/scripts/preflight-check.sh
docker compose build
./deploy/scripts/provision-auth.sh
docker compose up -d sdk-netguard sdk-egress-guard sdk-egress
./deploy/scripts/login-maintenance.sh
docker compose up -d claude-sdk-host
python3 deploy/scripts/live-completion-smoke.py \
  --token-file /outside/git/local-secrets/apps/local-owner.token --run
```

Login explicitly uses official `auth login --claudeai`. The local profile uses port `127.0.0.1:18080` and separate named auth/journal volumes. Follow the official interactive flow; do not extract or paste a permanent OAuth token. The smoke makes exactly two tool-free turns (sync and SSE), checks its fixed public marker and positive usage, and prints only status/counters. Without `--run` it reads no token and performs no network request. It does not touch TMS data or contact a server deployment.

Keep the local auth volume after login; stop with `docker compose down`, **without `--volumes`**. Proxy enforcement and certificate verification remain enabled. Existing owner's E2E stacks/ports are not modified. Live model/refresh and production SSH tunnel behavior remain separate acceptance evidence until actually exercised.

## Explicit activation later

Only after the owner separately orders deployment, build/release TMS from the reviewed integration commit and configure the executor/network/TLS provider. Keep the built-in runner enabled (`--profile runner`, preserving any other required profiles), because writing/repairing tests needs its deterministic checks.

Wait for active TMS model jobs to finish. Change `TMS_LLM_BACKEND` to `claude-host` for **both backend and worker** and recreate them with the explicit override. Check owner generation, one direct/tunnel agent run, ordinary authoring and repair pass/fail paths; compare live usage and cancellation. Do not claim this activation from local scripted tests.

## Rollback

Restore the previously recorded `TMS_LLM_BACKEND` value and recreate backend/worker with the same base/override files after active jobs finish or are explicitly canceled. Keep host auth, journal and TMS results/repository. Never automatically replay an interrupted model query and never delete volumes to roll back routing. This integration introduces no new database migration; canonical TMS migrations still follow its normal reviewed release process.


## Two-parent local proxy operation

The ordered failover input is `deploy/egress/gost.failover.example.json`. Runtime uses pinned GOST3.3.2 native chain-group health checks; keep both parent IPs/ports in the egress allowlist. Auth credentials remain in the operator directory, not `.env`, Git or process arguments. The private local environment can be passed to `deploy/scripts/local-login.sh /absolute/operator/local.env` for the official interactive subscription flow.

The local overlay includes a dedicated access bridge because Docker does not publish an internal-only namespace's port. The bridge does not alter the default-drop egress firewall. Host publication remains exclusively `127.0.0.1:18080`; API authentication is still required. The local-only inbound API CIDR is broad to support Docker Desktop port forwarding, while production's client subnet restriction is unchanged. Direct IPv4/IPv6/metadata/DNS rejection was rechecked after adding the bridge.

Failover was exercised with mock parents and with real provided parents by blocking only the primary in the local namespace. Established-stream failure is not automatic application replay. No server package, TMS routing or remote proxy service was changed.
