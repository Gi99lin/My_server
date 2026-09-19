# MCP Telegram Cloud — self-hosted, single-operator mode

Self-hosted instance of [mcp-telegram/mcp-telegram-cloud](https://github.com/mcp-telegram/mcp-telegram-cloud),
running the [`SINGLE_OPERATOR_MODE`](https://github.com/mcp-telegram/mcp-telegram-cloud/pull/20)
fork build: an admin-login gate replaces the public multi-tenant OAuth flow,
so only this deployment's operator can register an MCP client — anyone else
hitting the URL gets bounced to the admin login, never a QR code.

- **Domain**: `mcp-tg.gigglin.tech`
- **MCP endpoint**: `https://mcp-tg.gigglin.tech/mcp`
- **Image**: `ghcr.io/gi99lin/mcp-telegram-cloud:latest`, built by the fork's
  own CI on every push to its `main` — Watchtower here just pulls it, same
  as `manager-helper`.

## 1. Create the real `.env`

```bash
cd ~/My_server/mcp-telegram
cp env.example .env
```

Fill in:
- `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` — from https://my.telegram.org/apps.
- `ADMIN_TOKEN`, `SESSION_ENCRYPTION_KEY`, `ADMIN_USERNAME`, `ADMIN_PASSWORD_HASH` —
  already generated for this deployment; ask in chat for the values if you
  don't have them saved.

`ISSUER`, `PORT`, `BRAND_NAME`, `SINGLE_OPERATOR_MODE=true` are already
filled in `env.example` for this deployment.

## 2. Start it

```bash
cd ~/My_server/mcp-telegram
docker compose up -d
docker compose logs -f mcp-telegram-cloud   # watch for a clean boot
```

No build step — the image is pulled from GHCR.

## 3. Nginx Proxy Manager — proxy host

In the NPM admin panel (`:81`):
1. **Proxy Hosts → Add Proxy Host**
2. Domain: `mcp-tg.gigglin.tech`
3. Forward Hostname/IP: `mcp-telegram-cloud`, Forward Port: `3000` (container
   is on `my_server_proxy_network`, same as `manager-helper`)
4. **SSL** tab: request a new Let's Encrypt certificate, force SSL, enable HTTP/2

## 4. DNS

Add an **A record** `mcp-tg` → `128.0.130.144` (the server's public IP,
same as the other `*.gigglin.tech` hosts) at your DNS provider. This zone
isn't wildcarded, so nothing resolves until this record exists.

## 5. First login — bootstrap the admin's Telegram account

1. Visit `https://mcp-tg.gigglin.tech/oauth/authorize` (or just register the
   MCP connector in Claude Code and let it drive you there) — you'll land on
   `/admin-login`.
2. Log in with `ADMIN_USERNAME` / the admin password (not the hash — the
   plaintext you were given when the hash was generated).
3. You'll be dropped on the QR bootstrap page exactly once — scan it with
   your own Telegram account. After that, every future login (new MCP
   client, new device) only needs the admin login, no more QR scans.

## 6. Point the MCP client at the new instance

Once `https://mcp-tg.gigglin.tech/health` returns 200 and step 5 is done,
update the MCP server entry that currently points at the public hosted
instance — e.g. in Claude Code's `~/.claude.json`:

```json
"telegram-hosted": {
  "type": "http",
  "url": "https://mcp-tg.gigglin.tech/mcp"
}
```

(was `https://mcp.mcp-telegram.com/mcp`).

## Flipping SINGLE_OPERATOR_MODE off later — don't, without cleanup

If this ever needs to run in the original public multi-tenant mode, clear
the Telegram session first via `POST /api/disconnect-telegram`
(`Authorization: Bearer $ADMIN_TOKEN`, or a valid admin session cookie) —
otherwise the predictable `admin:<ADMIN_USERNAME>` identity stays reachable
through the restored public routes. See
[docs/self-hosting.md](https://github.com/Gi99lin/mcp-telegram-cloud/blob/main/docs/self-hosting.md#single-operator-mode-optional)
in the fork for the full threat model.

## Upgrading

`docker compose pull && docker compose up -d`, or just wait for Watchtower
(polls GHCR every 2 minutes, per this repo's root README).
