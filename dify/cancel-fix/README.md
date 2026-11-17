# Dify 1.18.0 cancellation patch

This pilot patch fixes shell job lifetime and cancellation propagation through a quiet backend event stream. It changes only `layers/shell/layer.py` and `server/sse.py` in a separately built Agent Backend image. Dify's API, workers, databases, model provider, credentials, and production TMS routing are unchanged.

## Deployed build

- Base: `langgenius/dify-agent-backend@sha256:80d638d7114bb0fbe954952e37da1f464b61969ff870c0b173963b9f2b91e06e`.
- Upstream source: tag `1.18.0`, commit `50abea97062110044f15d0e03ccecadd9ccc87ca`.
- Local build tag: `dify-agent-backend:1.18.0-cancel-fix-20261103-r5`.
- Deployed immutable local image ID: `sha256:b948cf0ab13f1a52526fc69afc03aa17a91824e6dbb184634cc56d95c3d8d493`.
- Patched shell source SHA-256: `2d7d8729bafeda7cd882598819e2adbfdfe15c6055985356376cc8397933c3ac`.
- Patched SSE source SHA-256: `075cdf842b66d9439cbd89eac4a4cc9e723b546e1c3697914e25b7f20d0cbd12`.
- Runtime user remains `dify`; no package dependencies or container privileges were added.

`compose.cancel-fix.yml` pins a local image ID with `pull_policy: never`. It is not a downloadable registry reference. Build or load the image before using that override. After rebuilding on another machine, record the resulting local image ID and update the override deliberately.

## Behavior

1. Start a shell job with a valid 1 ms poll so its handle is available before waiting for output. Shield and finish this creation/registration step if cancellation arrives before the reply.
2. Preserve the caller's initial-wait and output behavior after registration. Keep creation and forced cleanup accounted for despite repeated cancellation.
3. Force termination of tracked unfinished jobs without a grace window when the shell layer exits. This covers a first cancellation during normal-end cleanup. Completed output and exit status are preserved.
4. Send existing SSE comment keepalives every 0.5 seconds instead of 15 seconds. The existing API-side client checks its stop callback when text arrives, before discarding comment frames. Event IDs, replay, and business payloads are unchanged.

The fourth change is essential: the shell-only candidate passed direct runtime checks but failed the published API reproduction because cancellation was not forwarded promptly during a silent command. That candidate was rolled back before the combined fix was accepted.

The keepalive change bounds stop observation on a healthy, flowing connection. It does not add transport-independent cancellation or recovery from an unreachable sandbox. Existing Community Edition isolation limitations and the separate TMS integration gaps still apply.

## Rebuild

Use a fresh detached source worktree; do not modify the pinned upstream checkout or packages inside a running container.

```bash
git -C /home/gigglin/services/dify-pilot/upstream worktree add --detach \
  /home/gigglin/services/dify-pilot/cancel-fix-rebuild 1.18.0
git -C /home/gigglin/services/dify-pilot/cancel-fix-rebuild apply --check \
  /home/gigglin/My_server/dify/cancel-fix/shell-cancellation.patch
git -C /home/gigglin/services/dify-pilot/cancel-fix-rebuild apply \
  /home/gigglin/My_server/dify/cancel-fix/shell-cancellation.patch
docker build --network=none \
  -f /home/gigglin/My_server/dify/cancel-fix/Dockerfile \
  -t dify-agent-backend:1.18.0-cancel-fix-rebuild \
  /home/gigglin/services/dify-pilot/cancel-fix-rebuild/dify-agent/src/dify_agent
```

The Dockerfile verifies original and patched source hashes. Keep the original cached image for rollback. No registry publication is required for this pilot.

## Checks

The original existing baseline passed 78 checks. Added process-lifetime regressions failed against the original image, and the idle-stream regression failed against the shell-only candidate. Final validation passed **99 checks**:

- Existing shell, Shellctl adapter, command-runner, agent-runner, and SSE checks.
- Real disposable subprocess checks for creation cancellation, initial waiting, repeated cancellation, cleanup, late first cancellation, SIGTERM-ignoring children, and normal output/exit status.
- Seven checks against the real authenticated sandbox, with a descendant independently confirmed alive before cancellation.
- An idle-stream check showing the real keepalive wakes the existing client stop callback without adding business events.

Tests run in disposable containers using the candidate image, `pytest==9.0.3` installed into an isolated test-dependency directory, and the pinned upstream tests. Mount the upstream `dify-agent/tests` at `/checks/tests`, the local `test_*.py` files at `/checks`, and set `PYTHONPATH=/testdeps:/checks`. Live checks additionally use `dify-pilot_agent_sandbox_network` and the server-only sandbox service token mounted read-only at `/run/sandbox-token`. Never copy that token into this directory.

The final pytest targets are:

```text
tests/local/dify_agent/layers/shell
tests/local/dify_agent/adapters/shell
tests/local/dify_agent/runtime/test_command_runner.py
tests/local/dify_agent/runtime/test_runner.py
tests/local/dify_agent/server/test_sse.py
test_cancellation.py
test_live_cancellation.py
test_heartbeat_cancellation.py
```

Run `python3 check_published_api.py` on `gigglin-agents` for the complete published API regression. It reads the pilot app key from private operator storage, uses a disposable conversation, and records actual heartbeat intervals, backend cancellation receipt, cleanup completion, and delayed-write absence. A stop acknowledgment or public stream closure alone does not pass this check.

Observed final result: 0.5-second keepalive intervals; cancellation received by the backend 1.455 seconds after the public stop request; `run_cancelled` after cleanup at 1.479 seconds; no delayed child write. Detailed private evidence is `cancel-fix-published-result.json` and `cancel-fix-r5-all.log` in the operator directory.

## Deploy and roll back

The server-only `COMPOSE_FILE` ends with `/home/gigglin/My_server/dify/cancel-fix/compose.cancel-fix.yml`. After confirming no active pilot runs, normal deployment is:

```bash
cd /home/gigglin/services/dify-pilot/upstream/docker
docker compose -p dify-pilot config --quiet
docker compose -p dify-pilot up -d --no-deps agent_backend
```

To roll back persistently, replace only that final override path in the private `compose.env` with `/home/gigglin/My_server/dify/cancel-fix/compose.rollback.yml`, then run the same commands. The rollback override restores the original pinned image. Preserve all other environment values and all volumes. A private pre-change environment backup also exists as `compose.env.before-cancel-fix-20261103`; do not restore the whole backup over later secret rotations or unrelated configuration changes.

Rollback configuration and original image availability were validated; the original image was also restored successfully after the incomplete shell-only candidate failed its API check. Only Agent Backend is recreated by this rollout. Production TMS and the Claude host remain unchanged.
