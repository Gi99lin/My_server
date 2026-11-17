# Nextcloud (`gigglin-personal`, VM 120)

Owner-only personal cloud at `https://cloud.gigglin.tech`, deployed with
[`docker-compose.yml`](./docker-compose.yml) on `gigglin-personal`
(`/home/gigglin/My_server/nextcloud`). User data lives on the 4 TB HDD at
`/srv/nextcloud-data` and is backed up nightly to Backblaze B2 (see
[`backup/`](../backup)).

## Personal hub apps

Nextcloud doubles as the owner's personal hub: calendar, tasks, notes and
project files, operated by Claude through a local MCP server on the Mac.
Behavior: [`docs/features/personal-hub.md`](../docs/features/personal-hub.md).
MCP setup: [`mcp/README.md`](./mcp/README.md).

Installed from the app store on 2026-11-17:

| App | Version | Role |
|---|---|---|
| `calendar` | 6.6.5 | Events (CalDAV) |
| `tasks` | 0.18.1 | The single task store (CalDAV `VTODO`, synced to Reminders) |
| `notes` | 5.0.2 | Markdown notes under `Notes/` |

Deck is intentionally not installed: it would be a second task store.

Reinstall or upgrade:

```bash
ssh gigglin-personal 'for a in calendar tasks notes; do docker exec -u www-data nextcloud php occ app:install $a || docker exec -u www-data nextcloud php occ app:update $a; done'
```
