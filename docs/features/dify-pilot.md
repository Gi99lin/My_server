---
feature: dify-pilot
title: Evaluate Dify on the agents contour
status: approved
source: owner request 2026-11-03 to set up and check a Dify trial; subsequent approval to patch the shell cancellation race, test it, and deploy with rollback
entry_points: private Dify console, published pilot app API
related: tms-omniroute-routing
code_paths: dify/
updated: 2026-11-03
---

# Evaluate Dify on the agents contour

## Purpose

The owner can evaluate Dify as a reusable agent platform before deciding whether to replace the current TMS Claude runtime. Future customer delivery is a possibility, not a requirement for this pilot.

## Main flow

1. Deploy a pinned Dify release on `gigglin-agents`, increasing its VM resources within available Proxmox capacity.
2. Initialize a private owner workspace and keep access credentials outside the repository.
3. Configure the internal OmniRoute endpoint `http://10.10.60.10:20131/v1` and exact model `cx/gpt-6.1-sol-medium` with the owner-supplied server-only API key.
4. Verify the console, service health, model generation, tool execution, and API access from the TMS contour using disposable pilot data.
5. Record the actual results and remaining integration gaps before any production TMS cutover.

## Rules

- OmniRoute provides inference only; Dify or the existing trusted execution service runs tools.
- Preserve the existing TMS production route and Claude authentication during evaluation. Claude retirement follows a successful replacement, not merely a successful Dify installation.
- Do not add a public Dify endpoint. Use private contour access and/or an SSH forward.
- Keep credentials, secret files, database data, and Dify runtime volumes outside Git. Version only reproducible non-secret deployment configuration and the acceptance record.
- Respect the agents contour's existing strict proxy routing. Internal OmniRoute access uses the existing permitted inter-contour route.
- Do not report existing TMS browser-tool integration as complete based only on a model response or a generic tool check.
- Stopping a pilot agent while its shell command is starting or running must terminate the associated shell job; closing the response stream alone is insufficient.
- The cancellation fix must preserve normal command output, completion status, and the requested initial-wait behavior. Creation must remain accounted for even if cancellation arrives before the job ID is returned.
- Layer exit forcefully terminates tracked unfinished shell jobs without a grace window. This also covers a first cancellation arriving after the handler has returned and cleanup has started; completed command output and exit status are preserved.
- On a healthy idle backend event connection, keepalive data must wake the API client's existing stop check within two seconds, without inventing business events or changing replay IDs. The published API check must verify backend cancellation receipt and cleanup, not only the public stop acknowledgment.
- Deploy the fix as a separate image over the pinned upstream Agent Backend. Preserve the original image and a complete Compose rollback path; do not edit packages in the running container.

## Failures

- Failed inference or tools must produce a recorded failed check, not a successful end-to-end TMS integration claim.
- Missing provider plugins or unsupported API behavior remain explicit pilot findings.
- Startup or resource changes must not strand existing contour services after the VM restart.
