"""In-process stand tunnel forward proxy for SDK host browser sessions.

Framework-neutral asyncio HTTP forward proxy listening on 127.0.0.1:0 (ephemeral).
Routes requests for the stand's saved origin to the registered tunnel relay host:port,
preserving browser URL, Host header, cookies, paths, query, and HTTPS SNI/TLS verification.
Mandatory proxying for other destinations routes through operator fixed proxy_url,
while registered non-loopback exact proxy_bypass peers connect directly.
"""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import logging
import ssl
from typing import Any
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

DEFAULT_CONNECT_TIMEOUT = 10.0
DEFAULT_IDLE_TIMEOUT = 60.0
MAX_HEADER_BYTES = 65536


def is_loopback_or_local(host: str) -> bool:
    """Return True if host resolves syntactically to a loopback, unspecified, or link-local address."""
    norm = host.strip("[]").lower().rstrip(".")
    if norm in {"localhost", "ip6-localhost", "ip6-loopback"} or norm.endswith(".localhost"):
        return True
    try:
        addr = ipaddress.ip_address(norm)
        return addr.is_loopback or addr.is_unspecified or addr.is_link_local
    except ValueError:
        return False


def _parse_host_port(netloc: str, default_port: int) -> tuple[str, int]:
    parsed = urlsplit("//" + netloc)
    if (
        not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("invalid_proxy_authority")
    port = parsed.port or default_port
    if not 1 <= port <= 65535:
        raise ValueError("invalid_proxy_port")
    return parsed.hostname.lower(), port


class StandTunnelProxy:
    """In-process forward proxy routing stand traffic to relay and other traffic to parent proxy or bypass."""

    def __init__(
        self,
        stand_url: str,
        tunnel_host: str,
        tunnel_port: int,
        *,
        proxy_url: str | None = None,
        proxy_bypass: list[str] | None = None,
        bind_host: str = "127.0.0.1",
        bind_port: int = 0,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        idle_timeout: float = DEFAULT_IDLE_TIMEOUT,
        max_header_bytes: int = MAX_HEADER_BYTES,
    ) -> None:
        self.stand_url = stand_url
        self.tunnel_host = tunnel_host
        self.tunnel_port = tunnel_port
        self.proxy_url = proxy_url
        self.bind_host = bind_host
        self.bind_port = bind_port
        self.connect_timeout = connect_timeout
        self.idle_timeout = idle_timeout
        self.max_header_bytes = max_header_bytes

        self._bypass_set: set[str] = {
            p.strip().lower() for p in (proxy_bypass or []) if p.strip() and not is_loopback_or_local(p.strip())
        }

        parsed = urlsplit(stand_url)
        self.stand_scheme = (parsed.scheme or "http").lower()
        default_port = 443 if self.stand_scheme == "https" else 80
        self.stand_host = (parsed.hostname or "localhost").lower()
        self.stand_port = parsed.port or default_port
        shown_host = f"[{self.stand_host}]" if ":" in self.stand_host else self.stand_host
        self.stand_netloc = (
            f"{shown_host}:{self.stand_port}"
            if (
                (self.stand_scheme == "http" and self.stand_port != 80)
                or (self.stand_scheme == "https" and self.stand_port != 443)
            )
            else shown_host
        )

        self._server: asyncio.Server | None = None
        self.port: int | None = None
        self._tasks: set[asyncio.Task[Any]] = set()

    @property
    def url(self) -> str:
        if self.port is None:
            raise RuntimeError("StandTunnelProxy is not running")
        return f"http://127.0.0.1:{self.port}"

    async def start(self) -> StandTunnelProxy:
        if self._server is not None:
            return self
        try:
            self._server = await asyncio.start_server(
                self._handle_client,
                self.bind_host,
                self.bind_port,
            )
            self.port = self._server.sockets[0].getsockname()[1]
            return self
        except Exception:
            await self.stop()
            raise

    async def stop(self) -> None:
        server = self._server
        self._server = None
        self.port = None
        if server is not None:
            server.close()
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        if server is not None:
            with contextlib.suppress(Exception):
                await server.wait_closed()

    async def __aenter__(self) -> StandTunnelProxy:
        await self.start()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.stop()

    def _matches_stand(self, scheme: str | None, host: str, port: int) -> bool:
        if scheme is not None and scheme.lower() != self.stand_scheme:
            return False
        norm_host = host.strip("[]").lower()
        norm_stand = self.stand_host.strip("[]").lower()
        return norm_host == norm_stand and port == self.stand_port

    def _is_bypass(self, host: str) -> bool:
        norm_host = host.strip("[]").lower()
        if is_loopback_or_local(norm_host):
            return False
        return norm_host in self._bypass_set

    async def _handle_client(self, client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        if task:
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

        try:
            total_bytes = 0
            header_lines: list[bytes] = []
            while True:
                line = await asyncio.wait_for(client_reader.readline(), timeout=self.idle_timeout)
                if not line:
                    break
                total_bytes += len(line)
                if total_bytes > self.max_header_bytes:
                    client_writer.write(b"HTTP/1.1 431 Request Header Fields Too Large\r\nConnection: close\r\n\r\n")
                    await client_writer.drain()
                    client_writer.close()
                    with contextlib.suppress(Exception):
                        await client_writer.wait_closed()
                    return
                if line in (b"\r\n", b"\n"):
                    break
                header_lines.append(line)

            if not header_lines:
                client_writer.close()
                with contextlib.suppress(Exception):
                    await client_writer.wait_closed()
                return

            req_line = header_lines[0].decode("latin1", errors="replace").rstrip("\r\n")
            parts = req_line.split(" ")
            if len(parts) < 2:
                client_writer.write(b"HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\n")
                await client_writer.drain()
                client_writer.close()
                with contextlib.suppress(Exception):
                    await client_writer.wait_closed()
                return

            method = parts[0].upper()
            target = parts[1]
            http_version = parts[2] if len(parts) > 2 else "HTTP/1.1"

            headers: list[tuple[str, str]] = []
            for hline in header_lines[1:]:
                decoded = hline.decode("latin1", errors="replace").rstrip("\r\n")
                if ":" in decoded:
                    k, v = decoded.split(":", 1)
                    headers.append((k.strip(), v.strip()))

            if method == "CONNECT":
                await self._handle_connect(target, client_reader, client_writer)
            else:
                await self._handle_http(method, target, http_version, headers, client_reader, client_writer)
        except Exception:
            pass
        finally:
            try:
                client_writer.close()
            except Exception:
                pass

    async def _handle_connect(
        self, target: str, client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter
    ) -> None:
        try:
            host, port = _parse_host_port(target, 443)
            if not (1 <= port <= 65535):
                raise ValueError
        except Exception:
            client_writer.write(b"HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\n")
            await client_writer.drain()
            client_writer.close()
            with contextlib.suppress(Exception):
                await client_writer.wait_closed()
            return

        # Case 1: Stand origin -> Tunnel relay
        if self._matches_stand(None, host, port):
            try:
                relay_reader, relay_writer = await asyncio.wait_for(
                    asyncio.open_connection(self.tunnel_host, self.tunnel_port),
                    timeout=self.connect_timeout,
                )
            except Exception:
                logger.warning("Failed connect to tunnel relay for CONNECT")
                client_writer.write(b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n")
                await client_writer.drain()
                client_writer.close()
                with contextlib.suppress(Exception):
                    await client_writer.wait_closed()
                return

            client_writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await client_writer.drain()
            await self._pipe_bidirectional(client_reader, client_writer, relay_reader, relay_writer)
            return

        # Case 2: Loopback outside stand origin -> Refuse immediately
        if is_loopback_or_local(host):
            client_writer.write(b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n")
            await client_writer.drain()
            client_writer.close()
            with contextlib.suppress(Exception):
                await client_writer.wait_closed()
            return

        # Case 3: Exact non-loopback proxy_bypass peer -> Direct
        if self._is_bypass(host):
            try:
                direct_reader, direct_writer = await asyncio.wait_for(
                    asyncio.open_connection(host, port),
                    timeout=self.connect_timeout,
                )
            except Exception:
                logger.warning("Failed direct connect to bypass peer")
                client_writer.write(b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n")
                await client_writer.drain()
                client_writer.close()
                with contextlib.suppress(Exception):
                    await client_writer.wait_closed()
                return

            client_writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await client_writer.drain()
            await self._pipe_bidirectional(client_reader, client_writer, direct_reader, direct_writer)
            return

        # Case 4: Other destination -> Mandatory fixed proxy_url
        if not self.proxy_url:
            client_writer.write(b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n")
            await client_writer.drain()
            client_writer.close()
            with contextlib.suppress(Exception):
                await client_writer.wait_closed()
            return

        proxy_parsed = urlsplit(self.proxy_url)
        p_host = proxy_parsed.hostname or ""
        p_port = proxy_parsed.port or (443 if proxy_parsed.scheme == "https" else 80)
        try:
            parent_reader, parent_writer = await asyncio.wait_for(
                asyncio.open_connection(
                    p_host,
                    p_port,
                    ssl=ssl.create_default_context() if proxy_parsed.scheme == "https" else None,
                    server_hostname=p_host if proxy_parsed.scheme == "https" else None,
                ),
                timeout=self.connect_timeout,
            )
        except Exception:
            logger.warning("Failed connect to parent proxy")
            client_writer.write(b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n")
            await client_writer.drain()
            client_writer.close()
            with contextlib.suppress(Exception):
                await client_writer.wait_closed()
            return

        authority = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
        connect_cmd = f"CONNECT {authority} HTTP/1.1\r\nHost: {authority}\r\n\r\n".encode("latin1")
        parent_writer.write(connect_cmd)
        await parent_writer.drain()

        try:
            parent_resp_line = await asyncio.wait_for(parent_reader.readline(), timeout=self.connect_timeout)
            if not parent_resp_line:
                raise ValueError("empty_parent_response")
            while True:
                pline = await asyncio.wait_for(parent_reader.readline(), timeout=self.connect_timeout)
                if not pline or pline in (b"\r\n", b"\n"):
                    break
            resp_parts = parent_resp_line.split(b" ", 2)
            if len(resp_parts) > 1 and resp_parts[1] == b"200":
                client_writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
                await client_writer.drain()
                await self._pipe_bidirectional(client_reader, client_writer, parent_reader, parent_writer)
            else:
                client_writer.write(parent_resp_line)
                client_writer.write(b"Connection: close\r\n\r\n")
                await client_writer.drain()
                parent_writer.close()
                with contextlib.suppress(Exception):
                    await parent_writer.wait_closed()
                client_writer.close()
                with contextlib.suppress(Exception):
                    await client_writer.wait_closed()
        except Exception:
            client_writer.write(b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n")
            await client_writer.drain()
            parent_writer.close()
            with contextlib.suppress(Exception):
                await parent_writer.wait_closed()
            client_writer.close()
            with contextlib.suppress(Exception):
                await client_writer.wait_closed()

    async def _handle_http(
        self,
        method: str,
        target: str,
        http_version: str,
        headers: list[tuple[str, str]],
        client_reader: asyncio.StreamReader,
        client_writer: asyncio.StreamWriter,
    ) -> None:
        header_map = {k.lower(): v for k, v in headers}
        req_scheme: str | None = None
        req_host: str = ""
        req_port: int = 80
        rel_path: str = target

        if target.startswith("http://") or target.startswith("https://"):
            try:
                parsed = urlsplit(target)
                if not parsed.hostname or parsed.username is not None or parsed.password is not None:
                    raise ValueError
                req_scheme = parsed.scheme.lower()
                req_host = parsed.hostname.lower()
                req_port = parsed.port or (443 if req_scheme == "https" else 80)
                rel_path = parsed.path or "/"
                if parsed.query:
                    rel_path += f"?{parsed.query}"
            except Exception:
                client_writer.write(b"HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\n")
                await client_writer.drain()
                client_writer.close()
                with contextlib.suppress(Exception):
                    await client_writer.wait_closed()
                return
        else:
            if not (target.startswith("/") or target == "*"):
                client_writer.write(b"HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\n")
                await client_writer.drain()
                client_writer.close()
                with contextlib.suppress(Exception):
                    await client_writer.wait_closed()
                return
            host_hdr = header_map.get("host", "")
            if not host_hdr:
                client_writer.write(b"HTTP/1.1 400 Bad Request\r\nConnection: close\r\n\r\n")
                await client_writer.drain()
                client_writer.close()
                with contextlib.suppress(Exception):
                    await client_writer.wait_closed()
                return
            req_host, req_port = _parse_host_port(host_hdr, self.stand_port)
            rel_path = target

        is_stand = self._matches_stand(req_scheme, req_host, req_port)

        # Loopback check: non-stand loopback is refused
        if not is_stand and is_loopback_or_local(req_host):
            client_writer.write(b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n")
            await client_writer.drain()
            client_writer.close()
            with contextlib.suppress(Exception):
                await client_writer.wait_closed()
            return

        is_bypass = not is_stand and self._is_bypass(req_host)

        if is_stand:
            connect_host = self.tunnel_host
            connect_port = self.tunnel_port
            forward_target = rel_path
        elif is_bypass:
            connect_host = req_host
            connect_port = req_port
            forward_target = rel_path
        else:
            if not self.proxy_url:
                client_writer.write(b"HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n")
                await client_writer.drain()
                client_writer.close()
                with contextlib.suppress(Exception):
                    await client_writer.wait_closed()
                return
            proxy_parsed = urlsplit(self.proxy_url)
            connect_host = proxy_parsed.hostname or ""
            connect_port = proxy_parsed.port or (443 if proxy_parsed.scheme == "https" else 80)
            if target.startswith("http://") or target.startswith("https://"):
                forward_target = target
            else:
                scheme = req_scheme or "http"
                netloc = f"{req_host}:{req_port}" if req_port != (443 if scheme == "https" else 80) else req_host
                forward_target = f"{scheme}://{netloc}{rel_path}"

        try:
            target_reader, target_writer = await asyncio.wait_for(
                asyncio.open_connection(
                    connect_host,
                    connect_port,
                    ssl=ssl.create_default_context()
                    if not is_stand and not is_bypass and proxy_parsed.scheme == "https"
                    else None,
                    server_hostname=connect_host
                    if not is_stand and not is_bypass and proxy_parsed.scheme == "https"
                    else None,
                ),
                timeout=self.connect_timeout,
            )
        except Exception:
            logger.warning("Failed connect to HTTP destination")
            client_writer.write(b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n")
            await client_writer.drain()
            client_writer.close()
            with contextlib.suppress(Exception):
                await client_writer.wait_closed()
            return

        out_headers: list[str] = [f"{method} {forward_target} {http_version}"]
        has_host = False
        is_websocket = header_map.get("upgrade", "").lower() == "websocket"

        for k, v in headers:
            kl = k.lower()
            if kl == "proxy-authorization":
                continue
            if kl == "host":
                out_headers.append(f"{k}: {v}")
                has_host = True
            elif kl in {"connection", "proxy-connection"}:
                if is_websocket and kl == "connection":
                    out_headers.append(f"{k}: {v}")
            else:
                out_headers.append(f"{k}: {v}")

        # One HTTP request per local proxy connection. Without this, a peer that
        # keeps HTTP/1.1 alive leaves this streaming handler waiting for EOF and
        # the next browser fetch stalls on that same connection.
        if not is_websocket:
            out_headers.append("Connection: close")

        if not has_host:
            default_host = self.stand_netloc if is_stand else req_host
            out_headers.append(f"Host: {default_host}")

        req_bytes = "\r\n".join(out_headers).encode("latin1") + b"\r\n\r\n"
        target_writer.write(req_bytes)
        await target_writer.drain()

        # Stream request body if present
        try:
            content_length = int(header_map.get("content-length", "0"))
        except ValueError:
            content_length = 0

        if content_length > 0:
            remaining = content_length
            while remaining > 0:
                chunk = await client_reader.read(min(remaining, 65536))
                if not chunk:
                    break
                target_writer.write(chunk)
                remaining -= len(chunk)
            await target_writer.drain()
        elif header_map.get("transfer-encoding", "").lower() == "chunked":
            while True:
                line = await client_reader.readline()
                target_writer.write(line)
                chunk_size_str = line.split(b";")[0].strip()
                try:
                    chunk_size = int(chunk_size_str, 16)
                except ValueError:
                    break
                if chunk_size == 0:
                    trailer = await client_reader.readline()
                    target_writer.write(trailer)
                    await target_writer.drain()
                    break
                chunk_data = await client_reader.readexactly(chunk_size + 2)
                target_writer.write(chunk_data)
                await target_writer.drain()

        if is_websocket:
            resp_headers: list[bytes] = []
            while True:
                rline = await asyncio.wait_for(target_reader.readline(), timeout=self.idle_timeout)
                if not rline:
                    break
                client_writer.write(rline)
                if rline in (b"\r\n", b"\n"):
                    break
                resp_headers.append(rline)
            await client_writer.drain()
            if resp_headers and b"101" in resp_headers[0]:
                await self._pipe_bidirectional(client_reader, client_writer, target_reader, target_writer)
                return

        try:
            while True:
                data = await asyncio.wait_for(target_reader.read(65536), timeout=self.idle_timeout)
                if not data:
                    break
                client_writer.write(data)
                await client_writer.drain()
        finally:
            target_writer.close()
            with contextlib.suppress(Exception):
                await target_writer.wait_closed()
            client_writer.close()
            with contextlib.suppress(Exception):
                await client_writer.wait_closed()

    async def _pipe_bidirectional(
        self,
        r1: asyncio.StreamReader,
        w1: asyncio.StreamWriter,
        r2: asyncio.StreamReader,
        w2: asyncio.StreamWriter,
    ) -> None:
        async def forward(src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
            try:
                while True:
                    data = await asyncio.wait_for(src.read(65536), timeout=self.idle_timeout)
                    if not data:
                        break
                    dst.write(data)
                    await dst.drain()
            except Exception:
                pass
            finally:
                try:
                    dst.close()
                    await dst.wait_closed()
                except Exception:
                    pass

        t1 = asyncio.create_task(forward(r1, w2))
        t2 = asyncio.create_task(forward(r2, w1))
        self._tasks.add(t1)
        self._tasks.add(t2)
        t1.add_done_callback(self._tasks.discard)
        t2.add_done_callback(self._tasks.discard)
        await asyncio.gather(t1, t2, return_exceptions=True)
