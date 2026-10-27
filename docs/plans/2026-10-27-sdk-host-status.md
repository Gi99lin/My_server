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

State: preparing contracts and lane worktrees. Coordinator reproduced `agy --version` = 1.4.8 and Gemini 3.8 availability; no application code existed at baseline.

Codex usage at start: 61% of 5-hour window, 57% of weekly window; Antigravity exposes models but no equivalent quota has been established. Do not invent quota figures.

| Lane | Runtime/model | Ownership | State |
| --- | --- | --- | --- |
| runtime | Antigravity / Gemini 3.8 Flash Medium | SDK lifecycle, usage | pending launch |
| browser | Antigravity / Gemini 3.8 Flash Medium | Toolkit, credential grant, evidence, submission | pending launch |
| deploy | Antigravity / Gemini 3.8 Flash Medium | Docker, namespace guard, proxy, runbook | pending launch |

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
