# Claude SDK host implementation status

Updated: 2026-10-27. Integration branch: `codex/claude-sdk-host`; base My_server `5faded3`. TMS observed master `1dcf3918` includes track 21. No production changes or new live inference calls.

## Read first

The owner approved the unified executor architecture and requested Antigravity CLI/Gemini 3.8 developers. Follow [the plan](../superpowers/plans/2026-10-27-claude-sdk-host.md) and [the lane charter](2026-10-27-sdk-host-charter.md). Reports are claims until reproduced on the integrated tree.

## Decisions

- Use `gemini-3.8-flash-medium`, confirmed by `agy models`; use `--dangerously-skip-permissions` for these isolated lines, explicitly approved by the owner on 2026-10-27 after `auto` proved unavailable.
- Use native managed worktrees for this repository; original untracked user files remain untouched. Implementation is not a production deployment.
- No new automated suite for this non-UI API/infra project, following the owner's global rule. Manual API/container probes and existing TMS checks are required.
- Local Docker exposes 6,210,170,880 bytes RAM; only one coordinator-owned disposable stack may run.
- Claude SDK developers' direct SDK code in TMS remains available under its existing switch; a new explicit host backend will not silently fall back to it.

## Cycle 1

State: initial Antigravity attempts stopped by normal permission checks before code; owner approved the bypass flag for these isolated lines; restarting in fresh CLI conversations. Coordinator has implemented independent configuration/authentication/journal producers and manually verified them. Coordinator reproduced `agy --version` = 1.4.8 and Gemini 3.8 availability; no application code existed at baseline.

Codex usage at start: 61% of 5-hour window, 57% of weekly window; Antigravity exposes models but no equivalent quota has been established. Do not invent quota figures.

| Lane | Runtime/model | Ownership | State |
| --- | --- | --- | --- |
| runtime | Antigravity / Gemini 3.8 Flash Medium | SDK lifecycle, usage | relaunching with owner-approved flag |
| browser | Antigravity / Gemini 3.8 Flash Medium | Toolkit, credential grant, evidence, submission | relaunching with owner-approved flag |
| deploy | Antigravity / Gemini 3.8 Flash Medium | Docker, namespace guard, proxy, runbook | relaunching with owner-approved flag |

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
- The owner subsequently explicitly approved `--dangerously-skip-permissions` for these worktree lines only. Fresh conversations use the flag; the initial denied runs remain unaccepted. Logs remain outside Git.
- Coordinator manual configuration/auth/journal probe passed: invalid scope denied, cross-application lookup returned 404, request key repeated without duplicate creation, agent budget excluded cache reads, content canary absent from journal projections, restart marked active session interrupted. No automated suite added.

## Coordinator integration in progress

All three first lane reports required a consolidated fresh-agent correction. Runtime review found stream UUID/provider ID confusion, false success on truncated streams, and unbounded cleanup. Browser review found incomplete origin/lease validation and missing real browser startup. Deploy review found a mismatched browser image and missing proxy-namespace firewall. Corrections are committed on the producer branches; coordinator integration probes remain required.

TMS integration lives in a separate worktree at `ai-testcase-generator/.worktrees/sdk-host-integration`, branch `codex/claude-host-integration`, base `f1de99aa463e`. Credential grants and accounting receipts use the existing leased platform job payload under row locks, with no new schema or migration. Usage receipts and domain counters commit in one transaction. Changing this choice later would require a schema migration and receipt backfill; current volume is bounded per job.

Existing targeted TMS tests on the coordinator's disposable Postgres port 5639 passed: **54 passed, 1 skipped**. The first attempt failed because enum migrations had not been applied; applying the repository's documented Alembic bootstrap resolved it. This is not evidence for new host adapters yet.

Coordinator added the API request contracts and supervisor against the already verified config/journal producer and frozen runtime interface; actual runtime worker integration is gated on corrected producers below. New source has only been compiled/linted so far, not accepted as working. No live Claude login, inference or production deployment occurred.
