# Nextcloud Personal Hub — Design

Date: 2026-11-17
Status: approved by the owner on 2026-11-17 (Tasks lists + Reminders, no Deck)

## Intent and why

The owner wants Nextcloud (`cloud.gigglin.tech`, `gigglin-personal`, VM 120)
to become the single place for tasks, calendar, notes and project files.

Two earlier attempts failed for the same reason, and it was not the tool:

- **Obsidian** with many plugins and automations collapsed because the setup
  itself needed constant care.
- **YouTrack** for tasks collapsed because tasks piled up, went stale and were
  never triaged. A Telegram bot with the Hermes agent in front of it felt
  bolted on, not native.

What is different now is that an agent can do the upkeep. The owner wants to
be a **consumer** of the system, not its maintainer: Claude (Claude Desktop
chat, the Code tab, the CLI) reads and edits Nextcloud natively through MCP and
keeps the system tidy. The owner accepts that changing tools does not fix root
causes, and wants to start small and fix causes as they show up — specifically
at the moments the owner feels like abandoning the system.

## Goals

1. Nextcloud has working calendar, tasks and notes, plus a project structure
   for files.
2. Claude can create, read, update and close tasks, events and notes, and work
   with files, through an MCP server, from any Claude surface on the Mac.
3. Global Claude memory explains what the hub is, how it is laid out, and the
   upkeep rules, so any session uses it without being told.
4. Upkeep is the agent's job: triage of new items, a weekly review, and
   retiring stale tasks.
5. The owner's day-to-day tools on the Mac and iPhone see the same data
   without a browser where possible.

## Non-goals (this project)

- Migrating files and notes that are lying around the Mac (and Apple Notes)
  into the hub. That is phase 2 and gets its own brainstorm once the
  structure exists and has been lived in for a while.
- A remote (internet-facing) MCP server for claude.ai web or the iPhone app.
  That is a later phase; the same MCP server is reused, so nothing here is
  thrown away.
- Migrating old YouTrack issues or the Obsidian vault.
- A custom-built MCP server.

## Anti-goals (failure even if it technically works)

- The owner has to maintain the system by hand: plugins to update, tags to
  curate, boards to groom.
- Tasks pile up stale with nobody looking at them.
- Two places to keep tasks, so neither is trusted.
- The agent deletes or rewrites the owner's data without asking.

## Constraints

- Nextcloud 32.0.8 in Docker on `gigglin-personal`, compose in
  [`nextcloud/`](../../../nextcloud). Data on the 4 TB HDD
  (`/srv/nextcloud-data`, 3.4 TB free). Currently installed non-shipped apps:
  Talk, Duplicate Finder, Files Archive.
- VLAN 20 egress goes through `proxy-failover` (fail-closed); the app store
  must be reachable through it for app installs.
- Nextcloud is already covered by the nightly Restic backups (DB dump + data
  directory), so calendar, tasks (DB) and notes (files) are backed up without
  extra work.
- Credentials never go into the repo or into memory. The MCP app password is
  stored in the macOS Keychain.
- **The hub is personal only.** Work (corporate) tasks, notes and files never
  go into it; they stay in the corporate contour. The agent does not move work
  material into the hub even when asked casually; it points this rule out
  first. *(Owner's decision.)*
- **The agent acts as the owner's own Nextcloud account** with a dedicated app
  password, with full access, because phase 2 needs it. The safety rules
  below are what limit it. *(Owner's decision.)*
- The owner creates credentials themselves (app password, CalDAV account on
  the Mac/iPhone); the agent does not type passwords.

## Approaches considered

1. **Ready-made MCP server on the Mac over stdio** — chosen by the owner.
   `cbcoutinho/nextcloud-mcp-server` (Python, run through `uvx`) covers Notes,
   Calendar and tasks (CalDAV), Files (WebDAV), Contacts and Deck. Talks to
   `https://cloud.gigglin.tech` with a dedicated, revocable app password.
   No new internet-facing surface, nothing to run on the server, ~15 minutes
   to set up. Works only where the Mac is on.
2. **Same server hosted on `gigglin-personal` as a remote MCP**, the way
   `mcp-tg.gigglin.tech` is hosted. Reachable from the iPhone and claude.ai,
   but adds a public entry point to private data, plus auth, an NPM host and
   upkeep. Deferred to a later phase.
3. **Own MCP server** — rejected: it is exactly the kind of maintenance that
   killed the previous systems.

## Design

### Nextcloud apps

- **Calendar** — events.
- **Tasks** — the **single** place for tasks. Tasks are CalDAV `VTODO`s, so
  they also show up natively in macOS/iOS Reminders, which gives quick capture
  from the phone (including Siri) without any custom bot. *(Agent's call.)*
- **Notes** — Markdown notes stored as files under `Notes/`, so they are
  readable by any Markdown editor and by the Files sync client.
- **Deck** is **not** installed. A kanban board next to Tasks would be a
  second task store (anti-goal). *(Agent's call; can be revisited.)*

### Layout

*(Agent's call, kept deliberately small.)*

- **Task lists (CalDAV calendars with tasks):** `Inbox` plus one list per
  active project or life area. New, unsorted tasks always land in `Inbox`.
- **Notes:** `Notes/<Project>/…` (Notes app categories = subfolders), same
  project names as the task lists.
- **Files:** `Projects/<Project>/…` for project files; `Archive/` for finished
  projects.
- The initial project list is drafted by the agent from what it knows about
  the owner's work, and the owner corrects it once. After that the agent
  creates and archives projects as they come and go.

### MCP connection

- `nextcloud-mcp-server` runs locally via `uvx`, pinned to a specific
  version, over stdio.
- A small wrapper script reads the app password from the Keychain and starts
  the server, so the secret is never written into a config file.
- Registered in both Claude Desktop (`claude_desktop_config.json`) and
  Claude Code (user scope), so chat, the Code tab and the CLI all see it.
- The app password belongs to the owner's own Nextcloud account (the agent
  acts as the owner). It is named so it can be found and revoked in one click.

### Agent upkeep rules (written into global memory)

- **Capture:** anything the owner mentions as a to-do goes into `Inbox`
  without asking, with a one-line confirmation.
- **Triage:** when the owner opens a "what's on my plate" kind of
  conversation, the agent first sorts `Inbox` into projects, sets due dates
  where they were said, and asks only about genuinely ambiguous items.
- **Weekly review:** once a week the agent prepares a short review: what got
  done, what is overdue, what has not moved in 3 weeks. Stale tasks are
  proposed for closing or archiving in a single batch; the owner answers once.
- **Safety:** the agent never deletes notes, files or events without
  confirmation; it prefers archiving and moving. Destructive MCP tools are
  confirmed one by one.
- **Abandonment signals:** when the owner says they feel like dropping the
  system, the agent writes the reason into a `Notes/Hub/Retro` note and
  proposes one concrete fix for that cause, instead of a new tool.

### Mac and iPhone clients

*(Agent's call; the owner sets up accounts since they involve passwords.)*

- **Files:** Nextcloud Desktop client on the Mac (virtual files mode, so the
  4 TB of data are not downloaded).
- **Calendar and tasks:** CalDAV account in macOS/iOS Internet Accounts →
  native Calendar and Reminders.
- **Notes:** read through the synced `Notes/` folder or the Nextcloud Notes
  iOS app; editing is mostly done by the agent anyway.
- No separate custom Mac app.

## Calls made after the builder check

These are the agent's calls; the owner can overturn any of them.

- **MCP feature gaps.** Before anything else, the plan verifies that the
  chosen server can create task lists, move a task between lists, and keep due
  dates, priority and subtasks intact. If something is missing, the fallback
  is another ready-made server (for example `Jaypeg-dev/nextcloud-mcp`). A
  thin custom tool is used only for the one missing operation and only with
  the owner's OK.
- **Stale signal.** A task counts as stale when its `LAST-MODIFIED` is older
  than 21 days. The plan checks that edits made in Reminders update it.
- **Weekly review when the Mac is off.** A Claude Desktop scheduled task runs
  the review. In any "what's on my plate" conversation, the agent also checks
  when the last review ran and runs it first if it is more than 7 days old.
  The date of the last review is kept in `Notes/Hub/Reviews`.
- **Existing Apple Reminders.** They stay where they are until phase 2. The
  default Reminders list on the Mac and iPhone is set to the Nextcloud
  `Inbox`, so new items captured on the phone land in the hub.
- **Keychain prompt.** A one-time "Always Allow" for the wrapper script is
  accepted.
- **Network path.** `cloud.gigglin.tech` is public, so the MCP server needs
  no VPN. The plan checks that it works with Proxifier on and off.
- **Seed projects.** The agent drafts the project list in chat, and the owner
  corrects it once before anything is created.

## Left to the builder

- Exact MCP server version, and whether some of its tools (Deck, Contacts,
  Cookbook, …) are disabled to keep Claude's tool list short.
- The weekly review trigger: a scheduled task in Claude Desktop or a reminder
  in the owner's calendar that starts the conversation.
- Where the wrapper script lives and how the repo documents it (README,
  feature doc in `docs/features/`).
- Verifying that the app store is reachable through the VLAN 20 proxy, and
  installing the apps with `occ`.
