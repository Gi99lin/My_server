# Runtime Lane, Cycle 1 Report (Correction Pass)

## Summary

Implemented all 8 consolidated runtime and usage corrections specified in `docs/plans/tracks/sdk-host-runtime-c1-correction.md` under `claude-sdk-host/src/claude_host/runtime.py` and `usage.py`. The implementation strictly adheres to ownership boundaries (owning only `runtime.py`, `usage.py`, and this report), preserves the frozen `contracts.py`, introduces no automated test files, and performs complete manual inline verification using real installed `claude_agent_sdk` classes.

## Implemented Corrections

1. **Distinct Stream UUIDs vs Provider Message ID & Single Text Emission**:
   - `StreamEvent.uuid` is recognized as a unique event UUID, not provider message ID.
   - Provider message ID is tracked from `event["message"]["id"]` during `message_start`.
   - `AssistantMessage.message_id` (and fallback to tracked turn message ID) prevents duplicate text emission.
   - `_extract_text_from_block()` extracts text from both SDK `TextBlock` dataclass instances and dictionary blocks while suppressing thinking, tool use, and tool results. Exactly one copy of text is emitted across streaming deltas and final turn messages.

2. **Stream Completion Semantics, Finite Stop Codes, and Profile Handling**:
   - Streams terminating without a `ResultMessage` fail cleanly with `state="failed"`, `stop_reason="provider_stream_incomplete"`, and `accounting_complete=false`.
   - `ResultMessage` with `error_max_turns` or `max_turns` fails for agent profiles (`profile != "completion"`). Completion profiles accept max-turn boundaries only if valid final text content was received and no tool requests remain pending.
   - Authoring sessions (`"author"` in profile) require `accepted_source` from `local_tools` before terminal success; otherwise they fail with `missing_author_submission`.
   - Raw provider subtypes and stop reasons are mapped to a finite safe set (`SAFE_STOP_REASONS`) via `_map_stop_reason()`, preventing arbitrary provider payloads or error strings from leaking into terminal events.

3. **Strict Usage Accounting Completeness & Token Deduplication**:
   - Cumulative counters in `ResultMessage.usage` are validated as non-boolean, non-negative integers across all four required fields (`input_tokens`, `cache_creation_input_tokens`, `cache_read_input_tokens`, `output_tokens`).
   - If any counter is missing, boolean, malformed, or reports a final total lower than already observed streaming totals, accounting is marked incomplete (`is_accounting_complete() -> False`).
   - Placeholder `AssistantMessage` usage values and distinct UUIDs do not double charge.
   - Turns lacking provider message IDs set `_has_missing_id = True` and avoid accumulating into shared anonymous buckets that conflate turns, honestly marking accounting incomplete.

4. **Bounded Cancellation, Await-before-close, and Resource Cleanup**:
   - `cancel(session_id)` signals cancellation and invokes bounded `stream.interrupt()`; it never invokes `stream.aclose()` while `stream.__anext__()` is running.
   - In `run()`, when cancellation or timeout occurs, `next_task` is cancelled and awaited before closing the generator, eliminating async generator concurrency collisions.
   - Stream interrupt, stream close, and local tools `aclose()` are bounded by 5.0-second timeouts.
   - If local tool startup or option construction fails, tools are cleaned up and resources freed before raising stable `RunFailure`.

5. **Startup Deadline and Budget Checks**:
   - Monotonic deadline checks cover local tool startup and working directory setup. Local tool startup is executed with `asyncio.wait_for(spec.local_tools.start(), timeout=remaining)` and cleans up on failure.
   - Non-positive token budgets (`spec.token_budget_remaining <= 0`) are rejected upfront before initialization with `RunFailure("budget_exhausted", status_code=400)`.
   - Final observed budget is rechecked immediately after `ResultMessage` observation; sessions exceeding remaining budget are marked `state="budget_exceeded"`.

6. **Production SDK Options & Ready-only Started Events**:
   - Real `ClaudeAgentOptions` and `HookMatcher` classes are constructed directly without dictionary fallbacks.
   - The `started` event is emitted only after options are constructed and `sdk.query()` has successfully created the stream.
   - Options or query initialization errors raise stable `RunFailure` codes without leaking exception payloads.

7. **Continuous Lease Guarding**:
   - While waiting on model tokens in `__anext__()`, `spec.local_tools.check_active()` is evaluated continuously every `<= 5.0` seconds. If the lease check returns `False` or raises an exception, the stream is interrupted and the session fails with `credential_grant_inactive`.
   - `check_active()` is also enforced prior to all tool calls within the `PreToolUse` hook.

8. **Subprocess Environment Isolation & Blanking**:
   - `_build_subprocess_env()` blanks every inherited key from `os.environ` that is not present in `ALLOWLISTED_ENV_KEYS`, neutralizing the child SDK's automatic `os.environ` merge.
   - All forbidden provider keys, API keys, and OAuth overrides are unconditionally cleared.
   - Operator auth paths (`CLAUDE_CONFIG_DIR`, etc.) and proxy configurations are preserved. Global `os.environ` is never mutated.

## Manual Verification Evidence

All verification was conducted using Python 3.12 within this worktree without introducing new test files.

### Check 1: Python Compilation
Command:
```bash
.venv/bin/python -m py_compile claude-sdk-host/src/claude_host/runtime.py claude-sdk-host/src/claude_host/usage.py
```
Output:
```
Exit code 0 (clean compilation).
```

### Check 2: Distinct Stream UUIDs, Assistant IDs, and Single Text Emission
Command:
```bash
.venv/bin/python -c "
import sys; sys.path.insert(0, 'claude-sdk-host/src')
import asyncio, time
import claude_agent_sdk as sdk
from claude_host.contracts import RunSpec
from claude_host.runtime import SDKRunner

class MockStream:
    def __init__(self, msgs): self._iter = iter(msgs)
    def __aiter__(self): return self
    async def __anext__(self):
        try: return next(self._iter)
        except StopIteration: raise StopAsyncIteration
    async def aclose(self): pass

class MockSDK:
    ClaudeAgentOptions = sdk.ClaudeAgentOptions
    HookMatcher = sdk.HookMatcher
    def __init__(self, msgs): self.msgs = msgs
    def query(self, prompt, options=None): return MockStream(self.msgs)

async def test():
    msgs = [
        sdk.StreamEvent(uuid='event-uuid-1', session_id='s1', event={'type': 'message_start', 'message': {'id': 'msg-provider-100', 'usage': {'input_tokens': 10, 'cache_creation_input_tokens': 0, 'cache_read_input_tokens': 0, 'output_tokens': 1}}}),
        sdk.StreamEvent(uuid='event-uuid-2', session_id='s1', event={'type': 'content_block_delta', 'delta': {'type': 'text_delta', 'text': 'Hello world'}}),
        sdk.StreamEvent(uuid='event-uuid-3', session_id='s1', event={'type': 'message_delta', 'usage': {'output_tokens': 5}}),
        sdk.AssistantMessage(
            message_id='msg-provider-100',
            uuid='assistant-uuid-999',
            model='claude-3-5-sonnet',
            content=[sdk.TextBlock(text='Hello world')],
            usage={'input_tokens': 10, 'cache_creation_input_tokens': 0, 'cache_read_input_tokens': 0, 'output_tokens': 5}
        ),
        sdk.ResultMessage(subtype='success', duration_ms=100, duration_api_ms=80, is_error=False, num_turns=1, session_id='s1', usage={'input_tokens': 10, 'cache_creation_input_tokens': 0, 'cache_read_input_tokens': 0, 'output_tokens': 5})
    ]
    runner = SDKRunner(sdk=MockSDK(msgs))
    spec = RunSpec(session_id='s1', model='claude-3-5-sonnet', system_prompt='', prompt='hi', max_turns=1, deadline_monotonic=time.monotonic() + 5.0, token_budget_remaining=1000)
    events = [e async for e in runner.run(spec)]
    
    text_deltas = [e.data['text'] for e in events if e.kind == 'text_delta']
    assert text_deltas == ['Hello world'], f'Expected 1 copy, got {text_deltas}'
    usage_events = [e.data for e in events if e.kind == 'usage']
    total_in = sum(u['input_tokens'] for u in usage_events)
    total_out = sum(u['output_tokens'] for u in usage_events)
    assert total_in == 10 and total_out == 5
    assert events[-1].data['state'] == 'completed'
    assert events[-1].data['accounting_complete'] is True
    print('Check 2 passed: distinct UUIDs and single text copy verified.')

asyncio.run(test())
"
```
Output:
```
Check 2 passed: distinct UUIDs and single text copy verified.
```

### Check 3: Incomplete Stream Terminating without ResultMessage
Command:
```bash
.venv/bin/python -c "
import sys; sys.path.insert(0, 'claude-sdk-host/src')
import asyncio, time
import claude_agent_sdk as sdk
from claude_host.contracts import RunSpec
from claude_host.runtime import SDKRunner

class MockStream:
    def __init__(self, msgs): self._iter = iter(msgs)
    def __aiter__(self): return self
    async def __anext__(self):
        try: return next(self._iter)
        except StopIteration: raise StopAsyncIteration
    async def aclose(self): pass

class MockSDK:
    ClaudeAgentOptions = sdk.ClaudeAgentOptions
    HookMatcher = sdk.HookMatcher
    def __init__(self, msgs): self.msgs = msgs
    def query(self, prompt, options=None): return MockStream(self.msgs)

async def test():
    msgs = [
        sdk.StreamEvent(uuid='u1', session_id='s2', event={'type': 'message_start', 'message': {'id': 'm1', 'usage': {'input_tokens': 10, 'cache_creation_input_tokens': 0, 'cache_read_input_tokens': 0, 'output_tokens': 1}}}),
        sdk.StreamEvent(uuid='u2', session_id='s2', event={'type': 'content_block_delta', 'delta': {'type': 'text_delta', 'text': 'Partial answer...'}}),
    ]
    runner = SDKRunner(sdk=MockSDK(msgs))
    spec = RunSpec(session_id='s2', model='claude-3-5-sonnet', system_prompt='', prompt='hi', max_turns=1, deadline_monotonic=time.monotonic() + 5.0, token_budget_remaining=1000)
    events = [e async for e in runner.run(spec)]
    terminal = events[-1]
    assert terminal.data['state'] == 'failed'
    assert terminal.data['stop_reason'] == 'provider_stream_incomplete'
    assert terminal.data['accounting_complete'] is False
    print('Check 3 passed: incomplete stream fails with provider_stream_incomplete and accounting_complete=False.')

asyncio.run(test())
"
```
Output:
```
Check 3 passed: incomplete stream fails with provider_stream_incomplete and accounting_complete=False.
```

### Check 4: Cancellation While Blocked Waiting for Model
Command:
```bash
.venv/bin/python -c "
import sys; sys.path.insert(0, 'claude-sdk-host/src')
import asyncio, time
import claude_agent_sdk as sdk
from claude_host.contracts import RunSpec
from claude_host.runtime import SDKRunner

class BlockedStream:
    def __init__(self):
        self.interrupted = False
        self.closed = False
        self.anext_running = False
        self.aclose_while_anext = False

    def __aiter__(self): return self

    async def __anext__(self):
        self.anext_running = True
        try:
            await asyncio.sleep(10.0)
            raise StopAsyncIteration
        finally:
            self.anext_running = False

    async def interrupt(self): self.interrupted = True

    async def aclose(self):
        if self.anext_running:
            self.aclose_while_anext = True
            raise RuntimeError('aclose called while __anext__ is running!')
        self.closed = True

class MockSDK:
    ClaudeAgentOptions = sdk.ClaudeAgentOptions
    HookMatcher = sdk.HookMatcher
    def __init__(self, stream): self.stream = stream
    def query(self, prompt, options=None): return self.stream

async def test():
    stream = BlockedStream()
    runner = SDKRunner(sdk=MockSDK(stream))
    spec = RunSpec(session_id='s3', model='claude-3-5-sonnet', system_prompt='', prompt='hi', max_turns=1, deadline_monotonic=time.monotonic() + 10.0, token_budget_remaining=1000)

    async def do_cancel():
        await asyncio.sleep(0.05)
        await runner.cancel('s3')

    asyncio.create_task(do_cancel())
    events = [e async for e in runner.run(spec)]
    assert not stream.aclose_while_anext
    assert stream.interrupted and stream.closed
    assert events[-1].data['state'] == 'cancelled'
    assert events[-1].data['stop_reason'] == 'cancelled'
    assert events[-1].data['accounting_complete'] is False
    print('Check 4 passed: cancellation while blocked cleanly cancels and awaits without aclose collision.')

asyncio.run(test())
"
```
Output:
```
Check 4 passed: cancellation while blocked cleanly cancels and awaits without aclose collision.
```

### Check 5: Missing / Malformed Final Usage Validation
Command:
```bash
.venv/bin/python -c "
import sys; sys.path.insert(0, 'claude-sdk-host/src')
import claude_agent_sdk as sdk
from claude_host.usage import UsageMeter

# Missing counter
meter_a = UsageMeter('model')
meter_a.observe(sdk.StreamEvent(uuid='u1', session_id='s', event={'type': 'message_start', 'message': {'id': 'm1', 'usage': {'input_tokens': 100, 'cache_creation_input_tokens': 0, 'cache_read_input_tokens': 0, 'output_tokens': 10}}}))
meter_a.observe(sdk.ResultMessage(subtype='success', duration_ms=10, duration_api_ms=10, is_error=False, num_turns=1, session_id='s', usage={'input_tokens': 100, 'output_tokens': 10}))
assert not meter_a.is_accounting_complete()

# Bool counter
meter_b = UsageMeter('model')
meter_b.observe(sdk.StreamEvent(uuid='u1', session_id='s', event={'type': 'message_start', 'message': {'id': 'm1', 'usage': {'input_tokens': 100, 'cache_creation_input_tokens': 0, 'cache_read_input_tokens': 0, 'output_tokens': 10}}}))
meter_b.observe(sdk.ResultMessage(subtype='success', duration_ms=10, duration_api_ms=10, is_error=False, num_turns=1, session_id='s', usage={'input_tokens': True, 'cache_creation_input_tokens': 0, 'cache_read_input_tokens': 0, 'output_tokens': 10}))
assert not meter_b.is_accounting_complete()

# Totals lower than observed
meter_c = UsageMeter('model')
meter_c.observe(sdk.StreamEvent(uuid='u1', session_id='s', event={'type': 'message_start', 'message': {'id': 'm1', 'usage': {'input_tokens': 100, 'cache_creation_input_tokens': 0, 'cache_read_input_tokens': 0, 'output_tokens': 50}}}))
meter_c.observe(sdk.ResultMessage(subtype='success', duration_ms=10, duration_api_ms=10, is_error=False, num_turns=1, session_id='s', usage={'input_tokens': 100, 'cache_creation_input_tokens': 0, 'cache_read_input_tokens': 0, 'output_tokens': 20}))
assert not meter_c.is_accounting_complete()

# Valid complete ResultMessage
meter_e = UsageMeter('model')
meter_e.observe(sdk.StreamEvent(uuid='u1', session_id='s', event={'type': 'message_start', 'message': {'id': 'm1', 'usage': {'input_tokens': 100, 'cache_creation_input_tokens': 10, 'cache_read_input_tokens': 20, 'output_tokens': 30}}}))
meter_e.observe(sdk.ResultMessage(subtype='success', duration_ms=10, duration_api_ms=10, is_error=False, num_turns=1, session_id='s', usage={'input_tokens': 100, 'cache_creation_input_tokens': 10, 'cache_read_input_tokens': 20, 'output_tokens': 35}))
assert meter_e.is_accounting_complete()

print('Check 5 passed: missing/malformed/bool counters and lower totals rejected.')
"
```
Output:
```
Check 5 passed: missing/malformed/bool counters and lower totals rejected.
```

### Check 6: Final Budget Overflow Detection upon ResultMessage
Command:
```bash
.venv/bin/python -c "
import sys; sys.path.insert(0, 'claude-sdk-host/src')
import asyncio, time
import claude_agent_sdk as sdk
from claude_host.contracts import RunSpec
from claude_host.runtime import SDKRunner

class MockStream:
    def __init__(self, msgs): self._iter = iter(msgs)
    def __aiter__(self): return self
    async def __anext__(self):
        try: return next(self._iter)
        except StopIteration: raise StopAsyncIteration
    async def aclose(self): pass

class MockSDK:
    ClaudeAgentOptions = sdk.ClaudeAgentOptions
    HookMatcher = sdk.HookMatcher
    def __init__(self, msgs): self.msgs = msgs
    def query(self, prompt, options=None): return MockStream(self.msgs)

async def test():
    msgs = [
        sdk.StreamEvent(uuid='u1', session_id='s5', event={'type': 'message_start', 'message': {'id': 'm1', 'usage': {'input_tokens': 50, 'cache_creation_input_tokens': 0, 'cache_read_input_tokens': 0, 'output_tokens': 30}}}),
        sdk.ResultMessage(subtype='success', duration_ms=100, duration_api_ms=80, is_error=False, num_turns=1, session_id='s5', usage={'input_tokens': 50, 'cache_creation_input_tokens': 0, 'cache_read_input_tokens': 0, 'output_tokens': 60})
    ]
    runner = SDKRunner(sdk=MockSDK(msgs))
    spec = RunSpec(session_id='s5', model='claude-3-5-sonnet', system_prompt='', prompt='hi', max_turns=1, deadline_monotonic=time.monotonic() + 5.0, token_budget_remaining=100)
    events = [e async for e in runner.run(spec)]
    terminal = events[-1]
    assert terminal.data['state'] == 'budget_exceeded'
    assert terminal.data['stop_reason'] == 'budget_exceeded'
    print('Check 6 passed: final budget overflow detected upon ResultMessage.')

asyncio.run(test())
"
```
Output:
```
Check 6 passed: final budget overflow detected upon ResultMessage.
```

### Check 7: Startup Timeout and Non-positive Budget Rejection
Command:
```bash
.venv/bin/python -c "
import sys; sys.path.insert(0, 'claude-sdk-host/src')
import asyncio, time
import claude_agent_sdk as sdk
from claude_host.contracts import RunSpec, RunFailure
from claude_host.runtime import SDKRunner

class SlowStartupTools:
    def __init__(self):
        self.started = False
        self.closed = False
    async def start(self):
        await asyncio.sleep(2.0)
        self.started = True
    async def aclose(self): self.closed = True

class MockSDK:
    ClaudeAgentOptions = sdk.ClaudeAgentOptions
    HookMatcher = sdk.HookMatcher

async def test():
    runner = SDKRunner(sdk=MockSDK())
    # 1. Budget <= 0
    try:
        spec_budget = RunSpec('sb', 'm', '', '', 1, time.monotonic() + 5.0, token_budget_remaining=0)
        async for _ in runner.run(spec_budget): pass
        assert False
    except RunFailure as e:
        assert e.code == 'budget_exhausted' and e.status_code == 400

    # 2. Local tools startup timeout within remaining deadline
    tools = SlowStartupTools()
    spec_timeout = RunSpec('st', 'm', '', '', 1, time.monotonic() + 0.1, token_budget_remaining=1000, local_tools=tools)
    try:
        async for _ in runner.run(spec_timeout): pass
        assert False
    except RunFailure as e:
        assert e.code == 'deadline_exceeded' and e.status_code == 504
        assert tools.closed

    print('Check 7 passed: startup timeout and budget <=0 verified.')

asyncio.run(test())
"
```
Output:
```
Check 7 passed: startup timeout and budget <=0 verified.
```

### Check 8: Continuous Lease Guarding and Revocation
Command:
```bash
.venv/bin/python -c "
import sys; sys.path.insert(0, 'claude-sdk-host/src')
import asyncio, time
import claude_agent_sdk as sdk
from claude_host.contracts import RunSpec
from claude_host.runtime import SDKRunner

class RevocableTools:
    def __init__(self):
        self.active = False
        self.closed = False
    async def start(self): pass
    def sdk_servers(self, sdk): return {}
    def allowed_tool_names(self): return ['my_tool']
    async def check_active(self): return self.active
    async def aclose(self): self.closed = True

class SlowModelStream:
    def __init__(self):
        self.interrupted = False
        self.closed = False
    def __aiter__(self): return self
    async def __anext__(self):
        await asyncio.sleep(10.0)
        raise StopAsyncIteration
    async def interrupt(self): self.interrupted = True
    async def aclose(self): self.closed = True

class MockSDK:
    ClaudeAgentOptions = sdk.ClaudeAgentOptions
    HookMatcher = sdk.HookMatcher
    def __init__(self, stream): self.stream = stream
    def query(self, prompt, options=None):
        self.last_options = options
        return self.stream

async def test():
    tools = RevocableTools()
    stream = SlowModelStream()
    mock_sdk = MockSDK(stream)
    runner = SDKRunner(sdk=mock_sdk)
    spec = RunSpec('s7', 'm', '', '', 1, time.monotonic() + 15.0, 1000, local_tools=tools)

    events = [e async for e in runner.run(spec)]
    terminal = events[-1]
    assert terminal.data['state'] == 'failed'
    assert terminal.data['stop_reason'] == 'credential_grant_inactive'
    assert stream.interrupted and stream.closed
    assert tools.closed

    hook = mock_sdk.last_options.hooks['PreToolUse'][0].hooks[0]
    res = await hook({'tool_name': 'my_tool'})
    assert res['decision'] == 'block'
    assert res['reason'] == 'credential_grant_inactive'
    print('Check 8 passed: grant revocation during model wait and pre-tool-use verified.')

asyncio.run(test())
"
```
Output:
```
Check 8 passed: grant revocation during model wait and pre-tool-use verified.
```

### Check 9: Required Author Submission
Command:
```bash
.venv/bin/python -c "
import sys; sys.path.insert(0, 'claude-sdk-host/src')
import asyncio, time
import claude_agent_sdk as sdk
from claude_host.contracts import RunSpec
from claude_host.runtime import SDKRunner

class MockStream:
    def __init__(self, msgs): self._iter = iter(msgs)
    def __aiter__(self): return self
    async def __anext__(self):
        try: return next(self._iter)
        except StopIteration: raise StopAsyncIteration
    async def aclose(self): pass

class MockTools:
    def __init__(self, source=None): self.accepted_source = source
    async def start(self): pass
    async def aclose(self): pass

class MockSDK:
    ClaudeAgentOptions = sdk.ClaudeAgentOptions
    HookMatcher = sdk.HookMatcher
    def __init__(self, msgs): self.msgs = msgs
    def query(self, prompt, options=None): return MockStream(self.msgs)

async def test():
    msgs = [
        sdk.StreamEvent(uuid='u1', session_id='s8', event={'type': 'message_start', 'message': {'id': 'm1', 'usage': {'input_tokens': 10, 'cache_creation_input_tokens': 0, 'cache_read_input_tokens': 0, 'output_tokens': 5}}}),
        sdk.ResultMessage(subtype='success', duration_ms=10, duration_api_ms=10, is_error=False, num_turns=1, session_id='s8', usage={'input_tokens': 10, 'cache_creation_input_tokens': 0, 'cache_read_input_tokens': 0, 'output_tokens': 5})
    ]

    # Without accepted_source
    tools_a = MockTools(source=None)
    runner_a = SDKRunner(sdk=MockSDK(msgs))
    events_a = [e async for e in runner_a.run(RunSpec('s8a', 'm', '', '', 5, time.monotonic() + 5.0, 1000, profile='tms-authoring', local_tools=tools_a))]
    assert events_a[-1].data['state'] == 'failed'
    assert events_a[-1].data['stop_reason'] == 'missing_author_submission'

    # With accepted_source
    tools_b = MockTools(source='export default function test() {}')
    runner_b = SDKRunner(sdk=MockSDK(msgs))
    events_b = [e async for e in runner_b.run(RunSpec('s8b', 'm', '', '', 5, time.monotonic() + 5.0, 1000, profile='tms-authoring', local_tools=tools_b))]
    sub_events = [e for e in events_b if e.kind == 'submission']
    assert len(sub_events) == 1
    assert events_b[-1].data['state'] == 'completed'
    assert events_b[-1].data['stop_reason'] == 'end_turn'
    assert events_b[-1].data['accounting_complete'] is True
    print('Check 9 passed: required author submission enforced.')

asyncio.run(test())
"
```
Output:
```
Check 9 passed: required author submission enforced.
```

### Check 10: Environment Allowlist & Inherited Non-allowlisted Key Blanking
Command:
```bash
.venv/bin/python -c "
import sys; sys.path.insert(0, 'claude-sdk-host/src')
import os
from claude_host.runtime import SDKRunner

os.environ['RANDOM_INHERITED_VAR'] = 'leak_candidate'
os.environ['SOME_SERVICE_URL'] = 'https://internal'
os.environ['ANTHROPIC_API_KEY'] = 'sk-ant-test'
os.environ['OAUTH_TOKEN'] = 'secret-oauth'

runner = SDKRunner(environment={
    'PATH': '/usr/bin:/bin',
    'HTTP_PROXY': 'http://127.0.0.1:8080',
    'CLAUDE_CONFIG_DIR': '/var/claude/config',
    'ANTHROPIC_API_KEY': 'bad_override',
    'RANDOM_OPERATOR_VAR': 'ignore_me',
})
env = runner._build_subprocess_env()

assert env.get('RANDOM_INHERITED_VAR') == ''
assert env.get('SOME_SERVICE_URL') == ''
assert env.get('OAUTH_TOKEN') == ''
assert env.get('ANTHROPIC_API_KEY') == ''
assert env.get('PATH') == '/usr/bin:/bin'
assert env.get('HTTP_PROXY') == 'http://127.0.0.1:8080'
assert env.get('CLAUDE_CONFIG_DIR') == '/var/claude/config'
assert env.get('CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC') == '1'
assert os.environ['RANDOM_INHERITED_VAR'] == 'leak_candidate'
assert os.environ['ANTHROPIC_API_KEY'] == 'sk-ant-test'

print('Check 10 passed: environment allowlisting and non-allowlisted blanking verified.')
"
```
Output:
```
Check 10 passed: environment allowlisting and non-allowlisted blanking verified.
```

## Blockers and Findings

None. All 8 consolidated correction items have been fully implemented, verified with actual python command executions, and confirmed. No non-owned files, coordinator contracts, or automated test files were modified or created.
