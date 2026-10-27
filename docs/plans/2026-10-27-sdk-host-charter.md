# Claude SDK host lane charter

Owner approved implementation and Antigravity/Gemini 3.8 developers on 2026-10-27. Runtime is `agy 1.4.8`, model `gemini-3.8-flash-medium`, permission mode `auto`; blanket permission bypass was not requested and is not used.

Each lane has its own Git worktree and `codex/` branch, disjoint write paths and a 60-minute wall-clock limit. No lane edits the canonical checkout or another lane. No push, merge, rebase, destructive cleanup, server mutation, credential reads, paid model calls or subagents. The coordinator merges and verifies reports against code. Agents commit their own files and report exact checks; they do not modify shared contracts or broaden a failed check to match their implementation.

Cycle 1 produces independent SDK, browser and deployment components. API consumers and TMS consumers start after their required producers are committed and checked. Only the coordinator starts Docker; local Docker has approximately 5.78 GiB RAM. This is an API/infra project with no UI; the owner's rule prohibits a new automated suite unless explicitly requested. Use manual probes and existing applicable checks. Do not add pytest/browser test files to this project.

Coordinator-owned paths: `docs/`, root README, `claude-sdk-host/pyproject.toml`, package `__init__.py`/`contracts.py` and API/config/auth/journal/supervisor modules. Lane runtime owns only runtime/usage. Lane browser owns only browser/credentials/evidence/submission/SDK-tool modules. Lane deploy owns only Docker/Compose/deploy scripts/config examples/service README. Reports go to distinct `docs/plans/tracks/sdk-host-<lane>-c1-report.md` files.

Logs and launchers stay outside Git at `/Users/ivanakimkin/Projects/My_server-coordination/claude-sdk-host-20261027`. Do not inspect unrelated secrets or account keyrings. If Antigravity eligibility or permission review rejects an action, record the exact error and stop that action; do not change accounts, regions or permission modes to bypass it.
