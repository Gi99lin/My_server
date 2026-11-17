# Nextcloud MCP (local, stdio)

Lets Claude (Claude Desktop, the Code tab, the `claude` CLI) operate the
personal hub on `https://cloud.gigglin.tech` — calendar, tasks, notes, files.
Behavior and rules: [`docs/features/personal-hub.md`](../../docs/features/personal-hub.md).

## Pieces

| File | Role |
|---|---|
| `nextcloud-mcp-stdio.sh` | Wrapper. Reads the app password from the Keychain and `exec`s `uvx nextcloud-mcp-server==0.213.1 run --transport stdio` with only the `calendar` (incl. tasks), `notes` and `webdav` APIs. Installed as `~/.local/bin/nextcloud-mcp` (symlink). |
| `smoke-test.sh` | Sends MCP `initialize` + `tools/list` and expects `serverInfo` and calendar tools. |

## Credentials

- Nextcloud user: `admin` (the owner). App password name: `claude-mcp (Mac)`.
- Keychain: service `HomeLab nextcloud-mcp`, account `admin`. Set or replace:
  `security add-generic-password -U -s "HomeLab nextcloud-mcp" -a admin -w`
- Revoke: Nextcloud → Personal settings → Security → Devices & sessions →
  `claude-mcp (Mac)` → Revoke. Claude loses access immediately.

## Registration

- Claude Code (user scope): `claude mcp add --scope user nextcloud -- ~/.local/bin/nextcloud-mcp`
- Claude Desktop: `"nextcloud": {"command": "/Users/ivanakimkin/.local/bin/nextcloud-mcp"}` under
  `mcpServers` in `~/Library/Application Support/Claude/claude_desktop_config.json`.

## Checks

```bash
nextcloud/mcp/smoke-test.sh                 # PASS: Nextcloud MCP with 49 tools
NEXTCLOUD_MCP_USER=nobody ~/.local/bin/nextcloud-mcp </dev/null  # exit 1, clear stderr
```

## Capability check (2026-11-17, server 0.213.1)

Run against throwaway `zz-test-*` data, removed afterwards.

| Operation | Result | Notes |
|---|---|---|
| Create / delete task lists | ✅ | `nc_calendar_manage_calendar` `create` / `delete` |
| Task with due date, priority, description | ✅ | Pass `due` with an explicit offset (owner's Mac is `+02:00`); a naive time is stored as UTC |
| Subtasks | ❌ | No `RELATED-TO` support; use a checklist in the description instead |
| Move a task between lists | ⚠️ | No move tool; create in the target list, then delete the original (new UID) |
| Complete a task | ✅ | `nc_calendar_complete_todo` |
| Read `LAST-MODIFIED` (stale rule) | ❌ | Not exposed by any tool |
| Notes in a category | ✅ | Notes folder is `Заметки/` (localized), categories are subfolders |
| Files: create / list / delete folder | ✅ | WebDAV paths are relative to the user root |
| Calendar event | ✅ | |
