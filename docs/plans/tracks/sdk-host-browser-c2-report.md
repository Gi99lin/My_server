# Browser Lane Cycle 2: TMS Tunnel Contract Implementation Report

## Summary of Changes

Implemented browser producer integration for TMS cycle 83 localhost stand tunneling in `claude-sdk-host`:

1. **`claude_host.credentials.CredentialProviderClient`**:
   - Preserved three-tuple return compatibility `(grant_id, values, expires_at)` from `redeem()`.
   - Validated optional `tunnel` descriptor: must be a dictionary with strictly `{"port"}` key, positive non-bool integer port in `[1, 65535]`. Rejects arbitrary host, extra fields, or invalid types with `CredentialError("invalid_tunnel_descriptor")`.
   - Exposed read-only `tunnel_port` property.

2. **`claude_host.tunnel_proxy.StandTunnelProxy`**:
   - Implemented framework-neutral in-process HTTP forward proxy binding on `127.0.0.1:0` (ephemeral).
   - Routes requests matching the saved stand origin exclusively to the registered relay `tunnel_host:tunnel_port`, preserving original Host header, path, query, cookies, and TLS SNI/certificate verification without rewriting stand URL.
   - Preserves mandatory forward proxying for other destinations through the operator's fixed `proxy_url` (both absolute HTTP requests and CONNECT tunnels).
   - Allows registered non-loopback exact `proxy_bypass` peers direct connectivity without wildcard/suffix/CIDR interpretation.
   - Refuses loopback direct attempts outside stand with `HTTP 403 Forbidden`.
   - Bounded header size (64KB), connection timeouts (10s), and idle timeouts (60s). Safe logging without headers, URIs, bodies, or tokens.
   - Full lifecycle management: `stop()` cleanly cancels active client and piping tasks and closes server listening sockets.

3. **`claude_host.browser.BrowserSession`**:
   - Accepts optional `tunnel_host` and `tunnel_port`.
   - Spawns and manages `StandTunnelProxy` on localhost when tunneling is configured.
   - Sets Playwright proxy to `http://127.0.0.1:{ephemeral_port}` with `"<-loopback>"` in bypass list to disable Chromium's implicit loopback bypass while keeping the local proxy accessible and un-bypassed.
   - `reset()` guarantees closing of `StandTunnelProxy` and associated tasks across all normal and partial-start failure paths.

4. **`claude_host.sdk_tools.SessionTools`**:
   - Validates redeemed tunnel metadata against operator settings in `start()` before Chromium launch.
   - Requires valid `tunnel_host` (non-loopback registered peer) and `tunnel_port` within `[tunnel_port_min, tunnel_port_max]`.
   - Fails closed with `RunFailure` if loopback origin lacks tunnel metadata, if relay is unconfigured/loopback, or if port is out-of-range.
   - Preserves standard direct behavior for non-loopback stand origins without tunnel metadata.
   - Keeps Basic HTTP authentication bound to original stand origin.

## Observed Manual Verification Assertions

Tested using local asyncio fake relay and parent proxy servers with host venv (`Python 3.12.13`):

- **(a) Localhost HTTP Origin Mapping**:
  - Request: `GET http://localhost:3000/api/items?cat=tools&page=2 HTTP/1.1` with `Host: localhost:3000`, `Cookie: sid=abc123secret`.
  - Observed: Routed to relay server `127.0.0.1:<relay_port>` as `GET /api/items?cat=tools&page=2 HTTP/1.1` with `Host: localhost:3000` and `Cookie: sid=abc123secret` preserved. Response returned cleanly.
  - Assertion (a) PASS.

- **(b) External HTTP via Parent Proxy**:
  - Request: `GET http://api.external.org/v1/resource?id=99 HTTP/1.1` with `Host: api.external.org`.
  - Observed: Forwarded in absolute-form to configured parent proxy `http://127.0.0.1:<parent_port>` as `GET http://api.external.org/v1/resource?id=99 HTTP/1.1` with `Host: api.external.org`. Response returned cleanly.
  - Assertion (b) PASS.

- **(c) Stand CONNECT and External CONNECT**:
  - Stand CONNECT: `CONNECT localhost:3000 HTTP/1.1` connected to relay server, received `200 Connection Established`, bidirectional byte pipe exchanged `PING_RELAY` / `PONG`.
  - External CONNECT: `CONNECT secure.external.com:443 HTTP/1.1` forwarded CONNECT to fake parent proxy, received `200 Connection Established`, bidirectional byte stream relayed data.
  - Assertion (c) PASS.

- **(d) Missing/Invalid Port/Relay/Loopback Direct Refused**:
  - Non-stand loopback direct `GET http://127.0.0.1:8080/secret` returned `HTTP 403 Forbidden`.
  - Non-stand loopback direct `CONNECT 127.0.0.1:8080` returned `HTTP 403 Forbidden`.
  - `tunnel: {"port": True}` rejected by `CredentialProviderClient` with `invalid_tunnel_descriptor`.
  - `tunnel: {"port": "42001"}` rejected with `invalid_tunnel_descriptor`.
  - `tunnel: {"port": 42001, "host": "attacker"}` rejected with `invalid_tunnel_descriptor`.
  - Loopback origin without tunnel metadata rejected by `SessionTools.start()` with `RunFailure("missing_tunnel_metadata")`.
  - Out-of-range port `43000` (max 42999) rejected with `RunFailure("tunnel_port_out_of_range")`.
  - Unconfigured relay `tunnel_host` rejected with `RunFailure("invalid_tunnel_relay")`.
  - All invalid paths fail closed before Chromium startup.
  - Assertion (d) PASS.

- **(e) Stop/Cancel Cleanup**:
  - Active client connection held open; `StandTunnelProxy.stop()` cancels active client tasks, gathers without deadlock, closes listening server socket, and resets port to `None` with `_tasks` count 0.
  - `BrowserSession.reset()` cleans up and stops `StandTunnelProxy` on teardown / partial-start.
  - Assertion (e) PASS.
