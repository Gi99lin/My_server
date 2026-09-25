# GitHub Actions runner — self-hosted, for the TMS

A self-hosted GitHub Actions runner for [`Gi99lin/ai-testcase-generator`](https://github.com/Gi99lin/ai-testcase-generator)
(the TMS), built because the repository's GitHub-hosted CI used its entire
2,000-minute monthly allowance in six days. It runs three containers -
`docker-compose.yml` has the full picture of each and why - and never
touches the host's own Docker daemon or its other containers:

- **`runner-dind`** — a Docker-in-Docker engine of its own, so CI can build
  images and run compose stacks without going anywhere near
  `/var/run/docker.sock` on the host.
- **`runner`** — the GitHub Actions runner, built from
  [`myoung34/github-runner`](https://github.com/myoung34/docker-github-actions-runner)'s
  `ubuntu-noble` image plus the packages a few CI steps run directly on the
  runner assume (`postgresql-client`, `python-is-python3`,
  `python3-openpyxl` — `Dockerfile` in this directory has the reason for
  each), talking only to `runner-dind`'s engine.
- **`runner-pruner`** — cleans `runner-dind`'s own image/volume store on a
  schedule, so a long-lived CI cache cannot fill the host's disk.

Labels: `self-hosted`, `linux`, `x64`, `tms`. The TMS's
`.github/workflows/ci.yml` targets exactly this set.

## 1. Create the real `.env`

```bash
cd ~/My_server/github-runner
cp env.example .env
```

`REPO_URL`, `RUNNER_NAME` and `LABELS` are already correct for this
deployment in `env.example`. Only `RUNNER_TOKEN` needs filling in, and it
should never be typed or pasted by hand - see step 2.

## 2. Get a registration token and start it

A registration token from the GitHub API is valid for about an hour and is
only used once, to register the runner for the first time; it must never be
printed, logged or committed. From a machine with a `gh` CLI authenticated
against this repo (`repo` + `workflow` scopes), pipe it straight into the
server's `.env` over `ssh` — it never touches a local file, terminal, or
shell history on either end:

```bash
gh api -X POST repos/Gi99lin/ai-testcase-generator/actions/runners/registration-token --jq .token \
  | ssh gigglin-server 'umask 077; read -r TOKEN && printf "RUNNER_TOKEN=%s\n" "$TOKEN" >> ~/My_server/github-runner/.env'
```

Then, on the server:

```bash
cd ~/My_server/github-runner
docker compose up -d --build
docker compose logs -f runner   # watch for "Runner successfully added" / "Listening for Jobs"
```

Confirm it registered, from anywhere with `gh`:

```bash
gh api repos/Gi99lin/ai-testcase-generator/actions/runners --jq '.runners[] | {name, status, labels: [.labels[].name]}'
```
Expect `"status": "online"` and labels including `tms`.

## 3. Updating

```bash
cd ~/My_server/github-runner
git pull   # from ~/My_server
docker compose up -d --build
```

The registration is persisted in the `runner-persist` volume
(`CONFIGURED_ACTIONS_RUNNER_FILES_DIR` in `docker-compose.yml`), so a
rebuild or restart reuses it — no new token needed, and `RUNNER_TOKEN` in
`.env` is not re-read after the first successful registration.

## Rotating the registration

Needed only if the runner must be fully re-registered (its name or labels
changed, or the persisted state is suspected stale) — not for an ordinary
update or host reboot, which steps 3 and "Persistence across a host reboot"
already cover.

```bash
cd ~/My_server/github-runner
docker compose down
docker volume rm github-runner_runner-persist
```

Then repeat step 2 with a fresh token. The old registration is left behind
in GitHub's runner list until it is removed there too — `gh api -X DELETE
repos/Gi99lin/ai-testcase-generator/actions/runners/<id>` (find `<id>` from
the `gh api .../actions/runners` call in step 2) — or it will show as
offline indefinitely.

## Persistence across a host reboot

`restart: unless-stopped` brings all three containers back after a Docker or
host restart, and the registration survives in `runner-persist` exactly as
in step 3 — nothing further to do.

## What this touches, and what it never does

- Everything it creates lives in `~/My_server/github-runner/` (this
  directory: `dind-data`, `runner-work`, `runner-tmp` and `runner-persist`
  are this compose project's own named volumes) or inside `runner-dind`'s
  own Docker engine. It never reads or writes the host's
  `/var/run/docker.sock`, and never starts, stops or prunes any container,
  image, network or volume outside this compose project.
- `runner-pruner` prunes only `runner-dind`'s own store (`DOCKER_HOST:
  tcp://runner-dind:2375`) — never the host's.
- CPU and memory are capped per container (`mem_limit` / `cpus` in
  `docker-compose.yml`) so a CI job cannot starve the host's other services;
  only one job runs at a time (one runner, one queue), so the caps are sized
  for the heavier of the e2e or release stacks, not both at once.
- All three images are pinned by digest, and `runner-dind` /
  `runner-pruner` are matched to the host's Docker major version (29.x) for
  the closest client/server API compatibility.

## Why the work directory and `/tmp` are shared volumes

`runner` and `runner-dind` are separate containers with separate
filesystems; only their network namespace is shared. When a CI job runs
`docker compose` (e.g. `make e2e-up`, `make release-smoke`), that command
runs as `runner`'s own client process, but the *daemon* doing the actual
work — resolving bind-mount sources, writing layers — is `runner-dind`'s
engine. A relative bind mount such as `docker-compose.e2e.yml`'s
`./backend/tests/fixtures/keycloak` gets resolved to an absolute path by the
client (under the checked-out repo, inside the runner's work directory) and
sent to the daemon as-is; if that path does not also exist inside
`runner-dind`, the mount fails with "no such file or directory". The same
is true of paths release-smoke and the e2e Makefile targets create under
`/tmp` (a throwaway `mktemp -d` for release-smoke's TLS cert/key, and the
e2e OIDC secrets file). Mounting the same `runner-work` and `runner-tmp`
volumes at the same absolute paths (`/work`, `/tmp`) in both containers is
what makes every such path resolve identically on both sides.
