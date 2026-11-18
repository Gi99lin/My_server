---
feature: personal-hub
title: Nextcloud personal hub operated by Claude
status: approved
source: owner request 2026-11-17; design docs/superpowers/specs/2026-11-17-nextcloud-personal-hub-design.md approved the same day
entry_points: Claude Desktop chat, Claude Code (Code tab and CLI) via the nextcloud MCP server; macOS/iOS Reminders and Calendar; https://cloud.gigglin.tech (Calendar, Tasks, Notes, Files)
related: centralized-offsite-backup
code_paths: nextcloud/mcp/, nextcloud/README.md
updated: 2026-11-17
---

# Nextcloud personal hub operated by Claude

## Purpose

The owner keeps personal tasks, events, notes and project files in one place,
`cloud.gigglin.tech`, and does not maintain the system by hand. Claude captures,
sorts and reviews items through MCP, and the owner just uses the result.

## Actors and permissions

- **Owner**: sees and edits everything in Nextcloud's web UI, Reminders and
  Calendar on the Mac and iPhone, and through Claude.
- **Claude**: acts as the owner's Nextcloud account with the app password
  `claude-mcp (Mac)`. It works only from the owner's Mac, where the MCP server
  runs.
- Revoking `claude-mcp (Mac)` in Settings → Security → Devices & sessions
  cuts Claude off immediately without touching anything else.

## Entry points

- Claude conversations: Claude Desktop chat, the Code tab, the `claude` CLI.
- macOS/iOS **Reminders** (CalDAV account for `cloud.gigglin.tech`, default
  list `Inbox`) and **Calendar**.
- Nextcloud web apps: **Calendar**, **Tasks**, **Notes**, **Files**.

## Layout

- Task lists: `Inbox` plus one list per vector: Нетворкинг, Международка с SaaS,
  ТМС рынок КЗ, Нотариус, Танки, ТМС через мфлеш, Компания КЗ, Рутина.
- Notes: `Заметки/<Project>/…` (the Notes app's localized folder);
  hub housekeeping in `Заметки/Hub/Retro` and `Заметки/Hub/Reviews`.
- Files: `Projects/<Project>/…`; finished projects move to `Archive/`.

## Main flow

1. **Capture.** The owner mentions something to do in any Claude conversation
   ("remind me to renew the domain on Friday"). Claude creates a task in
   `Inbox`, with the due date if one was said, and replies with one line, for
   example: "Added to Inbox: Renew the domain — due Fri 21 Nov."
2. **Capture from the phone.** The owner adds a reminder by voice or in
   Reminders. It lands in `Inbox` and is visible to Claude within 2 minutes.
3. **Triage.** When the owner opens a "what's on my plate" conversation,
   Claude first moves every `Inbox` task into a project list. It asks only
   about tasks whose project is genuinely unclear, and then answers the
   question.
4. **Weekly review.** Every Monday at 10:00 a scheduled Claude task prepares
   a review with three parts:
   - what was completed in the last 7 days;
   - what is overdue;
   - what is stale.
   Stale tasks are offered as one batch ("close / archive / keep"), and the
   owner answers once. The review date is written to the first line of
   `Заметки/Hub/Reviews` as `Last review: YYYY-MM-DD`.
5. **Retro.** When the owner says they feel like dropping the system, Claude
   records the date and the reason in `Заметки/Hub/Retro` and proposes one
   concrete fix for that cause.

## Alternative flows

- **Missed review.** The Mac was off on Monday, so the review did not run.
  In the next "what's on my plate" conversation, Claude sees that the
  `Last review` date is more than 7 days old and runs the review first.
- **New project.** The owner starts something new. Claude creates the task
  list, the `Заметки/<Project>` category and the `Projects/<Project>/` folder
  under the same name.
- **Finished project.** Claude proposes moving it to `Archive/`. The move
  happens only after the owner confirms.

## Validation and business rules

- Personal only. Work (corporate) tasks, notes and files are never stored.
  If asked to file a work item, Claude declines and says the hub is
  personal-only.
- No invented structure: task lists are the owner's business vectors plus
  `Нетворкинг`, with no Business/Life split. Claude never adds due dates, goals
  or schedules the owner did not state, and does not push targets onto life
  outside these lists. At most it keeps a guidepost the owner named (for
  example "sleep 8 hours").
- There is exactly one task store: Nextcloud Tasks (CalDAV). There are no
  Deck boards.
- A stale task is an open task whose last modification is more than 21 days
  old.
- Claude never deletes a task, note, file or event without the owner's
  explicit confirmation of that item. It prefers completing, archiving or
  moving. Archiving a task sets it to CANCELLED in its list; archiving a
  project moves its folders to `Archive/`.
- Moving a task between lists keeps its title, description, priority, dates,
  categories and reminders. A recurring task, or one with details that can't
  be copied, stays in `Inbox` and Claude asks.
- The stale check only looks at the hub's own lists, never at lists other
  users share or the default calendar.
- In a plain Claude Desktop chat (no shell) Claude uses a time zone the owner
  stated or a date-only due date, and says the stale check needs Claude Code.
- Claude never closes stale tasks on its own. The weekly review only
  proposes them.

## Errors and edge cases

- **The app password is missing from the Keychain or was revoked.** The MCP
  server fails to start or returns 401. Claude tells the owner that Nextcloud
  access is not working and names the app password `claude-mcp (Mac)` as the
  likely cause. It does not retry in a loop.
- **`cloud.gigglin.tech` is unreachable** (server or network down). Claude
  says so, and for capture it offers to remember the item in the conversation
  and file it once Nextcloud is back.
- **An empty `Inbox` during triage.** Claude skips triage silently and
  answers the question.
- **An ambiguous due date** ("sometime next week"). The task is created
  without a due date, and the wording is kept in the description.

## Data

- A valid capture: "remind me to renew gigglin.tech on Friday". This creates
  the task "Renew gigglin.tech" in `Inbox`, due on the coming Friday.
- A rejected capture: "add the bank's quarterly report task". It is refused
  under the personal-only rule.
