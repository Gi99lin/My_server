# Dify pilot acceptance record

Date: 2026-11-03. Scope: an internal evaluation, not a production TMS migration.

## Deployed environment

- Dify Community Edition `1.18.0`, upstream commit `50abea97062110044f15d0e03ccecadd9ccc87ca`; 16 service images pinned by digest.
- Agent Backend was subsequently replaced with the separately built, immutable local cancellation-fix image `sha256:b948cf0ab13f1a52526fc69afc03aa17a91824e6dbb184634cc56d95c3d8d493`. See [the patch record](cancel-fix/README.md) for build, checks, and rollback.
- `gigglin-agents`, Proxmox VM 150: 4 vCPU, 6144 MiB RAM, 80 GiB root disk. Existing Claude/Hermes services recovered after the resource-change reboot.
- Private console: `http://agents.home.arpa:8080`, plus host loopback port `18080`. No public proxy entry was created.
- Internal provider: `http://10.10.60.10:20131/v1`, selected model alias `cx/gpt-6.1-sol-medium`.
- Published pilot agent: `TMS Dify Pilot`, ID `01a1a0b0-66b7-7175-a045-ee18798441c1`.

## Results

| Check | Result | Observed evidence |
| --- | --- | --- |
| Resource resize and service recovery | PASS | VM reports about 5.8 GiB usable RAM and a 79 GiB filesystem; old agents services are running. Proxmox still reports about 3.2 GiB available. |
| Pinned deployment | PASS | 15 services running; one-time `init_permissions` exited with code 0. API, PostgreSQL, Redis, code sandbox, and local agent sandbox health checks passed. The digest-pinned rollout completed, setup remained HTTP 200, and a post-rollout agent request returned `DIFY_PINNED_OK`. All six deployment artifact files matched between server and repository. |
| Console and workspace | PASS | Native browser check reached sign-in, authenticated Studio, agent list, and configured published agent. Owner account and workspace were initialized. |
| Gateway text and tool protocol | PASS | Direct internal inference returned `DIFY_PILOT_OK`; a local `pilot_add` tool round trip returned `42`, with usage for both model turns. |
| Dify agent generation | PASS | Published app returned `DIFY_AGENT_OK` through SSE, then `message_end`; reported 2221 prompt + 8 completion = 2229 tokens. |
| Actual Dify tool execution | PASS | Agent invoked `shell_run`, calculated 19 + 23, wrote and read its own workspace file, and returned `DIFY_TOOL_OK=42`. The file was independently read from the local sandbox. Reported 4817 total tokens. |
| Actual TMS container access | PASS | A probe executed inside `testcase-backend` reached Dify app info with HTTP 200 and received `TMS_DIFY_OK` from the published agent, with 2228 total tokens reported. This is connectivity/API compatibility evidence, not a production adapter. |
| Anonymous access denial | PASS | Published app info and console model-provider endpoints returned HTTP 401 without credentials. |
| Basic end-user conversation isolation | PASS | Requesting another pilot user's conversation through the same app API key returned HTTP 404. This is one bounded check, not a complete multi-tenant security assessment. |
| Cancel request and stream termination | PASS | Stop endpoint returned HTTP 200 with `result=success` in 0.01 seconds; the SSE stream ended without a final answer. |
| Stop an already-running shell action | PASS after patch | Originally failed: a delayed write appeared 18 seconds after public stream closure. The final patched published-API check confirmed a live descendant before stop, backend cancellation receipt after 1.455 seconds, cleanup-complete `run_cancelled` after 1.479 seconds, and no delayed child write. |
| Idle cancellation propagation | PASS after patch | Actual comment keepalives observed from the API container at 0.5-second intervals; the API-side client can now notice its stop flag during silent execution. Business events and replay IDs are unchanged. |
| Patch regression coverage | PASS | 99 existing and added deterministic/real-sandbox checks passed. Source hashes and the deployed image ID were verified. |

The cancellation probes used only disposable pilot workspaces. The original failure showed that a successful stop response or public stream closure does not prove process termination. The final test additionally verifies backend receipt and cleanup. This fixes the tested pilot path on healthy connections; it does not establish transport-independent cancellation, multi-tenant isolation, or replacement of the current TMS execution contract.

## Integration gaps and edition observations

- Production TMS generation, browser execution, authoring, repair, credential leases, and usage receipt/ACK processing remain on their existing configuration. No TMS source or production model routing was changed.
- TMS's trusted browser tools and per-job credential handoff are not yet integrated into Dify. Their authorization, redaction, evidence, budgets, replay behavior, and cancellation need a dedicated adapter and acceptance work.
- The new Agent UI marks Preview as Cloud/Enterprise-only. The published Agent API worked in this Community deployment.
- The Community UI explicitly describes limited sandbox isolation and shared process/capability boundaries. Future customer deployment needs a separate isolation assessment; this pilot does not establish that boundary.
- Token counts were returned. Dify's monetary prices are zero because custom-provider pricing has not been configured; do not interpret them as zero upstream cost.
- QA Lab feature-case generation returned HTTP 500. The feature documentation is saved, but generated regression cases were unavailable. This infrastructure repository has `ui: false`; no browser regression suite was created.

## Evidence and operations

Detailed probe JSON and deployment logs stay on `gigglin-agents` in `/home/gigglin/.config/dify-pilot`, with private access. Relevant non-secret result filenames include `agent-generation-events.json`, `agent-tool-events.json`, `agent-cancel-result.json`, `agent-cancel-side-effects.json`, and `isolation-result.json`. That directory also holds credentials, so it must not be copied into Git wholesale.

Routine Compose commands retain the pinned images and private access configuration through `COMPOSE_FILE` in the server-only environment. Preserve volumes and the private environment during restart. Keep the existing Claude runtime available until a replacement passes the actual TMS execution contracts.

The independent artifact/configuration review found no actionable issues. The operator's native test browser, temporary workstation authentication-state file, and temporary SSH forward were closed or removed after verification. Private VPN console access remains available.
