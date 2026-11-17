---
feature: awg-encrypted-dns
title: Encrypted public DNS for the HomeLab AWG client
status: draft
source: user request 2026-11-08
entry_points: 10.10.99.1:1053 over AWG
related:
code_paths: infra/openwrt-router/sing-box.config.example.json
updated: 2026-11-08
---

# Encrypted public DNS for the HomeLab AWG client

The Mac can use the HomeLab tunnel for DNS on any network that can reach its AWG endpoint. It keeps access to private HomeLab names while public lookups use encrypted DNS over the existing Kazakhstan proxy.

- The endpoint is available over UDP and TCP on the router's AWG address. It accepts only the Mac's AWG peer address, `10.10.99.2`.
- `router.home.arpa` resolves to `192.168.1.13`. HomeLab and LAN suffixes and their private reverse zones are resolved by the router's local DNS.
- A public lookup, such as `www.youtube.com`, uses Cloudflare DoH through the existing Kazakhstan proxy. If this proxy is unavailable, the lookup fails without retrying over plaintext DNS.
- The endpoint is opt-in. The existing router DNS listener on port 53 and other VLAN routing continue to use their existing policies.
- To roll back, switch the Mac's WireProxy DNS forwards back to OpenWrt port 53 and restore the router's previous sing-box configuration.
