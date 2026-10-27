"""Playwright Chromium lifecycle, proxy configuration, and origin boundaries.

Provenance:
Adapted from TMS src/tms/agents/sdk_runner/browser_tools.py.
Preserves Playwright context options, dialog handling, console collection, secret field masking,
and same-origin navigation enforcement (returning 204 on prohibited navigation/redirects).
Configures explicit proxy/bypass and chromium_sandbox=True.
"""

from __future__ import annotations

import base64
import contextlib
import html
import json
from collections import deque
from typing import Any
from urllib.parse import quote, quote_plus, urljoin, urlsplit, urlunsplit

NAVIGATION_REFUSAL = "Переход запрещён"
CONSOLE_LINES = 300
SECRET_FIELDS_KEPT = 8

CRASH_MARKERS = (
    "target closed",
    "has been closed",
    "browser has been closed",
    "page crashed",
    "connection closed",
    "browser closed",
    "target page, context or browser",
)


class BrowserUnavailable(Exception):
    """Chromium could not be started (Playwright or the browser is not installed)."""


def echo_variants(value: str) -> set[str]:
    """The forms a page can echo a typed value back in: URL-encoded, HTML-escaped, JSON-escaped, base64."""
    raw = value.encode()
    forms = {
        value,
        quote(value, safe=""),
        quote_plus(value),
        html.escape(value),
        html.escape(value, quote=False),
        json.dumps(value, ensure_ascii=True)[1:-1],
        json.dumps(value, ensure_ascii=False)[1:-1],
        base64.b64encode(raw).decode().rstrip("="),
        base64.urlsafe_b64encode(raw).decode().rstrip("="),
    }
    return {form for form in forms if form}


def origin_of(url: str) -> tuple[str, str, int] | None:
    """(scheme, host, port) of an http(s) address, with the default port made explicit; None for anything else."""
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except (ValueError, AttributeError):
        return None
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        return None
    scheme = parts.scheme.lower()
    return scheme, parts.hostname.lower(), port or (443 if scheme == "https" else 80)


def stand_url_refusal(stand_address: str, url: str) -> str | None:
    """Why this address may not be opened, or None. Only the stand's own origin is allowed."""
    stand = origin_of(stand_address)
    target = origin_of(url) if isinstance(url, str) else None
    if stand is None:
        return f"{NAVIGATION_REFUSAL}: адрес стенда задан неверно"
    if target is None or target != stand:
        return f"{NAVIGATION_REFUSAL}: можно открывать только адрес стенда {stand[0]}://{stand[1]}:{stand[2]}"
    if urlsplit(url.strip()).username is not None:
        return f"{NAVIGATION_REFUSAL}: в адресе не должно быть логина и пароля"
    return None


def split_address(address: str) -> tuple[str, tuple[str, str] | None]:
    """The stand's address without a login and password in it, and those, if the address carried them."""
    from urllib.parse import unquote

    try:
        parts = urlsplit(address.strip())
        host, port = parts.hostname, parts.port
    except ValueError:
        return address, None
    if parts.username is None or host is None:
        return address, None
    shown_host = f"[{host}]" if ":" in host else host
    netloc = f"{shown_host}:{port}" if port else shown_host
    clean = urlunsplit((parts.scheme, netloc, parts.path, parts.query, ""))
    return clean, (unquote(parts.username), unquote(parts.password or ""))


class BrowserSession:
    """One headless Chromium with one context and one active page, launched on demand with an empty profile."""

    def __init__(
        self,
        stand_address: str,
        *,
        action_timeout_ms: int = 10_000,
        http_credentials: tuple[str, str] | None = None,
        proxy_url: str | None = None,
        proxy_bypass: list[str] | None = None,
    ) -> None:
        self._stand_address = stand_address
        self._http_credentials = http_credentials
        self._action_timeout_ms = action_timeout_ms
        self._proxy_url = proxy_url
        self._proxy_bypass = proxy_bypass or []

        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None
        self._started = False

        self.console: deque[str] = deque(maxlen=CONSOLE_LINES)
        self.secret_fields: list[Any] = []
        self.blocked: list[str] = []

    @property
    def browser(self) -> Any:
        return self._browser

    @property
    def page(self) -> Any:
        return self._page

    def broken(self) -> bool:
        """The browser was launched and is gone: a new one must open, and its profile is empty."""
        return self._started and (self._browser is None or not self._browser.is_connected())

    async def start(self) -> None:
        if self._browser is not None:
            return
        try:
            from playwright.async_api import async_playwright

            launch_kwargs: dict[str, Any] = {
                "headless": True,
                "chromium_sandbox": True,
            }
            if self._proxy_url:
                proxy_config: dict[str, str] = {"server": self._proxy_url}
                if self._proxy_bypass:
                    proxy_config["bypass"] = ",".join(self._proxy_bypass)
                launch_kwargs["proxy"] = proxy_config

            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(**launch_kwargs)

            credentials = (
                {"username": self._http_credentials[0], "password": self._http_credentials[1]}
                if self._http_credentials
                else None
            )
            self._context = await self._browser.new_context(
                viewport={"width": 1280, "height": 800},
                locale="ru-RU",
                accept_downloads=False,
                service_workers="block",
                http_credentials=credentials,
            )
            self._context.set_default_timeout(self._action_timeout_ms)
            self._context.set_default_navigation_timeout(max(self._action_timeout_ms, 30_000))
            await self._context.route("**/*", self._route)
            self._context.on("page", self._adopt)
            self._started = True
            await self._context.new_page()
        except Exception as error:
            await self.reset()
            raise BrowserUnavailable(type(error).__name__) from None

    async def ensure_page(self) -> Any:
        await self.start()
        if self._page is None or self._page.is_closed():
            open_pages = [page for page in self._context.pages if not page.is_closed()]
            self._page = open_pages[-1] if open_pages else await self._context.new_page()
        return self._page

    async def reset(self) -> None:
        """Drop the browser. The next `start` opens a new one with an empty profile."""
        context, browser, playwright = self._context, self._browser, self._playwright
        self._context = self._browser = self._playwright = self._page = None
        self._started = False
        self.secret_fields.clear()
        self.console.clear()
        for closer in (
            context.close() if context is not None else None,
            browser.close() if browser is not None else None,
            playwright.stop() if playwright is not None else None,
        ):
            if closer is not None:
                with contextlib.suppress(Exception):
                    await closer

    def remember_secret_field(self, locator: Any) -> None:
        self.secret_fields.append(locator)
        del self.secret_fields[:-SECRET_FIELDS_KEPT]

    def _adopt(self, page: Any) -> None:
        """A page the context opened (e.g. target=_blank): becomes active."""
        self._page = page
        self.secret_fields.clear()
        page.on("console", lambda message: self.console.append(f"[{message.type}] {message.text}"))
        page.on("pageerror", lambda error: self.console.append(f"[pageerror] {str(error).splitlines()[0][:300]}"))
        page.on("dialog", self._on_dialog)

    async def _on_dialog(self, dialog: Any) -> None:
        self.console.append(f"[dialog] {dialog.type}: {dialog.message}")
        with contextlib.suppress(Exception):
            await dialog.accept()

    def _block(self, url: str) -> None:
        origin = origin_of(url)
        self.blocked.append(f"{origin[0]}://{origin[1]}:{origin[2]}" if origin else "другой адрес")

    async def _route(self, route: Any) -> None:
        request = route.request
        if not request.is_navigation_request():
            await route.continue_()
            return
        if stand_url_refusal(self._stand_address, request.url) is not None:
            self._block(request.url)
            await route.fulfill(status=204, body="")
            return

        response = await route.fetch(max_redirects=0, timeout=30_000)
        location = response.headers.get("location")
        if 300 <= response.status < 400 and location:
            target = urljoin(request.url, location)
            if stand_url_refusal(self._stand_address, target) is not None:
                self._block(target)
                await route.fulfill(status=204, body="")
                return
        await route.fulfill(response=response)
