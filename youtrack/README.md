# YouTrack Server — task engine for Mission Control

Self-hosted YouTrack (free tier: up to 10 users) used as the single task
database. Tasks are managed by the `hermes-tasks` agent (see
[`../hermes/hermes-tasks/SETUP.md`](../hermes/hermes-tasks/SETUP.md) for the
full runbook) and via UI/mobile at `https://tracker.gigglin.tech`.

## Install
```bash
./install.sh          # creates dirs (uid 13001), docker compose up, prints next steps
```

## Preset ("Mission Control")
`bootstrap/bootstrap_youtrack.py` — idempotent, stdlib-only. Creates:
- Projects **WORK / LIFE / PROJ**
- States: Backlog → Next → In Progress → Waiting → Someday → Done / Dropped
- Fields: **Sphere** (сферы Компаса), **Size**, **Energy**, **Due**
- Tags: `agent`, `needle-mover`, `bot-test`
- Agile board **Mission Control** (set swimlanes = Sphere + WIP limit 3 manually)
- Imports the current backlog from `bootstrap/seed_tasks.json`
  (exported 2026-07-15 from the Obsidian kanban boards)

```bash
# .env: YT_URL + YT_TOKEN (Profile → Account Security → Tokens)
python3 bootstrap/bootstrap_youtrack.py
```

## Notes
- Image pinned via `YT_VERSION` in `.env` (upgrades: bump tag, `docker compose up -d`;
  YouTrack migrates data on start — make a backup first: Admin → Backup).
- JVM app, `mem_limit: 3g`. Check free RAM before enabling.
- Host port `8899` is only needed for the initial wizard; afterwards NPM
  proxies `tracker.gigglin.tech` → `youtrack:8080` over the shared network.
