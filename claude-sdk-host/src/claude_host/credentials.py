"""Credential provider wire client and in-memory stand credential store.

Provenance:
Adapted from TMS src/tms/projects/stands/service.py
(StandRunnerAccess) and frozen wire contract from docs/plans/tracks/sdk-host-browser-c1.md.
No TMS backend, database or keyring dependencies.
"""

from __future__ import annotations

import logging
import re
import ssl
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from .contracts import RunFailure

logger = logging.getLogger(__name__)

GRANT_ID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}\."
    r"[0-9a-fA-F]{8}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{4}-?[0-9a-fA-F]{12}$"
)


class CredentialError(Exception):
    """Base exception for credential errors. Does not contain secrets in error strings."""


class CredentialNotFound(CredentialError):
    """A named credential was not found in the stand's credential store."""


class GrantInactiveError(CredentialError):
    """The credential grant is inactive or revoked."""


def parse_utc_iso(iso_str: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp string into a timezone-aware UTC datetime."""
    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def is_expired(expires_at: str | datetime) -> bool:
    """Check if an expiration timestamp has passed in UTC."""
    dt = parse_utc_iso(expires_at) if isinstance(expires_at, str) else expires_at
    return datetime.now(UTC) >= dt


@dataclass(frozen=True, repr=False)
class StandRunnerAccess:
    """Opaque in-memory browser access; credentials never leave memory or appear in repr/logs."""

    address: str
    credential_key: str
    role: str = "runner"
    _values: dict[str, dict[str, str]] = field(default_factory=dict, repr=False)

    def __repr__(self) -> str:
        return f"StandRunnerAccess(credential_key={self.credential_key!r}, address={self.address!r}, values=<redacted>)"

    def contains_sensitive(self, data: bytes) -> bool:
        """Check if any secret value in any credential set appears in the given bytes."""
        return any(
            value.encode("utf-8") in data for fields in self._values.values() for value in fields.values() if value
        )

    def redact_text(self, text: str) -> str:
        """Mask every secret value with [скрыто]."""
        for fields in self._values.values():
            for value in fields.values():
                if value:
                    text = text.replace(value, "[скрыто]")
        return text

    async def type_named_value(self, key: str, name: str, fill: Callable[[str], Awaitable[None]]) -> None:
        """Deliver the secret directly to the fill callback without exposing it to callers."""
        values = self._values.get(key, {})
        value = values.get(name)
        if value is None:
            raise CredentialNotFound("Данные для входа не найдены")
        await fill(value)


def should_bypass_proxy(url: str, bypass_list: list[str] | None) -> bool:
    """Determine whether the URL host should bypass the HTTP proxy using exact host/IP equality only."""
    if not bypass_list:
        return False
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
    except Exception:
        return False
    host = host.lower()
    return any(host == pattern.strip().lower() for pattern in bypass_list if pattern.strip())


@dataclass(frozen=True, repr=False)
class GrantStatus:
    grant_id: str
    active: bool
    expires_at: str

    def __repr__(self) -> str:
        return f"GrantStatus(grant_id={self.grant_id!r}, active={self.active}, expires_at={self.expires_at!r})"


class CredentialProviderClient:
    """Client for single-use HTTPS credential redemption and active grant polling.

    Wire contract:
    POST {provider.url}/redeem
      Authorization: Bearer <token_from_token_file>
      Body: {"lease_token": str, "credential_key": str, "origin": str}
      Response: {"grant_id": str, "expires_at": str (ISO UTC), "values": {"LOGIN": str, "PASSWORD": str, ...}}

    GET {provider.url}/grants/{grant_id}
      Authorization: Bearer <token_from_token_file>
      Response: {"active": bool, "expires_at": str (ISO UTC)}

    Rules:
    - Requires HTTPS base URL (no URL credentials, query, or fragment).
    - No redirects (follow_redirects=False).
    - trust_env=False.
    - TLS certificate verification via ssl.create_default_context.
    - Proxy handling: fixed proxy or exact internal bypass (exact host/IP equality only).
    - Validates grant_id safely for path component (TMS format job_uuid.grant_uuid).
    - All errors must be stable codes/phrases without credential values or secret URLs.
    - Reject expired or mismatched credentials.
    - Fails closed on inactive/revoked grants.
    """

    def __init__(
        self,
        base_url: str,
        token_file: str | Path,
        *,
        ca_file: str | Path | None = None,
        proxy_url: str | None = None,
        proxy_bypass: list[str] | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if not isinstance(base_url, str):
            raise CredentialError("base_url_must_be_string")
        parts = urlsplit(base_url.strip())
        if parts.scheme.lower() != "https":
            raise CredentialError("base_url_must_be_https")
        if not parts.hostname:
            raise CredentialError("base_url_missing_hostname")
        if parts.username is not None or parts.password is not None:
            raise CredentialError("base_url_credentials_forbidden")
        if parts.query:
            raise CredentialError("base_url_query_forbidden")
        if parts.fragment:
            raise CredentialError("base_url_fragment_forbidden")

        self._base_url = f"https://{parts.netloc}{parts.path}".rstrip("/")
        self._token_file = Path(token_file)
        self._ca_file = str(ca_file) if ca_file else None
        self._proxy_url = proxy_url
        self._proxy_bypass = [p.strip().lower() for p in (proxy_bypass or []) if p.strip()]
        self._injected_client = http_client
        self._client: httpx.AsyncClient | None = None
        self._grant_id: str | None = None
        self._expires_at: str | None = None

    def __repr__(self) -> str:
        return f"CredentialProviderClient(grant_id={self._grant_id!r})"

    @property
    def grant_id(self) -> str | None:
        return self._grant_id

    def _read_token(self) -> str:
        if not self._token_file.exists():
            raise CredentialError("token_file_missing")
        token = self._token_file.read_text(encoding="utf-8").strip()
        if not token:
            raise CredentialError("token_file_empty")
        return token

    def _build_client(self) -> httpx.AsyncClient:
        if self._injected_client is not None:
            return self._injected_client
        if self._client is None or self._client.is_closed:
            if self._ca_file:
                verify: Any = ssl.create_default_context(cafile=self._ca_file)
            else:
                verify = ssl.create_default_context()
            bypass = should_bypass_proxy(self._base_url, self._proxy_bypass)
            proxy = None if bypass else self._proxy_url

            self._client = httpx.AsyncClient(
                verify=verify,
                proxy=proxy,
                follow_redirects=False,
                trust_env=False,
                timeout=httpx.Timeout(15.0),
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and self._client is not self._injected_client:
            await self._client.aclose()
            self._client = None

    async def redeem(self, lease_token: str, credential_key: str, origin: str) -> tuple[str, dict[str, str], str]:
        """Redeem a single-use credential lease and return (grant_id, values, expires_at)."""
        token = self._read_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        body = {
            "lease_token": lease_token,
            "credential_key": credential_key,
            "origin": origin,
        }

        url = f"{self._base_url}/redeem"
        client = self._build_client()
        try:
            response = await client.post(url, headers=headers, json=body)
        except Exception as err:
            logger.warning("Credential redemption network error: %s", type(err).__name__)
            raise CredentialError("failed_to_reach_credential_provider") from None

        if 300 <= response.status_code < 400:
            raise CredentialError("credential_provider_redirect_forbidden")

        if response.status_code != 200:
            raise CredentialError(f"credential_redemption_failed_{response.status_code}")

        try:
            data = response.json()
        except Exception:
            raise CredentialError("credential_response_invalid_json") from None

        grant_id = data.get("grant_id")
        expires_at = data.get("expires_at")
        values = data.get("values")

        if not isinstance(grant_id, str) or not grant_id.strip():
            raise CredentialError("credential_response_missing_grant_id")
        if not GRANT_ID_PATTERN.match(grant_id):
            raise CredentialError("invalid_grant_id_format")
        if not isinstance(expires_at, str) or not expires_at.strip():
            raise CredentialError("credential_response_missing_expires_at")
        if not isinstance(values, dict):
            raise CredentialError("credential_response_missing_values")

        # Validate that all values are strings
        cleaned_values: dict[str, str] = {}
        for k, v in values.items():
            if not isinstance(k, str) or not isinstance(v, str):
                raise CredentialError("credential_values_invalid")
            cleaned_values[k] = v

        if is_expired(expires_at):
            raise CredentialError("grant_already_expired")

        self._grant_id = grant_id
        self._expires_at = expires_at
        return grant_id, cleaned_values, expires_at

    async def check_active(self) -> GrantStatus:
        """Poll the grant status and fail closed if revoked, expired or unreachable."""
        if self._grant_id is None:
            raise GrantInactiveError("no_active_grant")
        if not GRANT_ID_PATTERN.match(self._grant_id):
            raise GrantInactiveError("invalid_grant_id_format")

        if self._expires_at and is_expired(self._expires_at):
            raise GrantInactiveError("grant_expired_locally")

        token = self._read_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
        url = f"{self._base_url}/grants/{self._grant_id}"

        client = self._build_client()
        try:
            response = await client.get(url, headers=headers)
        except Exception as err:
            logger.warning("Grant check network error: %s", type(err).__name__)
            raise RunFailure("grant_check_failed") from None

        if 300 <= response.status_code < 400:
            raise RunFailure("grant_check_redirect_forbidden")

        if response.status_code != 200:
            raise RunFailure(f"grant_inactive_status_{response.status_code}")

        try:
            data = response.json()
        except Exception:
            raise RunFailure("grant_check_invalid_json") from None

        active = data.get("active")
        expires_at = data.get("expires_at")

        if active is not True:
            raise GrantInactiveError("grant_revoked")

        if not isinstance(expires_at, str) or is_expired(expires_at):
            raise GrantInactiveError("grant_expired")

        self._expires_at = expires_at
        return GrantStatus(grant_id=self._grant_id, active=True, expires_at=expires_at)
