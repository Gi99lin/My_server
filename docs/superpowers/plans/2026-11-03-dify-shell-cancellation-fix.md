# Dify Shell Cancellation Fix Implementation Plan

> **For agentic workers:** Execute inline with executing-plans. The owner approved the proposed targeted patch and testing on 2026-11-03.

**Goal:** Prevent canceled pilot agent runs from leaving newly started shell commands running.

**Architecture:** Patch the shell lifecycle and existing backend SSE keepalive in a separately built Agent Backend image based on pinned 1.18.0. Register shell handles before the long initial wait and preserve output semantics; complete creation and cleanup despite cancellation. Use prompt comment keepalives to wake the existing API client stop callback during silent tools. Preserve the rest of Dify and production TMS routing.

**Tech Stack:** Dify 1.18.0, Python 3.13 asyncio, existing Shellctl protocol, Docker Compose.

**Spec:** `docs/features/dify-pilot.md` (approved cancellation requirements).

## Constraints and review focus

- Build and test in an isolated upstream source worktree, leaving the pinned upstream checkout and live container packages untouched.
- Pin the original source hash and original base image digest. Keep a rollback override and do not alter secrets.
- Prove cancellation before the creation response, cancellation during output waiting, repeated cancellation, and ordinary output/completion using focused tests and real sandbox probes.
- Preserve initial output, offsets, truncation handling, exceptions, and the existing shell suite.
- Deploy only after deterministic checks and a focused review. Drain pilot runs first; TMS and Claude remain unchanged.

## Tasks

- [x] Add focused failing regression coverage and run the existing shell baseline against the unmodified image.
- [x] Implement the minimal cancellation-safe job start and waiting sequence; run focused and relevant existing suites.
- [x] Save the patch and reproducible image build, obtain a focused review, and build a separate candidate image.
- [x] Deploy the candidate with rollback available, rerun live cancellation/inference checks, and synchronize the verified artifacts and results to the repository.

## Progress

Baseline diagnosis is already reproduced: cancel during the long initial wait leaves a delayed file write; cancel after a one-second wait has returned a registered job stops it. Both release 1.18.0 and checked 1.17.1 source register the job after awaiting `commands.run`. No live patch has been applied at plan creation.

## Execution record

- Isolated source worktree: `/home/gigglin/services/dify-pilot/cancel-fix-src`, based on upstream `1.18.0` / `50abea97062110044f15d0e03ccecadd9ccc87ca`. Test dependencies and fixtures are isolated under `/home/gigglin/services/dify-pilot/cancel-fix-tests`; operational evidence stays in the private Dify operator directory.
- Original shell baseline: 41 passing tests; expanded existing baseline: 78 passing tests. New regression cases reproduced orphaned subprocesses. A real SDK schema check caught the requirement that startup poll timeouts be positive; the patch uses 1 ms.
- Direct sandbox probes established that default forced-delete grace can leave descendants active, while explicit zero grace terminated a process tree in 14 ms. The focused review found first cancellation during normal-end cleanup retained that grace; new unit and live cases reproduced it. Layer-exit forced cleanup now always uses zero grace.
- Candidate `r4` passed 94 deterministic and real sandbox checks, including descendants independently confirmed alive before cancellation. It was deployed briefly, but the published API regression still allowed the delayed write. The pilot was immediately rolled back to the original backend image `sha256:80d638d7114bb0fbe954952e37da1f464b61969ff870c0b173963b9f2b91e06e` through the persistent rollback override.
- Architecture audit and independent review found a second defect: the API-side client checks its stop callback only when backend SSE text arrives. A silent tool can therefore defer backend cancellation until the default 15-second heartbeat. The minimal backend-only correction retains comment keepalives but lowers the default interval to 0.5 seconds; business events and replay IDs are unchanged. An idle-stream stop-check regression failed against `r4` before this change.
- Current candidate `r5` includes the shell lifecycle patch and the SSE keepalive change. Patched shell source SHA-256: `2d7d8729bafeda7cd882598819e2adbfdfe15c6055985356376cc8397933c3ac`. Patched SSE source SHA-256: `075cdf842b66d9439cbd89eac4a4cc9e723b546e1c3697914e25b7f20d0cbd12`.
- Final acceptance completed: the expanded suite passed 99 checks. Candidate `r5`, immutable local image ID `sha256:b948cf0ab13f1a52526fc69afc03aa17a91824e6dbb184634cc56d95c3d8d493`, was deployed with no active pilot runs. The published API probe independently confirmed a live descendant, observed 0.5-second comment keepalives from the API container, recorded backend cancellation receipt after 1.455 seconds and cleanup-complete `run_cancelled` after 1.479 seconds, and verified that no delayed child write occurred. Normal inference from the actual TMS container also passed with token usage reported.
- Both deployed source hashes were verified, the runtime user remains `dify`, and the backend has no restart loop. The normal Compose configuration selects the immutable patched image; rollback configuration resolves to the cached original image. Non-secret source, build, tests, deployment override, and evidence summaries are synchronized with the repository. Production TMS routing and the existing Claude host remain unchanged.
