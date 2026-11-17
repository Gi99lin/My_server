# Dify Pilot Implementation Plan

> **For agentic workers:** Use executing-plans for inline execution. This is the owner's explicitly authorized evaluation spike, not a production TMS migration.

**Goal:** Run a private Dify pilot on the agents VM with internal OmniRoute inference and record meaningful integration checks.

**Architecture:** Keep TMS and the existing Claude host operational. Deploy pinned upstream Dify with private access, server-only secrets, and an operator-owned override. Evaluate Dify's APIs and tools before proposing any TMS adapter.

**Tech Stack:** Proxmox VM 150, Docker Compose, Dify 1.18.0, OmniRoute, existing TMS services.

**Spec:** `docs/features/dify-pilot.md`, approved by the owner's setup-and-check request.

## Constraints and review focus

- No production TMS routing change or Claude logout during this trial.
- No secrets or runtime data in Git; initialize owner access before permitting private contour access.
- Check host headroom before raising VM RAM, and confirm existing services recover after restart.
- Preserve upstream files; put pilot customization in separate configuration.
- Verify inference, real tool execution, cancellation/usage where supported, and apps-contour access separately. Report unsupported TMS lifecycle behavior explicitly.

## Tasks

- [x] Capture baseline; raise VM 150 to 6144 MiB RAM and 80 GiB disk, reboot gracefully, grow the filesystem, and verify existing services.
- [x] Install pinned Dify 1.18.0, provision private secrets and access, and bring its services healthy.
- [x] Initialize owner workspace, configure OmniRoute, create disposable pilot apps/tools, and run health/UI/inference/tool/API probes.
- [x] Save non-secret deployment files, update repository resource documentation, record evidence and gaps, and review the final diff.

## Execution notes

The owner explicitly requested trying Dify and running checks; proceed with the pilot without a further design or execution-method approval round. Use existing infrastructure checks and bounded UI/API probes. The repository remains an infrastructure project with `ui: false`; do not create an unrelated browser regression suite or modify Dify's upstream application source.

VM 150 was resized and restarted successfully. Cloud-init expanded the root filesystem automatically and regenerated the SSH host key; its new fingerprint was verified through the trusted Proxmox guest agent before updating the workstation's pinned host entry. Existing Claude/Hermes services recovered. Dify 1.18.0 and its provider plugin are installed, its owner workspace and published pilot agent are configured, and all 16 service images are pinned by digest. Fifteen services are running; the initialization task exited successfully. The Dify Agent server secret must be unpadded base64url; the private environment was corrected after its startup validator rejected padding.

UI, model inference, actual local shell execution, TMS-container API access, usage counters, anonymous access denial, and basic end-user conversation isolation checks passed. The cancellation API acknowledged stop and closed SSE, but the already-running shell command continued and created its marker 18 seconds after stream end. This is recorded as a failed cancellation-boundary check in `dify/ACCEPTANCE.md`; it is not a production TMS replacement claim. A final post-pin request returned `DIFY_PINNED_OK`. The independent final review found no actionable artifact/configuration issues. All six deployment artifact files matched between server and repository. The test browser and temporary authentication file were cleaned up, and the temporary workstation SSH forward was closed. Production TMS routing and Claude authentication remain unchanged.
