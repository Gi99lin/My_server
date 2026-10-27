# Browser Lane Cycle 1 Report

## 1. Provenance and Scope

This lane implements the local browser, credential management, evidence sink, submission validation, and SDK MCP tool registration for `claude-sdk-host`.

Source files adapted (read-only reference at `f258ba7a` in `/Users/ivanakimkin/Projects/ai-testcase-generator/test_importer_web/backend/`):
- `claude_host/browser_tools.py` & `claude_host/browser.py`:
  Adapted from `src/tms/agents/sdk_runner/browser_tools.py`. Extracted headless Playwright Chromium lifecycle, proxy/bypass configuration, `chromium_sandbox=True`, same-origin routing/204 response on blocked navigation, dialog handling, console collection, and all 9 tool specifications and serialized handlers.
- `claude_host/credentials.py`:
  Adapted from `src/tms/projects/stands/service.py` (`StandRunnerAccess`). Implements the frozen credential provider wire contract (`POST /redeem` and `GET /grants/{grant_id}`). Stripped all TMS database, SQLAlchemy, keyring, and IAM dependencies.
- `claude_host/evidence.py`:
  Adapted from `src/tms/agents/sdk_runner/evidence.py`. Connects to `tms-execution` streamable HTTP MCP server with run-bound `PrivateToken` and calls hidden `attach_evidence`. Model never sees attachment bytes or tokens.
- `claude_host/submission.py`:
  Adapted from `src/tms/agents/sdk_author/submission.py` and pure rules in `src/tms/agents/authoring/worker.py` (`source_refusal`). Zero backend or git dependencies.
- `claude_host/sdk_tools.py`:
  Adapted from `src/tms/agents/sdk_runner/sdk_server.py` and `src/tms/agents/sdk_author/tools.py`. Implements `SessionTools` pure factory, lifecycle, active grant watchdog, and in-process SDK MCP server registration.

Ownership followed:
- Only modified files within `claude-sdk-host/src/claude_host/{browser_tools.py, browser.py, credentials.py, evidence.py, submission.py, sdk_tools.py}` and `docs/plans/tracks/sdk-host-browser-c1-report.md`.
- No modifications to coordinator-owned `contracts.py`, `pyproject.toml`, or other lane files.
- No new automated test suite added (compliant with owner's non-UI infra rule).
- Verified with manual inline probes via Python 3.12.

---

## 2. Interface Assumptions and Contracts

### `SessionTools` Lifecycle
```python
SessionTools.from_payload(
    browser: dict,
    provider: dict,
    execution: dict | None = None,
    source_contract: dict | None = None,
) -> SessionTools
```
- **Pure Constructor Factory**: Validates payload structure and required keys; performs no I/O, network requests, or browser launches during instantiation.
- `await start()`: Reads operator token file, redeems credentials with provider, initializes `StandRunnerAccess`, configures `BrowserSession` (sandbox & proxy/bypass), sets up `BrowserToolkit` with a fail-closed active grant check callback, and instantiates `Submission` if in authoring mode.
- `await check_active()`: Verifies grant with provider (`GET /grants/{grant_id}`). Fails closed by raising `RunFailure("grant_inactive")` if revoked, expired, or provider unreachable.
- `await aclose()`: Cleanly shuts down browser session and context.
- `sdk_servers(sdk) -> dict[str, Any]`:
  - Execution profile: returns `{"browser": server}` exposing all 9 browser tools (`open_url`, `snapshot`, `click`, `type_text`, `type_stand_secret`, `press_key`, `select_option`, `wait`, `attach_evidence`).
  - Authoring profile: returns `{"browser": server, "author": server}` where browser server exposes 8 inspection tools (`attach_evidence` hidden) and author server exposes `submit_test`.
- `allowed_tool_names() -> list[str]`:
  - Execution profile: `mcp__browser__{name}` for all 9 tools.
  - Authoring profile: `mcp__browser__{name}` (excluding `attach_evidence`) + `mcp__author__submit_test`.
- `accepted_source: str | None`: Property returning the accepted test source string for authoring sessions, or `None`.

### Credential Provider Wire Contract
- `POST {provider.url}/redeem`:
  - Header: `Authorization: Bearer <token_from_token_file>`
  - Body: `{"lease_token": str, "credential_key": str, "origin": str}`
  - Response (200): `{"grant_id": str, "expires_at": str (ISO 8601 UTC), "values": {"LOGIN": str, "PASSWORD": str, ...}}`
  - Rejects: HTTP redirects, non-200 status, missing/non-string values, expired grants.
- `GET {provider.url}/grants/{grant_id}`:
  - Header: `Authorization: Bearer <token_from_token_file>`
  - Response (200): `{"active": bool, "expires_at": str (ISO 8601 UTC)}`
  - Rejects: Inactive grants, local/remote expiration, network failures, redirects.
- Proxy handling: Provider requests bypass HTTP proxy if provider host is matched in `proxy_bypass`; otherwise routed via `proxy_url` if configured.
- Secret safety: `StandRunnerAccess` keeps secrets strictly in memory; `__repr__` redacts values; typed echo forms (URL-encoded, HTML-escaped, JSON-escaped, Base64) are masked with `[скрыто]`.

### Authoring Submission Contract
- Single accepted source: First valid submission is stored in memory (`accepted_source`).
- Idempotency: Repeated identical source returns success (`ACCEPTED`). Differing subsequent submission is refused with `ALREADY_SUBMITTED`.
- Refusal rules enforced in pure Python:
  - File size cap: 60,000 characters.
  - Must import `@playwright/test`.
  - Must include `global_case_id` from contract.
  - No secret values or echo variants from `StandRunnerAccess`.
  - No reading whole `process.env`.
  - Module import whitelist (`@playwright/test`, `playwright`, `fs`, `os`, `path`, etc.).
  - No code evaluation (`eval`, `new Function`) or arbitrary `child_process`.
  - No direct network requests (`fetch`, `WebSocket`, `XMLHttpRequest`).
  - No secret output to sinks (`console.log`, `Error`, `test.step`, `expect`, `attach`, `writeFile`).
  - No credential literals or fallback literals.
  - Stand address must use `process.env.STAND_URL`.
  - No fixed waits (`waitForTimeout`, `sleep`, `setTimeout`).

---

## 3. Manual Verification Evidence

All probes were executed with Python 3.12 in `.venv`:

### Probe 1: `StandRunnerAccess` and Redaction
Command:
```bash
.venv/bin/python -c "
import sys; sys.path.insert(0, 'claude-sdk-host/src'); import asyncio
from claude_host.credentials import StandRunnerAccess, CredentialNotFound

access = StandRunnerAccess(
    address='https://stand.example.com',
    credential_key='admin_key',
    _values={'admin_key': {'LOGIN': 'admin_user', 'PASSWORD': 'SuperSecretPassword123!'}}
)
assert 'SuperSecretPassword123!' not in repr(access) and 'admin_user' not in repr(access)
assert access.contains_sensitive(b'hello admin_user world')
assert access.contains_sensitive(b'pass: SuperSecretPassword123!')
assert not access.contains_sensitive(b'hello harmless text')
redacted = access.redact_text('User admin_user with SuperSecretPassword123! logged in')
assert 'admin_user' not in redacted and 'SuperSecretPassword123!' not in redacted
assert '[скрыто]' in redacted
typed = []
async def fill(val: str): typed.append(val)
asyncio.run(access.type_named_value('admin_key', 'PASSWORD', fill))
assert typed == ['SuperSecretPassword123!']
try:
    asyncio.run(access.type_named_value('admin_key', 'NONEXISTENT', fill))
    assert False
except CredentialNotFound:
    pass
print('PROBE 1 (StandRunnerAccess): ALL CHECKS PASSED')
"
```
Output:
```
PROBE 1 (StandRunnerAccess): ALL CHECKS PASSED
```

### Probe 2: `CredentialProviderClient` Wire Contract
Tested POST `/redeem` header/payload parsing, response grant validation, redirect rejection, expired grant rejection, and GET `/grants/{grant_id}` fail-closed active checks with `httpx.MockTransport`.
Output:
```
PROBE 2 (CredentialProviderClient): ALL CHECKS PASSED
```

### Probe 3: `submission.py` Validation Constraints and Idempotency
Tested 13 validation rules: missing Playwright, missing case ID, secret leaks, whole `process.env`, forbidden modules, `eval`, direct `fetch`, sinks, credential literals, stand address literal, fixed waits, valid Playwright test acceptance, identical idempotent resubmission, and differing second submission rejection.
Output:
```
PROBE 3 (submission.py): ALL CHECKS PASSED
```

### Probe 4: Browser Session Isolation and `BrowserToolkit`
Tested `origin_of` normalization, `stand_url_refusal` same-origin enforcement, `split_address` basic auth extraction, `echo_variants` generation, `BrowserToolkit._shape()` secret and echo masking, and fail-closed behavior on inactive grant check callback.
Output:
```
PROBE 4 (browser and browser_tools): ALL CHECKS PASSED
```

### Probe 5: `SessionTools` Lifecycle and SDK Integration
Tested execution profile (9 `mcp__browser__{name}` tools), authoring profile (8 browser tools + 1 `mcp__author__submit_test`), in-process SDK MCP server generation, mock credential redemption, active watchdog polling, and fail-closed revocation.
Output:
```
PROBE 5 (SessionTools): ALL CHECKS PASSED
```

---

## 4. Findings and Blockers

- **Findings**: None. All components match the charter and spec requirements without requiring modifications to coordinator-owned files or runtime contracts.
- **Blockers**: None. Playwright Chromium launch was deliberately not executed here per instructions ("Do not actually launch Chromium here; coordinator owns sandbox probe"); all launch options (`chromium_sandbox=True`, `proxy={"server": ...}`, `new_context`) are verified ready for coordinator stack validation.
