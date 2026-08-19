# Manager Helper — Setup Runbook

Telegram bot (@Gigglin/@Mirabilis) that turns manager voice notes/text into
YouTrack tasks. Source: [Gi99lin/manager-helper](https://github.com/Gi99lin/manager-helper)
(private). Image auto-builds to `ghcr.io/gi99lin/manager-helper:latest` on
every push to `main` (`.github/workflows/docker-publish.yml` in that repo);
Watchtower here picks up new versions automatically once running.

## 1. First-time deploy

```bash
cd ~/My_server/manager-helper
cp env.example .env
nano .env
```

Fill in every blank value in `.env`:

- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`, `TELEGRAM_WEBHOOK_BASE_URL` — bot runs via long-polling, not a webhook, but `Settings` requires these to be set; `TELEGRAM_WEBHOOK_SECRET`/`_BASE_URL` can be any placeholder values.
- `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, `TRANSCRIPTION_MODEL` — OpenAI-compatible endpoint used for parsing/transcription.
- `YOUTRACK_BASE_URL` (`https://youtrack.gigglin.tech`), `YOUTRACK_API_TOKEN`, `YOUTRACK_DEFAULT_PROJECT_KEY` (`MHT`).
- `FERNET_KEY` — generate with `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.

Leave `POSTGRES_DSN` / `REDIS_URL` as the defaults already in `env.example` —
they point at this compose file's own `manager-helper-db`/`manager-helper-redis`
services.

```bash
docker login ghcr.io -u Gi99lin   # once, if not already done for other services
docker compose pull
docker compose up -d
docker compose logs -f manager-helper-bot   # wait for "Deleting Telegram webhook before starting polling..." then a clean run
```

## 2. Ongoing deploys

Nothing to do here — Watchtower polls GHCR every 2 minutes and restarts
`manager-helper-bot`/`manager-helper-worker` when a new `:latest` image
lands. A `git push` to `main` in the source repo is the whole deploy.

## 3. Manual redeploy / rollback

```bash
cd ~/My_server/manager-helper
docker compose pull
docker compose up -d
```

## 4. Database migrations

Run automatically on every `manager-helper-bot` container start
(`alembic upgrade head` before `run_polling`) — idempotent, no manual step
needed on a normal deploy.
