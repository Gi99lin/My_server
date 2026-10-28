# Claude SDK host implementation status

Updated 2026-10-27. Primary branch `codex/claude-sdk-host`, base My_server `5faded3`. Implementation is local; no production server, real Claude account or proxy credentials were changed.

## Current result

The private completion/session API, durable journal, process supervisor, official SDK runner, local browser/credential/submission tools and guarded Docker stack are implemented and manually exercised. A separate TMS integration branch implements generation, agent execution, authoring and scoped one-use HTTPS credentials. Current TMS cycle 83 introduced working origin-preserving stand tunnels while this task was running. Its producer was verified before the fresh browser lane started; the merged tunnel path now passes real Chromium navigation/AJAX and fixed-parent TLS/CONNECT/WebSocket probes.

- Host: `/Users/ivanakimkin/.codex/worktrees/claude-sdk-host/My_server`, `codex/claude-sdk-host`.
- TMS: `/Users/ivanakimkin/Projects/ai-testcase-generator/.worktrees/sdk-host-integration`, `codex/claude-host-integration`.
- Concrete protocol: [API contract](../../claude-sdk-host/API.md); operator steps: [service README](../../claude-sdk-host/README.md).
- TMS implementation `12c39456`, report `a1fc9c61`; subsequently merged canonical cycle83 snapshot `7157955ab5ca` as `58d51dd42cf2`. This is a frozen integration snapshot; canonical development continues independently.

## Decisions and scope

The owner approved the unified executor and asked for Antigravity/Gemini 3.8 developers. `agy models` confirmed `gemini-3.8-flash-medium`; `auto` was unavailable. Initial permission-limited attempts produced no accepted code. The owner then expressly authorized `--dangerously-skip-permissions` for the three prepared My_server worktrees, excluding deployment, secret inspection and server changes. Fresh conversations ran within those boundaries.

Permanent encrypted credentials, the master key, business state, deterministic checks and intentional retries stay in TMS. Only selected session credentials enter the trusted executor worker. The host has no API-key fallback. The existing TMS direct-SDK switch is preserved explicitly; selecting `claude-host` never silently falls back for the owner.

TMS grants and accounting receipts use the existing leased job payload under row locks. Receipt, domain counter and token usage commit together; no new TMS migration was introduced. The original immutable claimed-job ID, owner and claim attempt fence issuance/status, including a same-owner reclaim. Execution is never automatically restarted; a reclaimed authoring job requires explicit manual retry while retaining prior results/usage. A later move to dedicated indexed tables would require migration and receipt backfill.

The host defaults to one child process. Separate finite agent/completion queues are selected fairly. Queue wait consumes the supplied deadline. Auth state and journal volumes have UID1000/mode0700. The read-only application shares the guarded namespace; GOST has its own guarded namespace and can reach only the fixed parent IP/port. No host port is published by default. Default example networks use `10.253.240.0/24` split into four `/28` ranges, because the original example overlapped a real local `172.31.0.0/16` Docker network.

The application uses a digest-pinned official Python base and matching Playwright/Chromium 1.64.1 installed at build time. Pulling the full Playwright image was stopped after slow download; the same browser version was installed by the supported Playwright installer, without a version downgrade. The upstream Playwright seccomp profile is retained. A derived profile additionally permits only `chroot`, required after Chromium enters its user namespace when the initial namespace has no capabilities. Real sandbox startup passed; no `SYS_ADMIN`, privileged mode or `--no-sandbox` was added.

## Lane review and integration corrections

All three first reports required one consolidated fresh-agent correction. Reports were treated as claims and checked against actual code/probes.

| Boundary | Reproduced defect | Correction/evidence |
| --- | --- | --- |
| Runtime | Event UUID confused with provider message ID; truncated streams succeeded | Real SDK dataclass probes prove text/usage deduplication and incomplete-stream failure |
| Runtime | Continuous events postponed grant checks | A 20ms event stream is interrupted by the five-second grant watchdog |
| Runtime/API | Lazy SDK startup committed HTTP200 before provider failure | Advancing the real iterator and delaying headers until content/usage; actual route returns503 for pre-content failure |
| Browser | Startup omitted real Chromium; grant/origin checks incomplete | HTTPS grant/status + real sandboxed browser + actual SDK tool registration passed |
| Browser | Basic credentials could answer a foreign resource challenge | Exact original origin bound; real external401 challenge received no credential header |
| Browser | PNG byte inspection missed visible text echoes | Known secret visible DOM echoes refused before screenshot; typed fields masked |
| Submission | Character/byte limits differed | Accepted 31k Cyrillic source survives supervisor with the same 60,000-character bound |
| Deploy | Browser version mismatch; forwarder uplink unrestricted | Matching browser installed; independent packet filter proves fixed-parent-only egress |
| Deploy | Build paths, secret mounts, false Debug parsing | Real builds/start exposed and resolved these; GOST sees only its own config file |
| TMS | Stale worker could adopt a replacement's lease | Original claim identity/attempt checked under lock; takeover/reclaim probe passed |
| TMS | Cancellation dropped final usage | Bounded final durable replay charges late 7 after prior 5 exactly once; late source ignored |

## Coordinator-reproduced evidence

These are manual/integration probes, not new automated suites. This host is `ui:false`; no browser regression suite was generated. Probe scripts remain outside Git and use synthetic canaries only.

| Surface | Observed result |
| --- | --- |
| Actual ASGI routes plus real child processes | Auth/scopes, cross-app404, strict unsupported fields, sync and streaming completions, idempotency/conflict, usage policy, cancellation, consumer loss, source ACK, body cap passed |
| Real TMS completion client against actual host routes/processes | Sync/SSE text and usage 115 passed; prompt 112 includes 100 cached reads, output 3 |
| SDK message/option classes | Distinct event UUID text dedup; budget 15 excludes 50 cache reads; truncated result/deadline/incomplete counters fail honestly |
| Real non-root Chromium | UID1000, zero initial capabilities, sandbox enabled, original-origin navigation, named secrets, password-field restriction, snapshot/screenshot echo refusal passed |
| Guarded Docker namespaces | Direct IPv4/IPv6, TCP DNS and Docker UDP resolver denied; internal stand reachable; external HTTP crosses synthetic fixed parent |
| Parent outage | Proxy request fails; direct external fallback stays denied |
| Process failure | SIGKILL of actual browser-owning worker cleaned 9 processes including Chromium/driver; no surviving child PIDs |
| Actual Compose API | Authentication/models/metrics work; missing official auth yields readiness503; guard marker read-only; SIGUSR1 drain rejects new work |
| Builds and syntax | Native aarch64 application, guard and GOST images built; Ruff, compile, JSON, shell and Compose smoke passed |
| TMS creator/grant/receipt | Real DB and route probes cover selected credential set, one-use expiry/replay, origin/key/owner/project/job/stand/worker fences, revocation and atomic usage rollback/retry |
| TMS author workflow | Candidate persisted before ACK; 3 checks per attempt;2 intentional attempts use 6 checks, reduce remaining budget and charge 24 once; reclaim launches no new model |

## Existing TMS gates

The initial full snapshot returned 2754 passed, 25 skipped, 1 failed. The failure was the canonical schema checker's hard-coded table set; it failed identically on canonical master without this integration. The owner subsequently merged that fix in cycle83; the refreshed final tree passed the full suite: **2768 passed, 24 skipped, 0 failed** in 869.38 seconds.

After consolidated fixes, the affected existing suite passed 428 tests with 13 skipped; the narrow legacy author/API gate passed 10 with 3 skipped. Frontend lint/types/build and 171 component files passed on the earlier snapshot. Coordinator independently reran legacy generation clients: 32 passed, 1 skipped, and ran the actual cross-repository API/client probe. The fresh cycle 83 frontend gate also passed: **174 component files, 0 failed**, lint (12 warnings, 0 errors), TypeScript and production build. No existing test was skipped, weakened or edited by this task.

## Remaining live release evidence

Official owner login/refresh, real multi-turn model usage, actual configured upstream exit IP, the server's architecture/sandbox and a live SSH tunnel remain go-live checks. Local fake-parent tests establish enforcement, not the owner's final proxy identity. Registration, TLS CA, internal peer addresses and proxy credentials are operator inputs; no secret value belongs in Git. No deployment is implicit in this implementation.

QA Lab host documentation sync was invoked three times. The attempts failed at the external generator with `[Errno 54] Connection reset by peer`; the manual acceptance ledger above remains available. No generated cases are claimed, and no TMS QA Lab sync was run because that repository requires an explicit separate request.

## Cost/volume record

The six approved cycle 1 Antigravity runs report 1408768 input, 409172 output and 36553833 cache-read tokens; their recorded total excludes cache reads (1817940). These are CLI-reported counters, not independently verified billing or quota. Cycle 2 tunnel work is recorded separately below. Logs live outside Git. Codex usage was 61%/57% of the five-hour/weekly windows at start and 64%/73% at the later recorded snapshot. A native TMS agent reached its usage limit after committing its implementation/report; the coordinator inspected the artifacts and continued final integration independently.


## Final tunnel reconciliation

A verified TMS grant now binds access mode and reverse-forward port; changing either invalidates the grant. Redemption returns only `tunnel.port`. The host chooses relay IP and inclusive port range from its operator registry, retaining the original stand origin, Host, cookies and TLS SNI. Localhost stands without valid tunnel metadata fail before Chromium. The browser's local forward proxy routes other external resources through the fixed GOST parent, with exact registered internal bypasses only.

Fresh Antigravity browser cycle 2 produced commit `788ec71`, merged with coordinator fixes as `529f788`. The real HTTP/1.1 browser AJAX probe found a keep-alive stall missed by the socket producer probes. One-request connection closing resolved the reproduced failure. The coordinator additionally verified TLS to an HTTPS parent, external CONNECT, stand WebSocket byte relay, exact origin refusal and listener/task cleanup. The outer packet policy permits only the registered tunnel peer and its explicit port range. Actual SSH transport on the production server remains a release check; the local TCP relay is a synthetic stand transport.

The application image was built from the final source on local aarch64. The final test stack and disposable Postgres are removed after acceptance; no production volume or server service is touched. Native managed archive requests for the three finished lane checkouts were refused by the app because another active task uses them; those checkouts are retained, not removed through a filesystem workaround. All producer commits are preserved in the integration branch.


Cycle 2 Antigravity CLI counters: 272859 input, 85158 output, 7716910 cache reads; reported input/output total 358017. Thinking counter 51695 is reported separately. These are not billing estimates.

Final built-image probes (without a source overlay) passed the tunnel HTTP/1.1 navigation/AJAX path, direct-stand secret/refusal path, and configured synthetic proxy exit with direct IPv4/IPv6/metadata/DNS denial. `docker compose up --wait` reported every test service healthy. Its application healthcheck verifies the real HTTP liveness endpoint. The disposable SDK stack and its synthetic auth/journal/network volumes were removed after these probes.

The coordinator also removed its disposable PostgreSQL project `tms-sdk-host` after the final gates. Other local stacks and the original user files were not modified.


## 2026-10-28 complete TMS cutover preparation

Owner requested alignment with the near-final TMS, without any server installation. Current TMS includes repair mode, runner claim-timeout handling and model-registry fixes. The isolated integration branch was refreshed from cycle 86 code and subsequent documentation-only canonical updates. The current reviewed revision is recorded in `claude-sdk-host/deploy/tms/compatibility.json`.

Repair exposed two previously absent contracts: its browser run borrows the original author job claim, and its rewrite has no parent `agent_run_id`. Native Terra implemented sequential producer/consumer binding, per-run replay fencing, exact case/project/job/claim validation, shared live accounting and budget settlement, preserving existing API/direct-SDK routing. Coordinator-authored real DB/MCP acceptance tests demonstrated browser pass+rewrite (10+7 tokens exactly once), product failure without rewriting, wrong case/project/job denial, source persistence before ACK and deadline cleanup. External cancellation initially left the nested run `running`; the focused correction now terminalizes it, revokes its token and releases only its own stand before propagating cancellation.

Evidence on isolated Postgres5649: 675 affected tests passed (13 skipped), 58 pipeline/library checks passed. After the cancellation correction, all six independent contracts and 39 repair/author seams passed; backend lint and compilation passed. The original grant implementation failed the new producer test under a temporary in-memory baseline substitution. The owner's active E2E o4100 and other DBs were not used or changed.

Host artifacts now include an explicit inactive TMS release override, a private TLS credential gateway, matching default network/model/provider bindings, a read-only source/config gate, rollback instructions, and a local-only login profile with separate retained auth volume. Compose checks prove the override preserves API mode until explicit selection and preserves the built-in runner. The source gate accepts the tested integration and rejects canonical source without host support. The official bundled CLI supports `auth login --claudeai`; live smoke defaults to a no-network/no-token-read dry run and requires `--run` to spend two model turns.

No live model request, real owner login, production switch or server command was performed. A ready Docker-reachable proxy or opaque operator configuration is still needed before the offered real local login/test. Real subscription, proxy-exit and production tunnel evidence remain explicitly unverified. Final preparation matrix and report are in the TMS worktree at `docs/plans/tracks/2026-10-28-sdk-host-cutover.md` and its report.

Focused independent Sol review of TMS `cb527ea35b31` found no high-confidence P1/P2 defect in the changed authorization, lease, replay, shared accounting and cancellation paths. The preparation matrix is closed 8/8; this does not certify live model/proxy/tunnel operation. The only new long-running local resource was isolated Postgres5649, removed after verification; the owner's existing acceptance services were left running.
