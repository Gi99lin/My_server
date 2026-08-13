# monitoring

Prometheus + cAdvisor + node-exporter + Grafana for the whole server — not
scoped to one project. cAdvisor and node-exporter read straight from the
host (`/sys`, `/var/lib/docker`, `/proc`), so this sees every container on
the box, and any project can point its own tooling at Grafana over
`my_server_proxy_network` by container name (`grafana:3000`) without needing
a host port.

Originally built inside the `workInfra` project (an alerting agent needed
something real to query) and moved here once it became clear it belonged at
the server level.

## Setup

```bash
cp .env.example .env
# edit .env — set GRAFANA_ADMIN_PASSWORD at minimum
docker compose up -d
```

## Access

| What | Where |
|---|---|
| Grafana | `https://grafana.gigglin.tech` (once the NPM proxy host + DNS are set), or `http://127.0.0.1:3020` on the box / via SSH tunnel |
| Prometheus | `http://127.0.0.1:9090` on the box / via SSH tunnel — no public route, nothing external needs to query it directly |

Default dashboard: **Server → Host & Containers Overview** — host CPU/memory/disk, plus per-container CPU/memory (legended by image, since cAdvisor only sees raw container IDs on this Docker version, not the human names Docker itself assigns — a containerd-snapshotter quirk, not a bug here).

## Adding a datasource for your project

Grafana can query more than Prometheus — Postgres, MySQL, Loki, etc. are all
built-in datasource types. If your project wants a dashboard:

1. Get your service's container onto `my_server_proxy_network` (add it
   alongside whatever network it already uses — see any other project's
   `docker-compose.yml` here for the pattern).
2. Add a read-only credential scoped to what Grafana actually needs to read
   — never hand Grafana a service's full-privilege role.
3. Add the datasource in Grafana's UI, or drop a provisioning file in
   `grafana/provisioning/datasources/` and restart Grafana.

For scraping a project's own app metrics instead, add a `scrape_configs` job
to `prometheus/prometheus.yml` pointing at that project's `/metrics`
endpoint (needs the project's container on `monitoring_network`, not just
`proxy_network`, since Prometheus itself doesn't sit on the shared network).

## Consumers

- **workInfra**'s `agentkit` queries this Grafana for its stress-test
  alerting agent (`GRAFANA_URL=http://grafana:3000` in workInfra's `.env`,
  with `agentkit` joined to `my_server_proxy_network`).

## Notes

- `cadvisor` needs `--containerd` / `--containerd-namespace=moby` **and**
  `--docker_only=true` together on this host — this Docker runs on the
  containerd snapshotter, not the legacy overlay2 graphdriver (check with
  `docker info | grep driver-type`), which makes cAdvisor log "failed to
  identify the read-write layer ID" for every container and report only the
  root cgroup without the containerd flags. `--docker_only=true` looked like
  it might be the opposite problem at one point (a standalone test without
  it seemed to fix things), but that test was checking for the wrong thing —
  absence of an empty `name=""` label, which also matches lines that have no
  `name` label at all — and removing it for real does not fix anything; it
  only adds every systemd slice and VM on the host to what cAdvisor tracks
  (a QEMU Windows VM under libvirt showed up). Verified properly — actual
  non-empty label values extracted, then confirmed present in Prometheus via
  its JSON API — with both flags set together: 72 containers reporting.
  `--store_container_labels=false` and `--disable_metrics=disk,diskIO` are
  unrelated, there for cAdvisor's own benefit.
- Grafana's auth for scripted access (like agentkit) is currently HTTP Basic
  with the admin login (`GRAFANA_ADMIN_USER`/`GRAFANA_ADMIN_PASSWORD`), not a
  service account token — fine for a single-operator box, worth upgrading to
  a scoped service account if more consumers start relying on this.
