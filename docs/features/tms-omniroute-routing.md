---
feature: tms-omniroute-routing
title: Route TMS model calls through the internal OmniRoute gateway
status: draft
source: user request 2026-11-03 to use OmniRoute and cx/gpt-6.1-sol-medium throughout TMS over the local VM network
entry_points: TMS backend and worker configuration, TMS system/team/user AI settings
related: []
code_paths: ai-testcase-generator/docker-compose.yml
updated: 2026-11-03
---

# Route TMS model calls through the internal OmniRoute gateway

## Purpose

TMS on `gigglin-apps` uses OmniRoute on `gigglin-llm` through `http://10.10.60.10:20131/v1`, with model `cx/gpt-6.1-sol-medium`. The connection crosses the existing permitted inter-VM route and requires no public hostname or new firewall rule.

## Main flow

1. The operator supplies a valid TMS-specific OmniRoute API key through server-only secret storage.
2. The operator verifies that the key can access the internal gateway and the requested model.
3. Backend and worker generation configuration, including persisted system/team/user overrides, resolve to the requested internal URL and model.
4. The operator verifies effective settings for TMS users, makes a small real completion request, and confirms service health.
5. Successful non-secret deployment configuration is synchronized into this repository. Credentials and database contents stay on the server.

## Errors and edge cases

- A gateway response of HTTP 401 means the key cannot be used. Do not switch the live generation path until a valid key is available.
- Do not silently retain a Claude-host override for generation after reporting that generation has switched to OmniRoute.
- Do not disable browser agents, autotest authoring, or repair as a side effect of changing generation settings.
- Agent execution currently supports the separate Claude host. The owner chose to reuse that harness and add an OmniRoute model runtime for browser execution, authoring, and repair. OmniRoute supplies model responses only; tools and browser execution remain in the existing harness/TMS.

## Pending deployment requirements

- The supplied replacement key successfully accessed the internal model catalog, which lists `cx/gpt-6.1-sol-medium`. It is stored in a server-only file with mode `0600`; no secret value is included in this document.
- The provider-neutral host design is at `docs/superpowers/specs/2026-11-03-provider-neutral-agent-host-design.md`. This feature remains draft until the owner approves that design. Live TMS settings have not changed.
