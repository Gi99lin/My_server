"""SessionTools factory and in-process SDK MCP tool server registration.

Provenance:
Adapted from /Users/ivanakimkin/Projects/ai-testcase-generator/test_importer_web/backend/src/tms/agents/sdk_runner/sdk_server.py
and src/tms/agents/sdk_author/tools.py.
Preserves exact tool names (mcp__browser__{name}, mcp__author__submit_test), pure constructor factory,
and fail-closed grant watchdog checks.
"""

from __future__ import annotations

import logging
from typing import Any

from .browser import BrowserSession
from .browser_tools import TOOL_SPECS, BrowserToolkit, ToolOutput, ToolSpec
from .contracts import RunFailure
from .credentials import (
    CredentialError,
    CredentialProviderClient,
    GrantInactiveError,
    StandRunnerAccess,
)
from .evidence import McpEvidenceSink
from .submission import SUBMIT_SPEC, Submission

logger = logging.getLogger(__name__)

BROWSER_SERVER = "browser"
AUTHOR_SERVER = "author"
HIDDEN_BROWSER_TOOLS = ("attach_evidence",)


def browser_tool_names() -> list[str]:
    return [f"mcp__{BROWSER_SERVER}__{spec.name}" for spec in TOOL_SPECS]


def author_browser_specs() -> list[ToolSpec]:
    return [spec for spec in TOOL_SPECS if spec.name not in HIDDEN_BROWSER_TOOLS]


def author_tool_names() -> list[str]:
    return [
        *(f"mcp__{BROWSER_SERVER}__{spec.name}" for spec in author_browser_specs()),
        f"mcp__{AUTHOR_SERVER}__{SUBMIT_SPEC.name}",
    ]


def _format_reply(output: ToolOutput) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": output.text}],
        "is_error": output.is_error,
    }


def _make_sdk_tool(sdk: Any, spec: ToolSpec, handler_fn: Any) -> Any:
    if hasattr(sdk, "tool") and callable(sdk.tool):
        decorator = sdk.tool(spec.name, spec.description, spec.input_schema)
        return decorator(handler_fn)
    return handler_fn


def _make_sdk_server(sdk: Any, name: str, tools: list[Any]) -> Any:
    if hasattr(sdk, "create_sdk_mcp_server") and callable(sdk.create_sdk_mcp_server):
        return sdk.create_sdk_mcp_server(name=name, version="1.0.0", tools=tools)
    return {"name": name, "version": "1.0.0", "tools": tools}


class SessionTools:
    """Manages the lifecycle of browser tools, credentials and author submission for an SDK session.

    Constructed purely via `from_payload`.
    `start()` redeems credentials, creates local toolkit and preconfigures the browser session.
    """

    def __init__(
        self,
        *,
        browser_payload: dict[str, Any],
        provider_config: dict[str, Any],
        execution_payload: dict[str, Any] | None = None,
        source_contract: dict[str, Any] | None = None,
        credential_client: CredentialProviderClient | None = None,
    ) -> None:
        self._browser_payload = browser_payload
        self._provider_config = provider_config
        self._execution_payload = execution_payload
        self._source_contract = source_contract

        self._origin: str = browser_payload["origin"]
        self._address: str = browser_payload.get("address") or self._origin
        self._credential_key: str = browser_payload["credential_key"]
        self._lease_token: str = browser_payload["lease_token"]

        self._credential_client = credential_client
        self._stand: StandRunnerAccess | None = None
        self._evidence_sink: McpEvidenceSink | None = None
        self._session: BrowserSession | None = None
        self._toolkit: BrowserToolkit | None = None
        self._submission: Submission | None = None
        self._started = False

    def __repr__(self) -> str:
        return (
            f"SessionTools(origin={self._origin!r}, credential_key={self._credential_key!r}, "
            f"started={self._started})"
        )

    @classmethod
    def from_payload(
        cls,
        browser: dict[str, Any],
        provider: dict[str, Any],
        execution: dict[str, Any] | None = None,
        source_contract: dict[str, Any] | None = None,
        *,
        credential_client: CredentialProviderClient | None = None,
    ) -> SessionTools:
        """Pure factory: validates payload parameters without initiating I/O or browser launch."""
        if not isinstance(browser, dict):
            raise ValueError("browser payload must be a dict")
        if not isinstance(provider, dict):
            raise ValueError("provider config must be a dict")

        for key in ("origin", "credential_key", "lease_token"):
            if not browser.get(key) or not isinstance(browser[key], str):
                raise ValueError(f"browser payload missing required field: {key}")

        for key in ("url", "token_file"):
            if not provider.get(key) or not isinstance(provider[key], str):
                raise ValueError(f"provider config missing required field: {key}")

        if execution is not None:
            if not isinstance(execution, dict):
                raise ValueError("execution payload must be a dict or None")
            for key in ("url", "token"):
                if not execution.get(key) or not isinstance(execution[key], str):
                    raise ValueError(f"execution payload missing required field: {key}")

        if source_contract is not None:
            if not isinstance(source_contract, dict):
                raise ValueError("source_contract must be a dict or None")
            for key in ("path", "global_case_id", "credential_key"):
                if key not in source_contract or source_contract[key] is None:
                    raise ValueError(f"source_contract missing required field: {key}")

        return cls(
            browser_payload=browser,
            provider_config=provider,
            execution_payload=execution,
            source_contract=source_contract,
            credential_client=credential_client,
        )

    async def start(self) -> None:
        """Redeem credentials, initialize local toolkit and preconfigure browser session."""
        if self._started:
            return

        if self._credential_client is None:
            self._credential_client = CredentialProviderClient(
                base_url=self._provider_config["url"],
                token_file=self._provider_config["token_file"],
                ca_file=self._provider_config.get("ca_file"),
                proxy_url=self._provider_config.get("proxy_url"),
                proxy_bypass=self._provider_config.get("proxy_bypass"),
            )

        grant_id, values, expires_at = await self._credential_client.redeem(
            lease_token=self._lease_token,
            credential_key=self._credential_key,
            origin=self._origin,
        )

        self._stand = StandRunnerAccess(
            address=self._address,
            credential_key=self._credential_key,
            role="runner",
            _values={self._credential_key: values},
        )

        if self._execution_payload:
            self._evidence_sink = McpEvidenceSink(
                url=self._execution_payload["url"],
                token=self._execution_payload["token"],
            )

        self._session = BrowserSession(
            stand_address=self._address,
            action_timeout_ms=10_000,
            proxy_url=self._provider_config.get("proxy_url"),
            proxy_bypass=self._provider_config.get("proxy_bypass"),
        )

        async def _check_active_cb() -> None:
            await self.check_active()

        self._toolkit = BrowserToolkit(
            stand=self._stand,
            evidence=self._evidence_sink,
            session=self._session,
            action_timeout_ms=10_000,
            check_active_cb=_check_active_cb,
        )

        if self._source_contract is not None:
            self._submission = Submission(
                contract=self._source_contract,
                access=self._stand,
            )

        self._started = True

    async def check_active(self) -> None:
        """Fail closed if the credential grant is revoked, expired, or provider unreachable."""
        if self._credential_client is None or not self._started:
            raise RunFailure("tools_not_started")
        try:
            status = await self._credential_client.check_active()
            if not status.active:
                raise RunFailure("grant_inactive")
        except GrantInactiveError:
            raise RunFailure("grant_inactive") from None
        except RunFailure:
            raise
        except CredentialError:
            raise RunFailure("grant_check_failed") from None

    async def aclose(self) -> None:
        """Release browser session and tools."""
        if self._toolkit is not None:
            await self._toolkit.aclose()
        self._started = False

    def sdk_servers(self, sdk: Any) -> dict[str, Any]:
        """Produce the SDK in-process MCP servers for Claude Agent SDK."""
        if not self._started or self._toolkit is None:
            raise RuntimeError("SessionTools must be started before sdk_servers")

        toolkit = self._toolkit

        if self._source_contract is not None:
            # Authoring profile: browser tools exclude attach_evidence; author server exposes submit_test
            submission = self._submission
            if submission is None:
                raise RuntimeError("Authoring session missing submission instance")

            specs = author_browser_specs()

            def make_browser_handler(spec_name: str):
                async def handler(arguments: dict[str, Any]) -> dict[str, Any]:
                    output = await toolkit.call(spec_name, arguments)
                    return _format_reply(output)
                return handler

            browser_tools = [
                _make_sdk_tool(sdk, spec, make_browser_handler(spec.name))
                for spec in specs
            ]

            async def submit_test_handler(arguments: dict[str, Any]) -> dict[str, Any]:
                output = submission.submit(arguments)
                return _format_reply(output)

            submit_tool = _make_sdk_tool(sdk, SUBMIT_SPEC, submit_test_handler)

            return {
                BROWSER_SERVER: _make_sdk_server(sdk, BROWSER_SERVER, browser_tools),
                AUTHOR_SERVER: _make_sdk_server(sdk, AUTHOR_SERVER, [submit_tool]),
            }

        # Execution profile: all 9 browser tools
        def make_execution_browser_handler(spec_name: str):
            async def handler(arguments: dict[str, Any]) -> dict[str, Any]:
                output = await toolkit.call(spec_name, arguments)
                return _format_reply(output)
            return handler

        browser_tools = [
            _make_sdk_tool(sdk, spec, make_execution_browser_handler(spec.name))
            for spec in TOOL_SPECS
        ]
        return {
            BROWSER_SERVER: _make_sdk_server(sdk, BROWSER_SERVER, browser_tools),
        }

    def allowed_tool_names(self) -> list[str]:
        """Return the exact public tool names for this session profile."""
        if self._source_contract is not None:
            return author_tool_names()
        return browser_tool_names()

    @property
    def accepted_source(self) -> str | None:
        """Return the single accepted test source for authoring sessions, or None."""
        return self._submission.source if self._submission is not None else None
