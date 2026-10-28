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
