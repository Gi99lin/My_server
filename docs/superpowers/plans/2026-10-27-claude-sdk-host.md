# Personal Claude SDK Host Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use coordinating-agent-lanes for the owner's selected Antigravity CLI workflow. Execute producer tasks before their consumers.

**Goal:** Implement the private personal-subscription SDK executor, local browser tools, completion/session APIs and fail-closed Docker deployment, with TMS integration through a stable documented contract.

**Architecture:** One long-lived API supervises per-session workers containing official Claude Agent SDK and Chromium. Application authorization, durable usage and cancellation are enforced by the host; TMS keeps business state and permanent encrypted credentials. A separate network namespace guard and existing proxy enforce mandatory upstream routing.

**Tech Stack:** Python 3.12, FastAPI, httpx, SQLite, official claude-agent-sdk, Playwright Chromium, Docker Compose, nftables, GOST or compatible Squid.

**Spec:** [Approved architecture](../specs/2026-10-27-claude-sdk-host-design.md).

## Global Constraints

- Owner approved implementation on 2026-10-27 and explicitly selected Antigravity/Gemini 3.8 lanes; do not ask for another routine plan approval.
- All implementation lives under `claude-sdk-host/`; root README and documentation are coordinator-owned.
- No production deployment, credential extraction, public endpoint, API-key fallback, Docker socket, root Chromium or direct external egress.
- No new automated test suite for this API/infra project under the owner's global instruction. Verify with manual HTTP/SDK/container probes and record exact evidence. Existing TMS tests remain in place and are run when TMS code changes.
- Gemini 3.8 Flash Medium is available in `agy 1.4.8`; the owner explicitly approved `--dangerously-skip-permissions` for the three prepared isolated lanes after `auto` proved unavailable. No server, secret inspection or deployment authority was delegated.
- Local Docker has 5.78 GiB RAM; only coordinator runs a container stack. Lanes use syntax/import and focused process-level probes.
- No secret values in source, examples, prompts, logs or reports.

## Review Focus

1. A proxy setting is removed or upstream fails: IPv4/IPv6/DNS/UDP must remain blocked.
2. A caller reuses another application's ID or supplies a tool/env setting: deny before SDK/browser starts.
3. A TMS grant expires, is revoked, or cannot be checked: stop tools and terminate workers without logging credentials.
4. Repeated usage blocks, reconnects and final settlement: count once, including cache-policy distinction.
5. Cancellation/crash during browser actions or submission delivery: close process groups, preserve accounting and expose unavailable output honestly.

## Frozen files and producer contracts

`claude-sdk-host/src/claude_host/contracts.py` defines `RunSpec`, `RuntimeEvent` and `RunFailure`. It is coordinator-owned. A `RunSpec` is already authorized and contains a monotonic deadline, fixed proxy environment and optional trusted local tool object. No HTTP body maps directly to SDK options.

SDK producer: `SDKRunner(environment: dict[str,str] | None = None, sdk: object | None = None).run(spec: RunSpec) -> AsyncIterator[RuntimeEvent]`; `cancel(session_id: str)` interrupts a running query. `usage.UsageMeter.observe(message)` returns normalized positive usage events and supports final reconciliation. Runtime events use `kind` values `started`, `text_delta`, `usage`, `rate_limit`, `submission`, `terminal` and JSON-serializable `data`.

Local tools producer: `SessionTools.from_payload(browser: dict, provider: dict, execution: dict | None, source_contract: dict | None) -> SessionTools`; `await start()`, `sdk_servers(sdk) -> dict`, `allowed_tool_names() -> list[str]`, `await check_active()`, `await aclose()`, `accepted_source: str | None`. Provider config is operator-registered HTTPS URL, host auth secret file and CA path; browser request contains an opaque redeem token, stand origin and selected credential key. Local tool values never enter SDK subprocess environment.

Deployment producer: Dockerfile builds from `claude-sdk-host/`, installs package and invokes `python -m claude_host`; port 8080; config is `/run/secrets/host-config.json`, auth state `/var/lib/claude-auth`, journal `/var/lib/claude-host`, work `/tmp/claude-host`. CLI supports `serve` (default) and `check-config`; no user-controlled command execution. Networks/firewall allow only configured internal peers and mandatory proxy.

## Task 1 — establish approved contract and isolated lanes

- [x] Save plan, ownership charter, status ledger and immutable producer interfaces; mark the requirement approved from the owner's message.
- [x] Commit only task-owned files. Leave the user's untracked `gost-proxy/` and existing `AGENTS.md` in the original checkout untouched.
- [x] Create three worktrees and run Antigravity CLI with `gemini-3.8-flash-medium`, one committed report per lane, 60-minute hard limit.

## Task 2 — SDK process and usage producer (lane runtime)

**Files:** `src/claude_host/runtime.py`, `usage.py`.

- [x] Implement official SDK query, strict options, text-only delta mapping, constructed child environment, bounded cancellation and result/error settlement.
- [x] Implement message-ID deduplication across assistant/partial/final events; preserve raw four counters and agent-vs-completion budget totals.
- [x] Manually drive representative message streams and cancellation; report exact commands and observed counts. No live paid model calls.
- [x] Commit producer and report. Coordinator checks options and counter semantics before consumers start.

## Task 3 — browser, credentials and submission producer (lane browser)

**Files:** `src/claude_host/browser_tools.py`, `browser.py`, `credentials.py`, `evidence.py`, `submission.py`, `sdk_tools.py`.

- [x] Adapt the owner's existing framework-neutral TMS toolkit, retaining nine operations and origin/secret/evidence rules without importing TMS database/keyring.
- [x] Add one-use HTTPS credential redemption, pre-tool active grant checks, no redirects and fail-closed cleanup.
- [x] Add trusted in-process SDK tools and one accepted source contract; preserve secret and credential-literal refusal.
- [x] Use explicit Chromium proxy, sandbox, private profile and clean process lifecycle. Manually inspect refused secret/origin cases; commit with report.

## Task 4 — Docker network and packaging producer (lane deploy)

**Files:** Dockerfile, `.dockerignore`, Compose, `deploy/`, `.env.example`, `config.example.json`, service README.

- [x] Provide pinned browser/SDK runtime image, non-root/init/private IPC, secret mounts and conservative resource limits.
- [x] Configure mandatory existing proxy chain and independent IPv4/IPv6 namespace policy; no raw Docker DNS fallback, direct route or host port by default.
- [x] Verify Compose interpolation and shell syntax without starting Docker. Commit report. Coordinator alone builds/runs a disposable stack and checks no-fallback behavior.

## Task 5 — API, durable sessions and orchestration (coordinator, after 2–4)

**Files:** package metadata, `config.py`, `auth.py`, `api.py`, `sessions.py`, `journal.py`, `__main__.py`.

- [x] Validate secret-file config, application scopes/models/endpoints and request sizes; reject unsupported fields, arbitrary env/cwd/stdio/tool settings.
- [x] Provide chat and prompt completion APIs/SSE plus models/capabilities; stable schemas and explicit SDK semantic limitations.
- [x] Provide app-scoped session create/read/events/ack/cancel, durable request idempotency/usage, finite queues, deadlines, consumer leases and memory-only source replay.
- [x] Supervise SDK/browser lifecycle, enforce remaining budgets, mark restart interruptions and expose incomplete accounting.
- [x] Run manual HTTP probes through actual ASGI endpoints using a deterministic injected runner; no mocked route implementation and no committed automated suite.

## Task 6 — TMS producer/consumer integration (separate isolated TMS branch)

- [x] Recheck canonical TMS master and run its acceptance preflight before delegation; preserve current direct SDK switch as required by TMS instructions.
- [x] Add an explicit remote-host backend selection, creator guard, remote execution/author adapters and HTTPS credential-grant endpoints with job/stand checks.
- [x] Persist host usage deduplication atomically with TMS counters using existing appropriate state or a reviewed schema change. Never apply a production migration automatically.
- [x] Integrate supported completion fields, leave default OpenAI path intact and make remote-host failures fail closed without direct-SDK fallback.
- [x] Run existing targeted/backend lint/tests and applicable TMS acceptance gates, using isolated databases. Record any migration requiring human review before deployment.

## Task 7 — integration acceptance and handoff

- [x] Review merged code for auth/secrets/concurrency/security; correct concrete findings once, then rerun affected gates.
- [x] Build pinned images; exercise HTTP API, Chromium sandbox, internal stand routing, direct DNS/IPv4/IPv6/UDP denial and upstream failure in a disposable local stack.
- [ ] Release gate: exercise real official SDK message/usage behavior only with an authorized official login; absent login is a clearly recorded go-live prerequisite, not replaced by invented usage evidence.
- [x] Update feature docs/runbooks/status, record commits and manual evidence; provide implementation result without claiming deployment or unsupported real-model checks.


## Final integration outcome

Implementation and local acceptance are complete on the recorded frozen branches. The current TMS snapshot includes cycle 83 and its tunnel transport; the producer/consumer now carry a grant-bound port to an operator-registered relay. Full backend: 2768 passed, 24 skipped, 0 failed. Frontend: 174 component files passed, lint/types/build passed. Actual guarded Chromium, direct-egress denial, synthetic parent outage, sync/SSE/client compatibility, source/accounting replay and worker failure probes passed. Live owner-login/model/server/tunnel/actual-exit checks remain explicit release gates. Documentation generation was attempted but the external QA Lab generator reset the connection. No production action was performed.
