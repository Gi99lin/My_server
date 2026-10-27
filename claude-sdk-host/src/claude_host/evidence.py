"""Streamable HTTP MCP evidence client for tms-execution.

Provenance:
Adapted from TMS src/tms/agents/sdk_runner/evidence.py.
Never logs tokens or transmits raw screenshot/evidence bytes to the model.
"""

from __future__ import annotations

import base64
import logging
import ssl
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Protocol

from .credentials import should_bypass_proxy

logger = logging.getLogger(__name__)

EXECUTION_PATH = "/mcp/tms-execution"
CALL_TIMEOUT_SECONDS = 30.0
UNREACHABLE = "Не удалось приложить доказательство: сервер не ответил. Повторите вызов"


class EvidenceRejected(Exception):
    """The execution tools refused the attachment."""


class EvidenceSink(Protocol):
    async def attach(self, *, point_id: str, step_id: str, kind: str, data: bytes, filename: str) -> str: ...


def execution_url(base_url: str) -> str:
    """The tms-execution server URL below the backend address."""
    return base_url.rstrip("/") + EXECUTION_PATH


class McpEvidenceSink:
    """Invokes attach_evidence on the execution MCP server with a run-bound PrivateToken."""

    def __init__(
        self,
        url: str,
        token: str,
        *,
        ca_file: str | Path | None = None,
        proxy_url: str | None = None,
        proxy_bypass: list[str] | None = None,
        client_factory: Callable[[dict[str, str]], Any] | None = None,
    ) -> None:
        self._url = url
        self._token = token
        self._ca_file = str(ca_file) if ca_file else None
        self._proxy_url = proxy_url
        self._proxy_bypass = [p.strip().lower() for p in (proxy_bypass or []) if p.strip()]
        self._client_factory = client_factory

    def __repr__(self) -> str:
        return f"McpEvidenceSink(url={self._url!r}, token=<redacted>)"

    @asynccontextmanager
    async def _session(self):
        try:
            import httpx2 as http_mod
        except ImportError:
            import httpx as http_mod

        from mcp.client.session import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        headers = {"Authorization": f"PrivateToken {self._token}"}
        if self._client_factory:
            client = self._client_factory(headers)
        else:
            if self._ca_file:
                verify: Any = ssl.create_default_context(cafile=self._ca_file)
            else:
                verify = ssl.create_default_context()
            bypass = should_bypass_proxy(self._url, self._proxy_bypass)
            proxy = None if bypass else self._proxy_url
            client = http_mod.AsyncClient(
                headers=headers,
                verify=verify,
                proxy=proxy,
                follow_redirects=False,
                trust_env=False,
                timeout=http_mod.Timeout(CALL_TIMEOUT_SECONDS),
            )
        async with client:
            async with streamable_http_client(self._url, http_client=client) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    yield session

    async def attach(self, *, point_id: str, step_id: str, kind: str, data: bytes, filename: str) -> str:
        arguments = {
            "point_id": point_id,
            "step_id": step_id,
            "kind": kind,
            "file": base64.b64encode(data).decode(),
            "filename": filename,
        }
        try:
            async with self._session() as session:
                result = await session.call_tool("attach_evidence", arguments)
        except Exception as error:
            logger.warning("attach_evidence did not reach the execution tools: %s", type(error).__name__)
            raise EvidenceRejected(UNREACHABLE) from None

        text = result.content[0].text if result.content and hasattr(result.content[0], "text") else ""
        if getattr(result, "is_error", False):
            raise EvidenceRejected(text or UNREACHABLE)
        return text
