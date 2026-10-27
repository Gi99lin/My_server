"""Operator-owned configuration and secret-file loading. No credentials in environment examples."""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .contracts import RunFailure

ALL_SCOPES = {"completion", "session:create", "session:read", "session:cancel"}


def read_secret(path: Path) -> str:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        raise RunFailure("secret_file_unavailable") from None
    if len(value) < 24 or len(value) > 4096 or any(char.isspace() for char in value):
        raise RunFailure("invalid_secret_file")
    return value


def endpoint(value: str, *, https_only: bool = False) -> str:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise ValueError("invalid endpoint") from None
    if (
        parsed.scheme not in ({"https"} if https_only else {"http", "https"})
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise ValueError("endpoint requires a hostname, explicit HTTP(S), and no credentials/query/fragment")
    if parsed.hostname.lower() in {
        "localhost",
        "127.0.0.1",
        "::1",
        "host.docker.internal",
        "169.254.169.254",
    }:
        raise ValueError("host/loopback/metadata endpoints are not allowed")
    return value.rstrip("/")


class Application(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
    owner: str = Field(min_length=1, max_length=256)
    token_file: Path
    scopes: list[str]
    models: list[str] = Field(min_length=1)
    mcp_endpoints: list[str] = Field(default_factory=list)
    credential_providers: list[str] = Field(default_factory=list)

    @field_validator("scopes")
    @classmethod
    def valid_scopes(cls, values: list[str]) -> list[str]:
        if not values or not set(values) <= ALL_SCOPES:
            raise ValueError("invalid application scopes")
        return values

    @field_validator("mcp_endpoints")
    @classmethod
    def valid_endpoints(cls, values: list[str]) -> list[str]:
        return [endpoint(value) for value in values]


class CredentialProvider(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    url: str
    token_file: Path
    ca_file: Path | None = None

    @field_validator("url")
    @classmethod
    def valid_url(cls, value: str) -> str:
        return endpoint(value, https_only=True)


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    applications: list[Application] = Field(min_length=1)
    models: dict[str, str] = Field(min_length=1)
    proxy_url: str
    proxy_bypass: list[str] = Field(default_factory=list)
    credential_providers: dict[str, CredentialProvider] = Field(default_factory=dict)
    idempotency_key_file: Path
    auth_dir: Path = Path("/var/lib/claude-auth")
    journal_path: Path = Path("/var/lib/claude-host/journal.sqlite3")
    work_dir: Path = Path("/tmp/claude-host")
    network_ready_file: Path | None = None
    max_children: int = Field(default=1, ge=1, le=2)
    agent_queue_size: int = Field(default=8, ge=1, le=32)
    completion_queue_size: int = Field(default=16, ge=1, le=64)
    queue_wait_seconds: float = Field(default=30, gt=0, le=30)
    consumer_timeout_seconds: float = Field(default=30, gt=0, le=30)
    submission_retention_seconds: float = Field(default=30, gt=0, le=30)
    completion_timeout_seconds: float = Field(default=300, gt=0, le=300)
    max_agent_seconds: int = Field(default=14400, ge=1, le=604800)
    max_agent_tokens: int = Field(default=2_000_000, ge=1, le=10_000_000)
    max_body_bytes: int = Field(default=262_144, ge=1024, le=1_048_576)
    max_journal_bytes: int = Field(default=268_435_456, ge=1_048_576)

    @field_validator("proxy_url")
    @classmethod
    def valid_proxy(cls, value: str) -> str:
        return endpoint(value)

    @field_validator("proxy_bypass")
    @classmethod
    def valid_bypass(cls, values: list[str]) -> list[str]:
        if any(not value or any(c in value for c in "*/,@") or any(c.isspace() for c in value) for value in values):
            raise ValueError("proxy bypass requires exact hostnames or IP addresses")
        return values

    @model_validator(mode="after")
    def valid_registry(self) -> Settings:
        ids = [app.id for app in self.applications]
        if len(set(ids)) != len(ids):
            raise ValueError("application ids must be unique")
        if any(not value or any(c.isspace() for c in value) for value in self.models.values()):
            raise ValueError("model ids must be nonempty names")
        for app in self.applications:
            if not set(app.models) <= self.models.keys():
                raise ValueError("application refers to unregistered model")
            if not set(app.credential_providers) <= self.credential_providers.keys():
                raise ValueError("application refers to unregistered credential provider")
        return self

    def verify_secret_files(self) -> None:
        seen: set[str] = set()
        for app in self.applications:
            value = read_secret(app.token_file)
            if value in seen:
                raise RunFailure("duplicate_application_token")
            seen.add(value)
        read_secret(self.idempotency_key_file)
        for provider in self.credential_providers.values():
            read_secret(provider.token_file)
            if provider.ca_file is not None and not provider.ca_file.is_file():
                raise RunFailure("provider_ca_unavailable")

    def sdk_environment(self) -> dict[str, str]:
        result = {name: os.environ[name] for name in ("PATH", "LANG", "LC_ALL", "TMPDIR") if name in os.environ}
        result.update(
            {
                "HOME": str(self.auth_dir.parent),
                "PLAYWRIGHT_BROWSERS_PATH": "/ms-playwright",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONUNBUFFERED": "1",
                "CLAUDE_CONFIG_DIR": str(self.auth_dir),
                "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
                "DISABLE_AUTOUPDATER": "1",
                "HTTP_PROXY": self.proxy_url,
                "HTTPS_PROXY": self.proxy_url,
                "http_proxy": self.proxy_url,
                "https_proxy": self.proxy_url,
                "NO_PROXY": ",".join(self.proxy_bypass),
                "no_proxy": ",".join(self.proxy_bypass),
            }
        )
        return result


def load_settings(path: Path) -> Settings:
    try:
        settings = Settings.model_validate(json.loads(path.read_text(encoding="utf-8")))
        settings.verify_secret_files()
        return settings
    except RunFailure:
        raise
    except Exception:
        # Pydantic errors can include rejected values; never echo a secret-bearing config.
        raise RunFailure("invalid_host_configuration") from None
