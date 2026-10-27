# Private API contract

Send `Authorization: Bearer <application token>` on every `/v1` request. Registration controls scopes, model aliases, MCP endpoints and credential providers. Each application can access only its own sessions; guessing another session ID returns 404. Tokens, prompts and source belong in bodies/headers, never query strings or logs.

## Completions

`POST /v1/chat/completions`:

```json
{
  "model": "claude-personal-default",
  "messages": [
    {"role": "system", "content": "Answer in Russian."},
    {"role": "user", "content": "Write three checks for password reset."}
  ],
  "stream": false
}
```

`POST /v1/completions` takes `prompt` instead of `messages`. Responses contain the usual `id`, `object`, `created`, `model`, `choices` and `usage`. Streaming uses `data: <JSON>` SSE chunks and `data: [DONE]`; request `stream_options:{"include_usage":true}` for a final usage chunk. Chat deltas use `choices[0].delta.content`; prompt completions use `choices[0].text`.

Supported input fields: `model`, `messages` or `prompt`, `stream`, `stream_options`, and `n:1`. Messages contain text and one of `system`, `user`, `assistant`. Unknown fields return HTTP 400 `unsupported_parameter`. This includes `temperature`, `max_tokens`, `max_completion_tokens`, tools, images, response schemas, seeds and sampling parameters. A fresh official SDK session performs one model turn with no tools. SDK history handling and token limits do not reproduce all OpenAI semantics.

Streaming headers are delayed until provider content/usage or a successful final response is available. Earlier failures return an HTTP error; failures after streaming begins use an SSE error object and do not emit `[DONE]`. Disconnect cancels the worker group. Responses are bounded to 1 MiB of text; queue wait and total request deadlines apply.

Completion usage is `prompt_tokens = input + cache_creation + cache_read`, `completion_tokens = output`. Cached reads are included in prompt totals and identified under `prompt_tokens_details.cached_tokens`. These counters describe SDK observations; `capabilities` advertises that an exact hard token cap is unavailable.

`GET /v1/models` lists permitted aliases. `GET /v1/capabilities` lists supported fields, operator budget caps and session heartbeat/replay behavior. The default agent time cap is 14,400 seconds; requests beyond configured time/token caps return 400 `host_budget_exceeded` before starting a child. Missing official auth state fails as `reauthentication_required`; no API-key fallback exists.

## Agent sessions

`POST /v1/agent-sessions` requires `session:create`. Example execution body; placeholders represent runtime values and are not usable credentials:

```json
{
  "client_request_id": "tms-run-<run UUID>",
  "profile": "tms-execution",
  "model": "claude-personal-default",
  "system_prompt": "<fixed tester instructions>",
  "prompt": "<sanitized task>",
  "timeout_seconds": 1800,
  "token_budget": 2000000,
  "max_turns": 1500,
  "mcp_servers": [{
    "name": "tms-execution",
    "url": "http://10.253.240.20:8000/mcp/tms-execution",
    "token": "<run-bound PrivateToken value>",
    "tools": ["next_point", "start_attempt", "record_step", "finish_attempt", "hand_off"]
  }],
  "browser": {
    "origin": "http://10.253.240.20:8000",
    "credential_key": "ADMIN",
    "credential_provider": "tms",
    "credential_lease": "<single-use opaque lease>"
  }
}
```

The host constructs the `PrivateToken` header. `attach_evidence` on the remote MCP is hidden from the model; the local browser tool calls it with real evidence. MCP URLs must exactly match the operator registry. Only HTTP MCP and the fixed five execution tools are accepted. Clients cannot supply SDK options, stdio servers, commands, environment, working directories or built-in tools.

For `profile:"tms-authoring"`, use `mcp_servers:[]`, `max_turns <=120`, and:

```json
{
  "source_contract": {
    "file_path": "tests/CASE-1.spec.ts",
    "global_case_id": "CASE-1",
    "credential_key": "ADMIN"
  }
}
```

This adds `submit_test`; accepted source is returned only in a `submission` event. Source is limited to 60,000 characters. It must pass secret/literal and test contract checks. TMS independently validates it and runs three deterministic checks in its own runner service. Final assistant prose is never treated as submitted source.

Creation returns 202 and a session object with UUID `id`. Repeating the identical body under the same application and `client_request_id` returns the same receipt with HTTP 200; a different body returns 409. **Retry the original body**, including its original opaque lease and MCP token. Do not issue a new grant and repost the same request ID. Interrupted sessions after a host restart are not restarted.

## Events, acknowledgment and cancellation

| Method | Path | Scope |
| --- | --- | --- |
| GET | `/v1/agent-sessions/{id}` | `session:read` |
| GET | `/v1/agent-sessions/{id}/events` | `session:read` |
| POST | `/v1/agent-sessions/{id}/ack` with `{"seq":N}` | `session:read` |
| POST | `/v1/agent-sessions/{id}/cancel` | `session:cancel` |

SSE envelopes contain `session_id`, monotonically increasing `seq`, `event_id:"<session UUID>:<seq>"`, `timestamp`, `type` and `data`. Types are `started`, `text_delta`, `usage`, `rate_limit`, `submission`, `terminal`. Reconnect with `Last-Event-ID` or `?after=N`. Accounting events are replayable; text and rate-limit notices are live only. Five-second SSE comments are keepalives, not lease renewal.

A `usage` event is a positive delta with `input_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`, `output_tokens` and `budget_tokens`. Agent budgets count **input + cache_creation + output**, excluding cache reads. Persist usage and its deduplication receipt atomically in the consumer before ACK. ACK the last durably processed sequence every five seconds even while idle; no ACK for 30 seconds stops the session. Do not ACK a later event before earlier usage/submission is durable.

Source is held only in process memory until acknowledged, or for 30 seconds after termination. Persist an accepted source in the consuming application before ACK. Missing unacknowledged source after expiration/restart returns HTTP 410 `result_unavailable`; never silently recreate the session. Session status exposes `result_available` where relevant. Replay ordering can have sequence gaps because text is not journaled.

Terminal states include `completed`, `failed`, `cancelled`, `timed_out`, `budget_exceeded`, `consumer_lost`, `interrupted`. `accounting_complete:false` means final provider settlement was not validated; reported counters remain charged. Cancellation stops the entire worker/SDK/browser group within the supervisor's bounded termination path. It cannot undo a stand action already accepted by the application.
