# Two-parent SDK egress failover

Owner requested two identical SOCKS5 parents and automatic reserve selection on failure. Both endpoints answered the unauthenticated SOCKS5 method negotiation with username/password mode; no credential was sent during that probe. The user-supplied credentials must stay outside Git/arguments/output and never appear in this document.

Use pinned GOST v2's existing node-group `ip` selector with `strategy=fifo`, `max_fails=1`, `fail_timeout=30s` and bounded connect retries. Two ChainNodes would mean two sequential hops and are not the requested behavior. Keep one chain hop with two explicit numeric peers sharing protocol/auth settings. No application/session/query replay is added; an already established broken stream remains a failure.

Tasks:
1. Validate the secret GOST config structurally with only the four supported group query keys. Reject duplicates, files/hostnames, wildcard/direct/bypass, unsupported schemes and unbounded retries. Never print a URL or credential.
2. Expose plural upstream IPs while preserving the existing single-parent environment variable. Restrict the egress namespace to the registered parent IPs/ports only; validate config endpoints against that list.
3. Exercise primary healthy, primary down -> reserve, cooldown/recovery, both down -> failure and no direct escape in an isolated local stack. Use fake credentials for failure injection.
4. Store the supplied operational config outside Git using a non-echoed input channel, validate actual SOCKS auth without printing it, then prepare the guarded local owner-login flow. No server deployment or paid model call before owner login.

Primary sources: https://v2.gost.run/en/load-balancing/ and pinned v2.11.5 upstream implementation. No new custom routing service is needed.


## Implementation decision and evidence

Review of pinned v2.11.5 source showed its FIFO marker does not cover a SOCKS final-target CONNECT failure when the parent TCP/auth handshake succeeds. Rather than maintain a custom proxy fork, use current official GOST3.3.2 (release metadata verified) with native whole-chain probes and chainGroup FIFO selection. Preserve the existing narrow operator input through a strict normalizer; runtime structure is generated and never copied from arbitrary input fields.

Local fake SOCKS acceptance passed: healthy primary; primary TCP listener alive but CONNECT rejected -> reserve (2 checks); primary container stopped -> reserve; both chains unavailable -> failure plus IPv4/metadata/DNS direct denial; recovered primary selected again (5 checks). A POST whose payload reached the primary and whose stream was dropped did not reach the reserve; its application-request counter remained unchanged. Nine unsafe configuration variants were rejected without printing a URL/credential. Both real user-provided parent auth handshakes passed, with operational files written outside Git via non-echoed stdin; no supplied credential is in source or process arguments. No paid model call was made.

Focused independent read-only review found no high-confidence P1/P2 issue in normalization, secret suppression, endpoint allowlisting or request replay. Actual model/login test remains pending the owner's official interactive login; no server operation was performed.

## Explicit both-parent outage on the real local contour

At the owner's request, verified the current four-service local deployment with both configured parent IPs/ports temporarily rejected in the egress namespace **before** established-connection acceptance. The added counter observed actual packets. No remote proxy or server was changed.

Observed assertions:
- Explicit HTTP CONNECT through the forwarder fails when both parents are blocked.
- Direct TCP IPv4/IPv6, metadata, TCP DNS, Docker DNS, DoT and direct access to the parent endpoints fail from the application namespace.
- UDP DNS, QUIC-port and other UDP sends are synchronously denied, rather than being treated as blocked merely because no reply arrived.
- A child worker with a scrubbed environment and no proxy variables cannot bypass the policy.
- Real sandboxed Chromium fails both with its configured proxy and with all proxy environment removed/direct connection attempted.
- The forwarder's own uplink cannot connect directly to an arbitrary Internet destination.
- Internal loopback API remains reachable; losing both parents does not shut down allowed internal traffic.

The temporary block was removed in `finally`, probe files were removed from the container, and a subsequent proxied HTTPS public GET succeeded. No paid model request was made. The implementation required no additional code change: both host and forwarder namespaces already enforce default-drop independently of proxy availability.
