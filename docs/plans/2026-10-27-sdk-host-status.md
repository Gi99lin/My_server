# Claude SDK host implementation status

Updated: 2026-10-27. Integration branch: `codex/claude-sdk-host`; base My_server `5faded3`. TMS observed master `1dcf3918` includes track 21. No production changes or new live inference calls.

## Read first

The owner approved the unified executor architecture and requested Antigravity CLI/Gemini 3.8 developers. Follow [the plan](../superpowers/plans/2026-10-27-claude-sdk-host.md) and [the lane charter](2026-10-27-sdk-host-charter.md). Reports are claims until reproduced on the integrated tree.

## Decisions

- Use `gemini-3.8-flash-medium`, confirmed by `agy models`; run in `auto` mode without blanket permission bypass.
- Use native managed worktrees for this repository; original untracked user files remain untouched. Implementation is not a production deployment.
- No new automated suite for this non-UI API/infra project, following the owner's global rule. Manual API/container probes and existing TMS checks are required.
- Local Docker exposes 6,210,170,880 bytes RAM; only one coordinator-owned disposable stack may run.
- Claude SDK developers' direct SDK code in TMS remains available under its existing switch; a new explicit host backend will not silently fall back to it.

## Cycle 1

State: initial Antigravity attempts stopped by normal permission checks before code; explicit owner approval for blanket bypass is pending. Coordinator has implemented independent configuration/authentication/journal producers and manually verified them. Coordinator reproduced `agy --version` = 1.4.8 and Gemini 3.8 availability; no application code existed at baseline.

Codex usage at start: 61% of 5-hour window, 57% of weekly window; Antigravity exposes models but no equivalent quota has been established. Do not invent quota figures.

| Lane | Runtime/model | Ownership | State |
| --- | --- | --- | --- |
| runtime | Antigravity / Gemini 3.8 Flash Medium | SDK lifecycle, usage | initial run stopped: permission not granted |
| browser | Antigravity / Gemini 3.8 Flash Medium | Toolkit, credential grant, evidence, submission | initial run stopped: permission not granted |
| deploy | Antigravity / Gemini 3.8 Flash Medium | Docker, namespace guard, proxy, runbook | initial run stopped: permission not granted |

## Acceptance ledger

| Requirement | Planned surface | Evidence | State |
| --- | --- | --- | --- |
| Personal official SDK auth, no API fallback | runtime/config/auth volume | official CLI smoke and options inspection | pending |
| Completion API and strict parameters | API/runtime | manual actual-route HTTP/SSE probes | pending |
| Browser and named secrets in executor | local tools/grants | manual origin/secret/lease probes, real Chromium | pending |
| Execution/authoring TMS adapters | isolated TMS branch | existing targeted checks plus API contract smoke | pending |
| Usage/replay/budgets/cancellation | meter/journal/supervisor | message-stream and lifecycle probes | pending |
| All external egress via proxy | namespace/proxy | disposable container denial and outage probes | pending |

## Deployment prerequisites

Bind upstream proxy without printing credentials; register application tokens and internal TLS provider certificate; verify official owner login; review any TMS migration; run real model usage and tunnel checks before go-live. None is implicitly satisfied by a deterministic local runner.

## Cycle 1 preliminary evidence

- Managed detached nohup processes did not survive the execution harness; foreground managed sessions preserved CLI lifetime. No application code was produced by those attempts.
- Antigravity reported `--mode auto is not available for this account; continuing in the default mode.` Default mode denied runtime/deploy shell commands and browser source reading. Their result status was SUCCESS despite `denied_actions` and no code; those runs are not accepted as implementation.
- Permission question for `--dangerously-skip-permissions` is pending; no bypass flag has been used. Logs remain outside Git.
- Coordinator manual configuration/auth/journal probe passed: invalid scope denied, cross-application lookup returned 404, request key repeated without duplicate creation, agent budget excluded cache reads, content canary absent from journal projections, restart marked active session interrupted. No automated suite added.
