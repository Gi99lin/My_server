"""SSE entrypoint for telegram-mcp.

The upstream main.py runs the MCP server over stdio, which doesn't work
in a Docker sidecar scenario where OpenClaw communicates via HTTP/SSE.

This entrypoint:
1. Imports the MCP app and Telegram clients from main.py
2. Parses proxy settings from OPENCLAW_PROXY_URL (Telethon needs explicit proxy config)
3. Connects all configured Telegram clients
4. Warms entity caches (StringSession has no persistent cache)
5. Starts a raw ASGI SSE server via Uvicorn on 0.0.0.0:8932
"""

import asyncio
import json
import sys
import os
from urllib.parse import urlparse

import nest_asyncio
nest_asyncio.apply()

from main import mcp, clients, _configure_allowed_roots_from_cli


# ---------------------------------------------------------------------------
# Proxy helpers
# ---------------------------------------------------------------------------

def _parse_proxy():
    """Parse OPENCLAW_PROXY_URL into a Telethon-compatible proxy dict.

    Telethon ignores HTTP_PROXY/HTTPS_PROXY env vars because it uses
    raw TCP (MTProto), not HTTP.
    """
    proxy_url = os.getenv("OPENCLAW_PROXY_URL", "").strip()
    if not proxy_url:
        return None

    parsed = urlparse(proxy_url)
    if not parsed.hostname or not parsed.port:
        print(f"[sse_entrypoint] WARNING: Could not parse proxy URL: {proxy_url}", file=sys.stderr)
        return None

    scheme = (parsed.scheme or "http").lower()

    import python_socks
    if scheme in ("socks5", "socks5h"):
        proxy_type = python_socks.ProxyType.SOCKS5
    elif scheme in ("socks4", "socks4a"):
        proxy_type = python_socks.ProxyType.SOCKS4
    else:
        proxy_type = python_socks.ProxyType.HTTP

    proxy = {
        'proxy_type': proxy_type,
        'addr': parsed.hostname,
        'port': parsed.port,
        'rdns': True,
    }
    if parsed.username:
        proxy['username'] = parsed.username
    if parsed.password:
        proxy['password'] = parsed.password

    print(f"[sse_entrypoint] Proxy configured: {scheme}://{parsed.hostname}:{parsed.port}", file=sys.stderr)
    return proxy


def _apply_proxy_to_clients(proxy):
    """Patch all Telegram clients to use the proxy before connecting."""
    if not proxy:
        return
    for name, client in clients.items():
        client._proxy = proxy
        print(f"[sse_entrypoint] Proxy applied to client '{name}'", file=sys.stderr)


# ---------------------------------------------------------------------------
# Telegram client bootstrap
# ---------------------------------------------------------------------------

async def _start_clients():
    """Connect all discovered Telegram clients and warm caches."""
    labels = ", ".join(clients.keys())
    print(f"[sse_entrypoint] Starting {len(clients)} Telegram client(s) ({labels})...", file=sys.stderr)
    await asyncio.gather(*(cl.start() for cl in clients.values()))

    print("[sse_entrypoint] Warming entity caches...", file=sys.stderr)
    await asyncio.gather(*(cl.get_dialogs() for cl in clients.values()))

    print(f"[sse_entrypoint] Telegram client(s) ready ({labels}).", file=sys.stderr)


# ---------------------------------------------------------------------------
# Raw ASGI app (bypasses Starlette routing — no _send issues)
# ---------------------------------------------------------------------------

def _build_asgi_app():
    """Build a raw ASGI application serving MCP over SSE.

    Uses SseServerTransport directly with raw ASGI scope/receive/send
    to avoid Starlette version compatibility issues with request._send.
    """
    from mcp.server.sse import SseServerTransport

    sse_transport = SseServerTransport("/messages/")

    # Resolve the underlying MCP server instance
    mcp_server = getattr(mcp, '_mcp_server', None) or getattr(mcp, 'server', None)
    if mcp_server is None:
        raise RuntimeError("Cannot find MCP server instance on FastMCP object")

    async def app(scope, receive, send):
        if scope["type"] != "http":
            return

        path = scope.get("path", "")

        if path == "/sse":
            async with sse_transport.connect_sse(scope, receive, send) as (
                read_stream,
                write_stream,
            ):
                await mcp_server.run(
                    read_stream,
                    write_stream,
                    mcp_server.create_initialization_options(),
                )

        elif path.startswith("/messages"):
            await sse_transport.handle_post_message(scope, receive, send)

        elif path == "/health":
            body = json.dumps({"status": "ok"}).encode()
            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [[b"content-type", b"application/json"]],
            })
            await send({"type": "http.response.body", "body": body})

        else:
            await send({
                "type": "http.response.start",
                "status": 404,
                "headers": [],
            })
            await send({"type": "http.response.body", "body": b"Not Found"})

    return app


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def _main_sse():
    """Start clients, then run SSE server."""
    try:
        proxy = _parse_proxy()
        _apply_proxy_to_clients(proxy)
        await _start_clients()

        host = os.getenv("MCP_SSE_HOST", "0.0.0.0")
        port = int(os.getenv("MCP_SSE_PORT", "8932"))

        print(f"[sse_entrypoint] Starting MCP SSE server on {host}:{port}...", file=sys.stderr)

        app = _build_asgi_app()

        import uvicorn
        config = uvicorn.Config(app, host=host, port=port, log_level="info")
        server = uvicorn.Server(config)
        await server.serve()

    except Exception as e:
        print(f"[sse_entrypoint] Fatal error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        try:
            await asyncio.gather(
                *(cl.disconnect() for cl in clients.values()), return_exceptions=True
            )
        except Exception:
            pass


def main():
    _configure_allowed_roots_from_cli(sys.argv[1:])
    asyncio.run(_main_sse())


if __name__ == "__main__":
    main()
