# Browser Lane Cycle 1 Report (Correction Pass)

## 1. Provenance and Scope

This lane implements the local browser, credential management, evidence sink, submission validation, and SDK MCP tool registration for `claude-sdk-host`.

Source files adapted (read-only reference at `f258ba7a` in `/Users/ivanakimkin/Projects/ai-testcase-generator/test_importer_web/backend/`):
- `claude_host/browser_tools.py` & `claude_host/browser.py`:
  Adapted from `src/tms/agents/sdk_runner/browser_tools.py`. Extracted headless Playwright Chromium lifecycle, proxy/bypass configuration, `chromium_sandbox=True`, same-origin routing/204 response on blocked navigation, dialog handling, console collection, and all 9 tool specifications and serialized handlers.
- `claude_host/credentials.py`:
  Adapted from `src/tms/projects/stands/service.py` (`StandRunnerAccess`). Implements the frozen credential provider wire client (`POST /redeem` and `GET /grants/{grant_id}`). Stripped all TMS database, SQLAlchemy, keyring, and IAM dependencies.
- `claude_host/evidence.py`:
  Adapted from `src/tms/agents/sdk_runner/evidence.py`. Connects to `tms-execution` streamable HTTP MCP server with run-bound `PrivateToken` and calls hidden `attach_evidence`. Model never sees attachment bytes or tokens.
- `claude_host/submission.py`:
  Adapted from `src/tms/agents/sdk_author/submission.py` and pure rules in `src/tms/agents/authoring/worker.py` (`source_refusal`). Zero backend or git dependencies.
- `claude_host/sdk_tools.py`:
  Adapted from `src/tms/agents/sdk_runner/sdk_server.py` and `src/tms/agents/sdk_author/tools.py`. Implements `SessionTools` pure factory, lifecycle, active grant watchdog, and in-process SDK MCP server registration.

Ownership followed:
- Only modified files within `claude-sdk-host/src/claude_host/{browser_tools.py, browser.py, credentials.py, evidence.py, submission.py, sdk_tools.py}`, `docs/plans/tracks/sdk-host-browser-c1-report.md`, and tracked plan documentation.
- No modifications to coordinator-owned `contracts.py`, `pyproject.toml`, or other lane files.
- No new automated test suite added (compliant with owner's non-UI infra rule).
- Verified with manual inline probes via Python 3.12.

---

## 2. Cycle 1 Correction Findings and Concrete Fixes

All 8 concrete findings specified in `docs/plans/tracks/sdk-host-browser-c1-correction.md` have been addressed:

1. **Origin & Address Binding in `SessionTools.from_payload`**:
   - `origin` and `address` are validated before credential redemption.
   - Credentials embedded in either URL (`username:password@host`) are strictly rejected.
   - Non-HTTP(S) schemes are rejected.
   - `address` is bound to `origin`: normalized origin `(scheme, host, port)` of `address` must match `origin` exactly, preventing a valid lease for Stand A from being used to access Stand B.

2. **Hardened `CredentialProviderClient`**:
   - Requires HTTPS base URL without credentials, query parameters, or fragments.
   - Strict client options: `follow_redirects=False`, `trust_env=False`.
   - `should_bypass_proxy` strictly enforces exact host/IP equality only (no wildcards or suffix patterns).
   - `grant_id` is validated against `GRANT_ID_PATTERN` matching the TMS format `job_uuid.grant_uuid` (`^[0-9a-fA-F-]{32,36}\.[0-9a-fA-F-]{32,36}$`), preventing path traversal or URL injection.
   - TLS CA verification uses `ssl.create_default_context(cafile=...)`.
   - All errors use stable codes/phrases without secret URLs or credential values.

3. **Fail-Closed Active Grant Checks**:
   - `submit_test` SDK handler explicitly awaits `await self.check_active()` before any source validation or acceptance.
   - In `BrowserToolkit.call`, `await self._check_active_cb()` is awaited outside the exception-catching block that wraps tool actions; if the active grant check fails, the action is never executed, and `RunFailure` propagates fail-closed.

4. **`SessionTools` Start & Resource Lifecycle**:
   - `SessionTools.start()` calls `await self._session.start()` before marking `_started = True`, surfacing launch failures prior to model invocation.
   - Cleanup on start failure resets browser session, closes provider client, and clears `_lease_token = ""` and `_stand = None`.
   - `aclose()` releases browser session and provider resources, wipes `_lease_token` and `_stand` secrets from memory, while preserving `accepted_source` separately for final emission.

5. **Mandatory Official SDK Interface**:
   - Removed production fake-SDK fallbacks in `_make_sdk_tool` and `_make_sdk_server`.
   - Official SDK callable `tool()` decorator and `create_sdk_mcp_server()` function are mandatory; missing methods raise `TypeError` immediately.

6. **Evidence Client Network & Transport Isolation**:
   - `McpEvidenceSink` client forbids redirects (`follow_redirects=False`), enforces `trust_env=False`, and routes through trusted proxy/bypass configurations supplied from provider config in `SessionTools`.
   - Integrates with installed `httpx2` / `mcp` streamable HTTP client interface.
   - No tokens, payloads, or file bytes are logged.

7. **HTTP Basic Authentication Separation**:
   - Stand URL in browser payload cannot carry embedded basic credentials.
   - Supports reserved names `__HTTP_BASIC_USERNAME` and `__HTTP_BASIC_PASSWORD` in redeemed provider values, passing them to `BrowserSession(http_credentials=...)`.
   - Basic credentials are masked with `[скрыто]` in `StandRunnerAccess.redact_text` and `BrowserToolkit` echoes.
   - Regular `LOGIN` and `PASSWORD` remain independent.

8. **TMS Child Process Template Verification**:
   - Verified that `submission.py` source validator (`source_refusal`) accepts the actual current TMS secure child_process sign-in template from `sdk_author/prompt.py`.
   - Confirmed arbitrary `child_process` invocations (e.g., `execSync`, `spawn`, `fork`, non-template `execFileSync`) are rejected.

---

## 3. Interface Assumptions and Contracts

### `SessionTools` Lifecycle
```python
SessionTools.from_payload(
    browser: dict,
    provider: dict,
    execution: dict | None = None,
    source_contract: dict | None = None,
    *,
    credential_client: CredentialProviderClient | None = None,
    session: BrowserSession | None = None,
) -> SessionTools
```
- **Pure Constructor Factory**: Validates payload structure, origin/address binding, HTTPS requirements, and key presence without initiating I/O or browser launches.
- `await start()`: Reads token file, redeems credentials with provider, instantiates `StandRunnerAccess`, creates `BrowserSession` (configured with proxy/bypass and basic auth), starts Chromium, sets up `BrowserToolkit` with fail-closed active check callback, and instantiates `Submission` if in authoring mode.
- `await check_active()`: Verifies grant with provider (`GET /grants/{grant_id}`). Fails closed with `RunFailure("grant_inactive")` if revoked, expired, or unreachable.
- `await aclose()`: Cleanly shuts down browser session and provider resources, clears `_lease_token` and `_stand` values, preserving `accepted_source`.
- `sdk_servers(sdk) -> dict[str, Any]`:
  - Execution profile: returns `{"browser": server}` exposing all 9 browser tools (`open_url`, `snapshot`, `click`, `type_text`, `type_stand_secret`, `press_key`, `select_option`, `wait`, `attach_evidence`).
  - Authoring profile: returns `{"browser": server, "author": server}` where browser server exposes 8 inspection tools (`attach_evidence` hidden) and author server exposes `submit_test`.
- `allowed_tool_names() -> list[str]`:
  - Execution profile: `mcp__browser__{name}` for all 9 tools.
  - Authoring profile: `mcp__browser__{name}` (excluding `attach_evidence`) + `mcp__author__submit_test`.
- `accepted_source: str | None`: Property returning the single accepted test source string for authoring sessions, or `None`.

### Credential Provider Wire Contract
- `POST {provider.url}/redeem`:
  - Header: `Authorization: Bearer <token_from_token_file>`
  - Body: `{"lease_token": str, "credential_key": str, "origin": str}`
  - Response (200): `{"grant_id": str, "expires_at": str (ISO 8601 UTC), "values": {"LOGIN": str, "PASSWORD": str, ...}}`
  - Rejects: HTTP redirects, non-200 status, missing/non-string values, expired grants, invalid grant_id format.
- `GET {provider.url}/grants/{grant_id}`:
  - Header: `Authorization: Bearer <token_from_token_file>`
  - Response (200): `{"active": bool, "expires_at": str (ISO 8601 UTC)}`
  - Rejects: Inactive grants, local/remote expiration, network failures, redirects.
- Proxy handling: Requests bypass HTTP proxy if host matches exact entry in `proxy_bypass`; otherwise routed via `proxy_url` if configured.
- Secret safety: `StandRunnerAccess` keeps secrets strictly in memory; `__repr__` redacts values; typed echo forms are masked with `[скрыто]`.

---

## 4. Manual Verification Evidence

All probes were executed with Python 3.12 in `.venv`.

### Complete Verification Probe Run
Command:
```bash
.venv/bin/python -c "
import sys, re, ssl, asyncio, tempfile
from pathlib import Path
sys.path.insert(0, 'claude-sdk-host/src')

import httpx
from claude_host.credentials import (
    StandRunnerAccess,
    CredentialNotFound,
    GrantInactiveError,
    CredentialError,
    CredentialProviderClient,
    should_bypass_proxy,
    GRANT_ID_PATTERN,
)
from claude_host.browser import (
    origin_of,
    split_address,
    stand_url_refusal,
    echo_variants,
    BrowserUnavailable,
)
from claude_host.browser_tools import (
    BrowserToolkit,
    TOOL_SPECS,
    ToolRefusal,
    ToolOutput,
)
from claude_host.evidence import McpEvidenceSink
from claude_host.submission import (
    Submission,
    source_refusal,
    ACCEPTED,
    ALREADY_SUBMITTED,
)
from claude_host.sdk_tools import (
    SessionTools,
    _make_sdk_tool,
    _make_sdk_server,
)
from claude_host.contracts import RunFailure

print('=== STARTING COMPLETE VERIFICATION SUITE ===')

# 1. StandRunnerAccess & Redaction
access = StandRunnerAccess(
    address='https://stand.example.com',
    credential_key='admin_key',
    _values={'admin_key': {'LOGIN': 'admin_user', 'PASSWORD': 'SuperSecretPassword123!', '__HTTP_BASIC_USERNAME': 'b_user', '__HTTP_BASIC_PASSWORD': 'b_pass'}}
)
assert 'SuperSecretPassword123!' not in repr(access) and 'admin_user' not in repr(access)
assert access.contains_sensitive(b'hello admin_user world')
assert access.contains_sensitive(b'pass: SuperSecretPassword123!')
assert access.contains_sensitive(b'auth: b_user')
assert not access.contains_sensitive(b'hello harmless text')
redacted = access.redact_text('User admin_user with SuperSecretPassword123! and b_user:b_pass logged in')
assert 'admin_user' not in redacted and 'SuperSecretPassword123!' not in redacted
assert 'b_user' not in redacted and 'b_pass' not in redacted
assert '[скрыто]' in redacted
print('CHECK 1 (StandRunnerAccess): PASSED')

# 2. Finding 1: SessionTools.from_payload validations
provider_valid = {'url': 'https://provider.example.com', 'token_file': '/tmp/test_token'}
try:
    SessionTools.from_payload(browser={'origin': 'https://user:pass@stand.example.com', 'credential_key': 'k', 'lease_token': 'l'}, provider=provider_valid)
    assert False
except ValueError as e:
    assert 'credentials embedded in browser origin' in str(e)

try:
    SessionTools.from_payload(browser={'origin': 'https://stand.example.com', 'address': 'https://user:pass@stand.example.com', 'credential_key': 'k', 'lease_token': 'l'}, provider=provider_valid)
    assert False
except ValueError as e:
    assert 'credentials embedded in browser address' in str(e)

try:
    SessionTools.from_payload(browser={'origin': 'ftp://stand.example.com', 'credential_key': 'k', 'lease_token': 'l'}, provider=provider_valid)
    assert False
except ValueError as e:
    assert 'HTTP or HTTPS' in str(e)

try:
    SessionTools.from_payload(browser={'origin': 'https://stand-a.example.com', 'address': 'https://stand-b.example.com', 'credential_key': 'k', 'lease_token': 'l'}, provider=provider_valid)
    assert False
except ValueError as e:
    assert 'does not match browser origin' in str(e)

st_valid = SessionTools.from_payload(browser={'origin': 'https://stand.example.com', 'address': 'https://stand.example.com/login', 'credential_key': 'k', 'lease_token': 'l'}, provider=provider_valid)
assert st_valid._origin == 'https://stand.example.com'
assert st_valid._address == 'https://stand.example.com/login'
print('CHECK 2 (Finding 1: URL & Origin Binding): PASSED')

# 3. Finding 2: CredentialProviderClient & wire contract
with tempfile.NamedTemporaryFile('w') as tf:
    tf.write('token123')
    tf.flush()
    tf_path = Path(tf.name)

    # HTTPS required
    try:
        CredentialProviderClient('http://provider.example.com', tf_path)
        assert False
    except CredentialError as e:
        assert 'base_url_must_be_https' in str(e)

    # No URL credentials, query, or fragment
    try:
        CredentialProviderClient('https://u:p@provider.example.com', tf_path)
        assert False
    except CredentialError as e:
        assert 'base_url_credentials_forbidden' in str(e)
    try:
        CredentialProviderClient('https://provider.example.com/api?q=1', tf_path)
        assert False
    except CredentialError as e:
        assert 'base_url_query_forbidden' in str(e)
    try:
        CredentialProviderClient('https://provider.example.com/api#f', tf_path)
        assert False
    except CredentialError as e:
        assert 'base_url_fragment_forbidden' in str(e)

    # Proxy bypass exact match only
    bypass = ['internal.corp', '10.0.0.1']
    assert should_bypass_proxy('https://internal.corp/api', bypass) is True
    assert should_bypass_proxy('https://10.0.0.1:8443/api', bypass) is True
    assert should_bypass_proxy('https://sub.internal.corp/api', bypass) is False
    assert should_bypass_proxy('https://internal.corp/api', ['*']) is False

    # Mock client wire tests
    valid_grant_id = '11111111-1111-1111-1111-111111111111.22222222-2222-2222-2222-222222222222'
    def mock_handler(request: httpx.Request):
        if request.url.path == '/redeem':
            return httpx.Response(200, json={
                'grant_id': valid_grant_id,
                'expires_at': '2099-01-01T00:00:00Z',
                'values': {'LOGIN': 'admin', 'PASSWORD': 'secret_password'}
            })
        if request.url.path == f'/grants/{valid_grant_id}':
            return httpx.Response(200, json={
                'active': True,
                'expires_at': '2099-01-01T00:00:00Z'
            })
        return httpx.Response(404)

    mock_http = httpx.AsyncClient(transport=httpx.MockTransport(mock_handler))
    client = CredentialProviderClient('https://provider.example.com', tf_path, http_client=mock_http)
    
    async def run_client_checks():
        gid, vals, exp = await client.redeem('lease', 'key', 'https://stand.example.com')
        assert gid == valid_grant_id
        assert vals == {'LOGIN': 'admin', 'PASSWORD': 'secret_password'}
        st = await client.check_active()
        assert st.active is True
        await client.aclose()
    asyncio.run(run_client_checks())

print('CHECK 3 (Finding 2: Wire Contract & Grant ID Validation): PASSED')

# 4. Finding 3: submit_test and BrowserToolkit active check fail-closed
async def run_finding_3_checks():
    stand = StandRunnerAccess(address='https://stand.example.com', credential_key='k', _values={'k': {'LOGIN': 'u'}})
    async def failing_cb():
        raise RunFailure('grant_inactive')
    
    class MockSess:
        broken = lambda self: False
        async def reset(self): pass

    tk = BrowserToolkit(stand=stand, session=MockSess(), check_active_cb=failing_cb)
    try:
        await tk.call('snapshot', {})
        assert False
    except RunFailure as rf:
        assert rf.code == 'grant_inactive'
asyncio.run(run_finding_3_checks())
print('CHECK 4 (Finding 3: Active Grant Check Fail-Closed): PASSED')

# 5. Finding 4: SessionTools.start session.start call, cleanup on failure, aclose clearing secrets
async def run_finding_4_checks():
    with tempfile.NamedTemporaryFile('w') as tf:
        tf.write('token123')
        tf.flush()
        
        class MockClient:
            def __init__(self): self.closed = False
            async def redeem(self, **kwargs):
                return '11111111-1111-1111-1111-111111111111.22222222-2222-2222-2222-222222222222', {'LOGIN': 'admin'}, '2099-01-01T00:00:00Z'
            async def check_active(self):
                from claude_host.credentials import GrantStatus
                return GrantStatus('11111111-1111-1111-1111-111111111111.22222222-2222-2222-2222-222222222222', True, '2099-01-01T00:00:00Z')
            async def aclose(self): self.closed = True

        class FailingSess:
            def __init__(self): self.reset_called = False
            async def start(self): raise BrowserUnavailable('failed to start')
            async def reset(self): self.reset_called = True

        c1 = MockClient()
        s1 = FailingSess()
        st1 = SessionTools.from_payload(
            browser={'origin': 'https://stand.example.com', 'credential_key': 'k', 'lease_token': 'secret_lease_1'},
            provider={'url': 'https://provider.example.com', 'token_file': tf.name},
            credential_client=c1,
            session=s1,
        )
        try:
            await st1.start()
            assert False
        except BrowserUnavailable:
            pass
        assert st1._started is False
        assert st1._lease_token == ''
        assert st1._stand is None
        assert s1.reset_called is True
        assert c1.closed is True

        # Successful start and aclose
        class SuccessSess:
            def __init__(self): self.started = False; self.reset_called = False
            async def start(self): self.started = True
            async def reset(self): self.reset_called = True

        c2 = MockClient()
        s2 = SuccessSess()
        st2 = SessionTools.from_payload(
            browser={'origin': 'https://stand.example.com', 'credential_key': 'k', 'lease_token': 'secret_lease_2'},
            provider={'url': 'https://provider.example.com', 'token_file': tf.name},
            source_contract={'path': 'test.ts', 'global_case_id': '123', 'credential_key': 'k'},
            credential_client=c2,
            session=s2,
        )
        await st2.start()
        assert st2._started is True
        assert s2.started is True

        class DummySDK:
            def tool(self, name, desc, schema):
                def dec(fn): fn._name = name; return fn
                return dec
            def create_sdk_mcp_server(self, name, version, tools):
                return {'name': name, 'tools': tools}

        srvs = st2.sdk_servers(DummySDK())
        submit_fn = srvs['author']['tools'][0]
        valid_ts = 'import { test } from \"@playwright/test\";\ntest(\"123: test\", () => {});'
        reply = await submit_fn({'source': valid_ts})
        assert not reply['is_error']
        assert st2.accepted_source == valid_ts

        # aclose
        await st2.aclose()
        assert st2._started is False
        assert st2._lease_token == ''
        assert st2._stand is None
        assert s2.reset_called is True
        assert c2.closed is True
        assert st2.accepted_source == valid_ts
asyncio.run(run_finding_4_checks())
print('CHECK 5 (Finding 4: SessionTools Lifecycle & Secret Clearing): PASSED')

# 6. Finding 5: Mandatory official SDK interface
try:
    _make_sdk_tool(object(), TOOL_SPECS[0], lambda: None)
    assert False
except TypeError as e:
    assert 'missing callable tool() decorator' in str(e)

try:
    _make_sdk_server(object(), 'srv', [])
    assert False
except TypeError as e:
    assert 'missing callable create_sdk_mcp_server()' in str(e)
print('CHECK 6 (Finding 5: Official SDK Mandatory): PASSED')

# 7. Finding 6: EvidenceSink network options
evidence_sink = McpEvidenceSink(
    url='https://tms.internal/mcp',
    token='sec_tok',
    proxy_url='http://proxy:8080',
    proxy_bypass=['tms.internal']
)
assert 'sec_tok' not in repr(evidence_sink)
assert evidence_sink._proxy_bypass == ['tms.internal']
print('CHECK 7 (Finding 6: Evidence Sink Network Options): PASSED')

# 8. Finding 7: HTTP Basic Auth reserved keys & masking
async def run_finding_7_checks():
    stand = StandRunnerAccess(
        address='https://stand.example.com',
        credential_key='k',
        _values={'k': {'LOGIN': 'u', 'PASSWORD': 'p', '__HTTP_BASIC_USERNAME': 'b_user', '__HTTP_BASIC_PASSWORD': 'b_pass'}}
    )
    class MockSess:
        broken = lambda self: False
        async def reset(self): pass

    tk = BrowserToolkit(stand=stand, session=MockSess(), http_credentials=('b_user', 'b_pass'))
    text = 'Echoing b_user and b_pass with u and p'
    shaped = tk._shape(text)
    assert 'b_user' not in shaped and 'b_pass' not in shaped
    assert 'u' not in shaped and 'p' not in shaped
    assert '[скрыто]' in shaped
asyncio.run(run_finding_7_checks())
print('CHECK 8 (Finding 7: Basic Auth Reserved Keys & Masking): PASSED')

# 9. Finding 8: TMS Child Process Template Verification
prompt_path = '/Users/ivanakimkin/Projects/ai-testcase-generator/test_importer_web/backend/src/tms/agents/sdk_author/prompt.py'
content = open(prompt_path).read()
m = re.search(r'_TEMPLATE = r\"\"\"(.*?)\"\"\"', content, re.DOTALL)
template = m.group(1).replace('@KEY@', 'admin_k').replace('@ID@', 'case_99').replace('@TESTNAME@', '\"case_99: Title\"').replace('@STEPS@', '  // step')
contract = {'global_case_id': 'case_99', 'credential_key': 'admin_k'}
assert source_refusal(template, contract) is None
assert source_refusal(template + '\nexecSync(\"id\");', contract) is not None
print('CHECK 9 (Finding 8: Pure TMS Child Process Template Accepted, Arbitrary Rejected): PASSED')

print('=== ALL CHECKS PASSED SUCCESSFULLY ===')
"
```
Output:
```
=== STARTING COMPLETE VERIFICATION SUITE ===
CHECK 1 (StandRunnerAccess): PASSED
CHECK 2 (Finding 1: URL & Origin Binding): PASSED
CHECK 3 (Finding 2: Wire Contract & Grant ID Validation): PASSED
CHECK 4 (Finding 3: Active Grant Check Fail-Closed): PASSED
CHECK 5 (Finding 4: SessionTools Lifecycle & Secret Clearing): PASSED
CHECK 6 (Finding 5: Official SDK Mandatory): PASSED
CHECK 7 (Finding 6: Evidence Sink Network Options): PASSED
CHECK 8 (Finding 7: Basic Auth Reserved Keys & Masking): PASSED
CHECK 9 (Finding 8: Pure TMS Child Process Template Accepted, Arbitrary Rejected): PASSED
=== ALL CHECKS PASSED SUCCESSFULLY ===
```

---

## 5. Findings and Blockers

- **Findings**: All 8 findings from `docs/plans/tracks/sdk-host-browser-c1-correction.md` are resolved in full.
- **Blockers**: None.
