---
feature: personal-claude-sdk-host
title: Personal Claude SDK sessions and completions
status: approved
source: owner approved implementation with Antigravity/Gemini 3.8 on 2026-10-27 after unified-executor design and prior-art review
entry_points: /v1/chat/completions, /v1/completions, /v1/agent-sessions
related: []
code_paths: claude-sdk-host
updated: 2026-10-27
---

# Personal Claude SDK sessions and completions

## Purpose

The owner connects personally used applications to one private Claude Agent SDK service. Applications can request a text answer or start an agent session with their own tools. The owner signs in through the official Claude flow using a personal subscription.

## Actors and permissions

- Only registered owner-controlled application backends can call the service with their private application token.
- An application can inspect and cancel only its own sessions.
- TMS checks the actual run/job creator against its SDK allowlist before opening an SDK session or browser.
- Subscription credentials and stand secrets never appear in application responses or model prompts.

## Entry points

- Applications request chat-shaped or string-prompt completions, with optional streaming.
- TMS starts an execution session or one authoring attempt, observes usage and requests cancellation.
- The owner checks service readiness and completes official reauthentication when needed.

## Main flow

1. An authorized application submits text messages or a string prompt. It receives one text answer in a completion response, or ordered text chunks followed by usage when requested.
2. TMS authorizes the creator, creates a scoped credential lease and sends an agent-session request with remaining budgets and its execution MCP configuration.
3. The service returns a session identifier. TMS observes usage while the agent calls only its approved tools.
4. The executor redeems the selected credential lease over authenticated HTTPS and starts its own isolated browser. It enters named stand credentials without showing their values to the model and attaches evidence through the hidden upload capability. Permanent encrypted credentials and the master key stay in TMS.
5. An authoring attempt returns one source file through its trusted local submission tool. TMS validates the source again; it must use environment variables for stand address and credentials. Three deterministic checks and any retries are performed by TMS.
6. Completion, cancellation or a limit ends the session and closes its resources. TMS retains its own domain results.

## Alternative flows

- Repair first runs the case through execution, then invokes authoring if the case passes. This is planned TMS behavior; the host supplies the same two session types.
- Reconnecting to an agent event stream replays unacknowledged accounting without rerunning tools. Text chunks are live-only.
- A repeated start request with the same application request identifier returns the original session; a changed request under that identifier returns 409.

## Validation and business rules

- Every connection outside registered attached Docker peers goes through the configured proxy. Turning off proxy variables or losing the proxy never permits direct external access.
- SDK and browser external traffic share the executor's enforced proxy boundary; registered internal stand/tunnel traffic remains direct.
- A tunneled stand keeps its saved browser origin, including a localhost origin. Redemption supplies only its bound tunnel port; the operator chooses the registered Docker relay and allowed port range. Missing or changed tunnel mapping fails closed before the browser starts. External resources continue through the mandatory proxy.
- Credential leases are single-use, bound to the application/job/attempt and exact stand origin, and must be redeemed within 60 seconds. Values remain only in trusted session-tool memory; they are never placed in model messages or the CLI environment.
- Completion sessions have one model turn and no tools. Unsupported options, including `temperature`, return 400 with `unsupported_parameter`.
- Agent execution uses one SDK session per run; authoring uses one per case attempt. Remaining authoring job budgets span cases and retries.
- Agent budget accounting includes newly processed input, cache writes and output, excluding cache reads. Completion usage also includes cache reads.
- Observed token limits stop further work once reached; an in-flight response may overshoot. Incomplete accounting after a crash is identified explicitly.
- Applications acknowledge/renew the agent consumer lease every 5 seconds; 30 seconds without renewal stops work.
- Default completion timeout is 300 seconds. Actual agent limits are supplied by TMS; examples are 30 minutes / 2,000,000 tokens for execution and 20 minutes / 1,000,000 tokens for an authoring job. Queue time consumes the supplied remaining deadline and never extends the job clock.

## Errors and edge cases

- Missing or invalid application token returns 401; an authenticated caller without the required scope receives 403.
- An unknown, expired or another application's session is inaccessible; no session details are disclosed.
- Unsupported completion parameter returns 400; unregistered tool endpoint or disallowed tool configuration is rejected before starting an SDK child.
- Known subscription exhaustion or full capacity returns 429; proxy/provider unavailability returns 503 before streaming; completion deadline returns 504 before streaming.
- A provider failure after streaming begins produces an error frame and closes the stream.
- Owner sign-in expiry reports `reauthentication_required`; it never switches to API-key billing.
- Host restart ends active sessions as `interrupted`; it does not replay side-effecting tools.
- Cancellation or worker failure closes executor-owned Chromium and SDK processes. TMS revokes credential leases if the job ends.
- An unacknowledged authoring source can be redelivered from bounded memory for up to 30 seconds after terminal delivery. After restart or buffer expiry, `result_unavailable` requires TMS to create a new attempt; the host never silently reruns it.

## Data

- Inputs: text/history, model alias, application request identifier, tool endpoint credentials and remaining budgets.
- Outputs: text completion, session identifier, ordered usage and terminal state; TMS stores evidence and accepted source itself.
- Retain acknowledged accounting and idempotency metadata for 7 days; preserve unacknowledged accounting until acknowledged or explicit operator cleanup. Do not retain prompts, raw source, tool credentials, conversation transcripts or text chunks in the host journal.

## Design and approval

The owner approved implementation on 2026-10-27. The architecture and verification checklist are in [the host design](../superpowers/specs/2026-10-27-claude-sdk-host-design.md), with source comparisons in [the prior-art review](../superpowers/specs/2026-10-27-claude-sdk-prior-art.md). This non-UI project's generated cases remain a manual checklist.
