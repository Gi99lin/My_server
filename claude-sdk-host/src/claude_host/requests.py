"""Narrow public request contracts. SDK configuration is never client supplied."""

from __future__ import annotations

import json
import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from .config import Application, Settings
from .contracts import RunFailure


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)


class McpServer(StrictRequest):
    name: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")
    url: str = Field(max_length=2048)
    token: SecretStr
    tools: list[str] = Field(min_length=1, max_length=32)


class Browser(StrictRequest):
    origin: str = Field(max_length=2048)
    credential_key: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,31}$")
    credential_provider: str = Field(max_length=64)
    credential_lease: SecretStr


class SourceContract(StrictRequest):
    file_path: str = Field(min_length=1, max_length=1024)
    global_case_id: str = Field(min_length=1, max_length=256)
    credential_key: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,31}$")


class AgentRequest(StrictRequest):
    client_request_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    profile: Literal["tms-execution", "tms-authoring"]
    model: str = Field(min_length=1, max_length=128)
    system_prompt: str = Field(max_length=32000)
    prompt: str = Field(min_length=1, max_length=160000)
    timeout_seconds: int = Field(ge=1)
    token_budget: int = Field(ge=1, le=10_000_000)
    max_turns: int = Field(default=1500, ge=1, le=1500)
    mcp_servers: list[McpServer] = Field(default_factory=list, max_length=8)
    browser: Browser
    source_contract: SourceContract | None = None

    @model_validator(mode="after")
    def coherent(self):
        if self.profile == "tms-authoring":
            if self.mcp_servers or self.source_contract is None or self.max_turns > 120:
                raise ValueError("invalid authoring profile")
            if self.source_contract.credential_key != self.browser.credential_key:
                raise ValueError("credential key mismatch")
        elif self.source_contract is not None or len(self.mcp_servers) != 1:
            raise ValueError("invalid execution profile")
        if len({s.name for s in self.mcp_servers}) != len(self.mcp_servers):
            raise ValueError("duplicate MCP server")
        return self

    def authorize(self, app: Application, settings: Settings) -> None:
        authorize_model(self.model, app, settings)
        if self.timeout_seconds > settings.max_agent_seconds or self.token_budget > settings.max_agent_tokens:
            raise RunFailure("host_budget_exceeded", 400)
        if self.browser.credential_provider not in app.credential_providers:
            raise RunFailure("credential_provider_not_allowed", 403)
        # Browser origin is a navigation boundary, not an arbitrary request URL.
        try:
            p = urlsplit(self.browser.origin)
            if (
                p.scheme not in {"http", "https"}
                or not p.hostname
                or p.username is not None
                or p.password is not None
                or p.path not in {"", "/"}
                or p.query
                or p.fragment
            ):
                raise ValueError
            if p.port is not None and not 1 <= p.port <= 65535:
                raise ValueError
            # A localhost stand origin is valid only with a redeemed, registered
            # tunnel route. The trusted worker enforces that before browser startup.
        except ValueError:
            raise RunFailure("invalid_stand_origin", 400) from None
        execution_tools = {"next_point", "start_attempt", "record_step", "finish_attempt", "hand_off"}
        for server in self.mcp_servers:
            if server.name != "tms-execution" or server.url.rstrip("/") not in app.mcp_endpoints:
                raise RunFailure("mcp_endpoint_not_allowed", 403)
            if len(set(server.tools)) != len(server.tools) or set(server.tools) != execution_tools:
                raise RunFailure("mcp_tools_not_allowed", 400)
            token = server.token.get_secret_value()
            if not token or len(token) > 4096 or any(ord(char) < 33 or ord(char) > 126 for char in token):
                raise RunFailure("invalid_mcp_token", 400)

    def private_payload(self) -> dict:
        data = self.model_dump(mode="json")
        data["browser"]["credential_lease"] = self.browser.credential_lease.get_secret_value()
        for target, server in zip(data["mcp_servers"], self.mcp_servers, strict=True):
            target["token"] = server.token.get_secret_value()
        return data


class Message(StrictRequest):
    role: Literal["system", "user", "assistant"]
    content: str = Field(max_length=160000)


class StreamOptions(StrictRequest):
    include_usage: bool = False


class CompletionRequest(StrictRequest):
    model: str = Field(min_length=1, max_length=128)
    messages: list[Message] | None = Field(default=None, max_length=256)
    prompt: str | None = Field(default=None, max_length=160000)
    stream: bool = False
    stream_options: StreamOptions | None = None
    n: Literal[1] = 1

    def conversation(self, chat: bool) -> tuple[str, str]:
        if chat:
            if not self.messages or self.prompt is not None or not any(m.role == "user" for m in self.messages):
                raise RunFailure("invalid_messages", 400)
            system = "\n\n".join(m.content for m in self.messages if m.role == "system")
            conversation = [{"role": m.role, "content": m.content} for m in self.messages if m.role != "system"]
            # JSON encoding preserves untrusted history as data and prevents delimiter injection.
            return system, "Continue this conversation with the next assistant response.\n" + json.dumps(
                conversation, ensure_ascii=False
            )
        if self.prompt is None or self.messages is not None:
            raise RunFailure("invalid_prompt", 400)
        return "", self.prompt


class Ack(StrictRequest):
    seq: int = Field(ge=0)


def authorize_model(model: str, app: Application, settings: Settings) -> str:
    if model not in app.models or model not in settings.models:
        raise RunFailure("model_not_allowed", 403)
    return settings.models[model]


def safe_identifier(value: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", value):
        raise RunFailure("session_not_found", 404)
    return value
