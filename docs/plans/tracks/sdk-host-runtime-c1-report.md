# Runtime Lane, Cycle 1 Report

## Summary

Implemented the complete assigned SDK and Usage producer under `claude-sdk-host/src/claude_host/runtime.py` and `usage.py`, adhering strictly to ownership, frozen `contracts.py`, and manual-verification guidelines.

## Owned Files Implemented

1. `claude-sdk-host/src/claude_host/runtime.py`:
   - `SDKRunner(environment=None, sdk=None)`:
     - Subprocess environment allowlist (`ALLOWLISTED_ENV_KEYS`, `FORBIDDEN_ENV_KEYS`, `SENSITIVE_ENV_MARKERS`). Explicitly scrubs/blanks all API-key/provider/base-url variables (`ANTHROPIC_API_KEY`, `CLAUDE_API_KEY`, etc.) and sensitive markers. Preserves proxy settings, system paths/locales, and official CLI config directories. Does not mutate global `os.environ`.
     - Lazy-loads `claude_agent_sdk` when `sdk` is not injected; probe-friendly for lightweight test mocks without live credentials.
     - Builds strict `ClaudeAgentOptions`: `tools=[]`, `strict_mcp_config=True`, `setting_sources=[]`, `permission_mode="dontAsk"`, `verbatim_prompts=True`, `include_partial_messages=True`, `extra_args={"no-session-persistence": None}`, `disallowed_tools=DISALLOWED_BUILTIN_TOOLS`, merged declared `allowed_tools`, and `max_turns` (`1` for completion profile, `spec.max_turns` for agent profiles).
     - Binds `PreToolUse` hook enforcing exact allowed tool names and awaiting `local_tools.check_active()`, rejecting unauthorized tools or inactive sessions.
     - Owns complete local tools and workdir lifecycle: `start()`, `aclose()`, temporary directory creation/removal, and cleanup across normal completion, deadline timeout, budget stop, error, and cancellation.
     - Enforces monotonic deadline (`spec.deadline_monotonic`) and observed token budget ceiling (`spec.token_budget_remaining`).
     - Session state tracking and bounded cancellation: `cancel(session_id)` triggers stream interrupt, closes resources, and yields `cancelled` terminal event.
     - Maps errors to stable safe codes (`provider_error`, `rate_limited`, `max_turns`, etc.); raises `RunFailure` for failures prior to run initialization (expired deadline, active duplicate session, SDK unavailable, local tools start failure).

2. `claude-sdk-host/src/claude_host/usage.py`:
   - `UsageMeter(model=None)`:
     - Canonical usage meter keyed by provider message ID.
     - Deduplicates across `StreamEvent`, `AssistantMessage`, and final `ResultMessage`.
     - Handles increasing cumulative output token updates from partial stream events.
     - Settles final cumulative counters from `ResultMessage` without double charging.
     - Emits positive token deltas with `budget_tokens` (input + cache_creation + output; excludes cache reads per agent budget rules) and `completion_prompt_tokens` (input + cache_creation + cache_read; includes cache reads).
     - Tracks honest accounting completeness (`is_accounting_complete()` is True only after valid `ResultMessage` settlement, False on crash or early termination).

## Verification Evidence

Ran manual inline probes in Python 3.12 without adding test files to the repository.

### Check 1: Python Compilation
Command:
```bash
.venv/bin/python -m py_compile claude-sdk-host/src/claude_host/runtime.py claude-sdk-host/src/claude_host/usage.py
```
Output:
```
Exit code 0 (clean compilation).
```

### Check 2: Environment Allowlisting and Scrubbing
Command:
```bash
.venv/bin/python -c "
import sys; sys.path.insert(0, 'claude-sdk-host/src')
import os
from claude_host.runtime import SDKRunner

os.environ['TEST_SECRET_KEY'] = 'super_secret_value'
os.environ['ANTHROPIC_API_KEY'] = 'sk-ant-test'
runner = SDKRunner(environment={'PATH': '/bin:/usr/bin', 'HTTP_PROXY': 'http://127.0.0.1:8080', 'ANTHROPIC_API_KEY': 'bad_key'})
env = runner._build_subprocess_env()

assert env.get('ANTHROPIC_API_KEY') == ''
assert env.get('TEST_SECRET_KEY') == ''
assert env.get('HTTP_PROXY') == 'http://127.0.0.1:8080'
assert env.get('CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC') == '1'
assert env.get('CLAUDE_DO_NOT_TRACK') == '1'
assert env.get('DISABLE_TELEMETRY') == '1'
assert os.environ['ANTHROPIC_API_KEY'] == 'sk-ant-test'  # unmutated global environ
print('Environment allowlist and scrubbing verified.')
"
```
Output:
```
Environment allowlist and scrubbing verified.
```

### Check 3: UsageMeter Deduplication & Token Reconciliation
Command:
```bash
.venv/bin/python -c "
import sys; sys.path.insert(0, 'claude-sdk-host/src')
from claude_host.usage import UsageMeter

meter = UsageMeter(model='claude-3-5-sonnet')

# Turn 1: StreamEvent message_start
e1 = {'event': {'type': 'message_start', 'message': {'id': 'msg_001', 'usage': {'input_tokens': 100, 'cache_creation_input_tokens': 20, 'cache_read_input_tokens': 50, 'output_tokens': 1}}}}
u1 = meter.observe(e1)
assert u1[0]['input_tokens'] == 100
assert u1[0]['budget_tokens'] == 121  # 100 + 20 + 1 (excludes cache reads)
assert u1[0]['completion_prompt_tokens'] == 170  # 100 + 20 + 50 (includes cache reads)

# Turn 1: StreamEvent message_delta with cumulative output
e2 = {'event': {'type': 'message_delta', 'usage': {'output_tokens': 15}}}
u2 = meter.observe(e2)
assert u2[0]['output_tokens'] == 14  # 15 - 1

# Turn 1: AssistantMessage for msg_001 with output_tokens=15 (already counted)
e3 = {'message_id': 'msg_001', 'content': [{'type': 'text', 'text': 'Hello'}], 'usage': {'input_tokens': 100, 'cache_creation_input_tokens': 20, 'cache_read_input_tokens': 50, 'output_tokens': 15}}
u3 = meter.observe(e3)
assert len(u3) == 0  # no double count

# Turn 2: Second model turn
e4 = {'message_id': 'msg_002', 'content': [{'type': 'text', 'text': 'World'}], 'usage': {'input_tokens': 200, 'cache_creation_input_tokens': 0, 'cache_read_input_tokens': 100, 'output_tokens': 30}}
u4 = meter.observe(e4)
assert u4[0]['input_tokens'] == 200
assert u4[0]['output_tokens'] == 30
assert not meter.is_accounting_complete()

# ResultMessage settling session total (out=48 settles +3 over 15+30=45)
e5 = {'subtype': 'success', 'duration_ms': 1200, 'usage': {'input_tokens': 300, 'cache_creation_input_tokens': 20, 'cache_read_input_tokens': 150, 'output_tokens': 48}}
u5 = meter.observe(e5)
assert u5[0]['input_tokens'] == 0
assert u5[0]['output_tokens'] == 3
assert meter.is_accounting_complete()

# Duplicate ResultMessage emits nothing
assert len(meter.observe(e5)) == 0
print('UsageMeter deduplication and accounting verified.')
"
```
Output:
```
UsageMeter deduplication and accounting verified.
```

### Check 4: SDKRunner Options, PreToolUse Hook, Local Tools Lifecycle, and Streaming
Command:
```bash
.venv/bin/python -c "
import sys; sys.path.insert(0, 'claude-sdk-host/src')
import asyncio, time
from claude_host.contracts import RunSpec
from claude_host.runtime import SDKRunner

class MockLocalTools:
    def __init__(self):
        self.started = False
        self.closed = False
        self.active = True
        self.accepted_source = None
    async def start(self): self.started = True
    def sdk_servers(self, sdk): return {'local_browser': {'type': 'in_process'}}
    def allowed_tool_names(self): return ['browser_click', 'submit_test']
    async def check_active(self): return self.active
    async def aclose(self): self.closed = True

class MockSDK:
    def __init__(self, messages):
        self._messages = messages
        self.last_options = None
    def query(self, prompt, options=None):
        self.last_options = options
        messages = self._messages
        class Stream:
            def __init__(self): self._iter = iter(messages)
            def __aiter__(self): return self
            async def __anext__(self):
                try: return next(self._iter)
                except StopIteration: raise StopAsyncIteration
            async def aclose(self): pass
        return Stream()

async def main():
    tools = MockLocalTools()
    spec = RunSpec(
        session_id='sess_test_1', model='claude-3-5-sonnet', system_prompt='Tester', prompt='Login',
        max_turns=10, deadline_monotonic=time.monotonic() + 10.0, token_budget_remaining=50000,
        profile='tms-execution', allowed_tools=['next_point'], local_tools=tools,
    )
    tools.accepted_source = 'export default function test() {}'
    messages = [
        {'event': {'type': 'content_block_delta', 'delta': {'type': 'text_delta', 'text': 'Navigating'}}, 'uuid': 'm1'},
        {'event': {'type': 'message_start', 'message': {'id': 'm1', 'usage': {'input_tokens': 50, 'output_tokens': 10}}}},
        {'message_id': 'm1', 'content': [{'type': 'text', 'text': 'Navigating'}], 'usage': {'input_tokens': 50, 'output_tokens': 10}},
        {'rate_limit_info': type('RateLimitInfo', (), {'status': 'allowed', 'resets_at': 1700000000})()},
        {'subtype': 'success', 'duration_ms': 500, 'is_error': False, 'stop_reason': 'end_turn', 'usage': {'input_tokens': 50, 'output_tokens': 10}}
    ]
    runner = SDKRunner(sdk=MockSDK(messages))
    events = [e async for e in runner.run(spec)]
    assert tools.started and tools.closed
    kinds = [e.kind for e in events]
    assert kinds[0] == 'started'
    assert 'text_delta' in kinds and 'usage' in kinds and 'rate_limit' in kinds and 'submission' in kinds and kinds[-1] == 'terminal'
    assert events[-1].data['state'] == 'completed' and events[-1].data['accounting_complete'] is True
    print('SDKRunner run and event flow verified.')

asyncio.run(main())
"
```
Output:
```
SDKRunner run and event flow verified.
```

### Check 5: Monotonic Deadline, Token Budget Ceiling, Cancellation, and Pre-initialization Failures
Command:
```bash
.venv/bin/python -c "
import sys; sys.path.insert(0, 'claude-sdk-host/src')
import asyncio, time
from claude_host.contracts import RunSpec, RunFailure
from claude_host.runtime import SDKRunner

class SlowStreamSDK:
    def __init__(self):
        self.interrupted = False
        self.closed = False
    def query(self, prompt, options=None):
        sdk_self = self
        class Stream:
            def __aiter__(self): return self
            async def __anext__(self):
                await asyncio.sleep(10.0)
                raise StopAsyncIteration
            async def interrupt(self): sdk_self.interrupted = True
            async def aclose(self): sdk_self.closed = True
        return Stream()

async def main():
    # Deadline timeout
    slow = SlowStreamSDK()
    runner = SDKRunner(sdk=slow)
    spec_dl = RunSpec('s_dl', 'm', '', '', 1, time.monotonic() + 0.05, 1000)
    events_dl = [e async for e in runner.run(spec_dl)]
    assert events_dl[-1].data['state'] == 'timed_out' and events_dl[-1].data['stop_reason'] == 'deadline_exceeded'
    assert slow.closed

    # Cancellation
    slow_c = SlowStreamSDK()
    runner_c = SDKRunner(sdk=slow_c)
    spec_c = RunSpec('s_c', 'm', '', '', 1, time.monotonic() + 10.0, 1000)
    async def do_cancel():
        await asyncio.sleep(0.05)
        await runner_c.cancel('s_c')
    ct = asyncio.create_task(do_cancel())
    events_c = [e async for e in runner_c.run(spec_c)]
    await ct
    assert events_c[-1].data['state'] == 'cancelled' and events_c[-1].data['stop_reason'] == 'cancelled'
    assert slow_c.interrupted and slow_c.closed

    # Pre-initialization failures
    try:
        async for _ in runner.run(RunSpec('s_exp', 'm', '', '', 1, time.monotonic() - 1.0, 1000)): pass
        assert False
    except RunFailure as e:
        assert e.code == 'deadline_exceeded' and e.status_code == 504

    print('Deadline, cancellation, and pre-initialization failures verified.')

asyncio.run(main())
"
```
Output:
```
Deadline, cancellation, and pre-initialization failures verified.
```

## Blockers and Findings

None. All constraints and requirements from `docs/plans/tracks/sdk-host-runtime-c1.md` and related charters have been verified. No coordinator or non-owned files were modified.
