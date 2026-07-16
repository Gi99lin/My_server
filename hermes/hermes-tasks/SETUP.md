# Mission Control (hermes-tasks) — Setup Runbook

Порядок запуска всей системы: YouTrack → preset → бот → cron. ~30 минут.

## 1. YouTrack

```bash
cd ~/My_server/youtrack        # (или где лежит репо на сервере)
chmod +x install.sh && ./install.sh
```

1. Открой `http://192.168.1.11:8899`, введи wizard token
   (`docker exec youtrack cat /opt/youtrack/conf/internal/services/configurationWizard/wizard_token.txt`).
2. В визарде: Base URL = `https://youtrack.gigglin.tech`, создай админа.
3. NPM → Proxy Host: `youtrack.gigglin.tech` → `youtrack:8080` (http),
   Websockets ON, SSL cert.
4. Профиль → Account Security → New token (scope YouTrack) → в `youtrack/.env`
   как `YT_TOKEN`, туда же `YT_URL=https://youtrack.gigglin.tech`.
5. Preset + импорт задач из старых канбанов (с сервера публичный домен
   недоступен — нет NAT loopback, поэтому через локальный порт):
   ```bash
   YT_URL=http://localhost:8899 python3 bootstrap/bootstrap_youtrack.py
   ```
6. В UI открой борд **Mission Control**: swimlanes = `Sphere`,
   WIP-лимит колонки In Progress = 3. (API это не умеет, руками 1 минута.)

## 2. Telegram-бот

1. @BotFather → `/newbot` → например `gigglin_mission_control_bot`.
2. Токен → `hermes/.env` → `TELEGRAM_BOT_TOKEN_TASKS=`.
3. Там же заполни `YOUTRACK_TOKEN=` (тот же perm-токен, что в шаге 1.4,
   либо отдельный от выделенного юзера `hermes` — чище для истории изменений).

## 3. Запуск агента

```bash
cd ~/My_server/hermes
docker compose up -d hermes-tasks
docker logs -f hermes-tasks     # дождаться "gateway ready"
```

Напиши боту что-нибудь («привет») — он должен ответить в роли Mission Control.
Дашборд: `ssh -L 9121:127.0.0.1:9121 сервер` → http://localhost:9121.

## 4. Cron-задания (создаются одним сообщением боту)

Отправь боту три сообщения:

```
Создай cron-задание: будни 09:00 и выходные 10:00 (Europe/Moscow) —
утренний дайджест по скиллу daily-digest.
```
```
Создай cron-задание: ежедневно 21:30 (Europe/Moscow) — вечерний чек-ин
по скиллу daily-digest.
```
```
Создай cron-задание: воскресенье 11:00 (Europe/Moscow) — недельное ревью
по скиллу weekly-review.
```

Проверь: `docker exec hermes-tasks hermes cron list` (или спроси у бота
«покажи свои cron-задания»).

## 5. Первая проверка системы

1. Кинь боту сырую задачу голосом: «надо разобраться с ВНЖ Беларуси» —
   он должен найти существующую LIFE-задачу и предложить декомпозицию,
   а не создать дубль.
2. Ответь «да» и проверь подзадачи на борде.
3. Скажи «сделай пункт 2 сам» на любой 🤖-подзадаче — результат должен
   прийти файлом + комментарием в задаче.

## Что где лежит

| Что | Где |
|---|---|
| Персона агента | `SOUL.md` |
| Скиллы (intake, digest, review, executor, yt-ops) | `skills/` |
| CLI для YouTrack | `scripts/yt.py` |
| Результаты agent-задач | `workspace/tasks/outputs/` (runtime) |
| Преcет и импорт YouTrack | `../../youtrack/bootstrap/` |

## Обсидиан
Vault остаётся стратегическим слоем (Компас, Weekly, знания) — агент в него
НЕ пишет (LiveSync-конфликты). Воскресный черновик пульса приходит в TG,
вставка в Weekly-заметку — руками, это осознанный ритуал.
