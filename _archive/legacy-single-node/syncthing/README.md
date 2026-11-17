# Syncthing + Obsidian Vault для OpenClaw

Инструкция по настройке синхронизации Obsidian vault через Syncthing и подключению к OpenClaw.

## Шаг 1: Запуск Syncthing на сервере

```bash
cd ~/My_server/syncthing

# Создать .env (при необходимости)
cp .env.example .env
# Отредактировать OBSIDIAN_VAULT_DIR если путь отличается от ~/obsidian-vault

# Создать директорию для vault
mkdir -p ~/obsidian-vault

# Запустить
docker compose up -d
```

Проверить: `docker ps | grep syncthing` — статус `Up`.

## Шаг 2: Защита Web UI

Сразу после запуска зайти в Web UI по `http://<server-ip>:8384` и:

1. **Settings → GUI** → установить пароль (будет запрашиваться при каждом входе)
2. Или через Nginx Proxy Manager: создать proxy host для `syncthing.<domain>` → `http://syncthing:8384`

> ⚠️ Не оставлять Web UI без пароля! Syncthing имеет полный доступ к файлам.

## Шаг 3: Установка Syncthing на Mac

```bash
brew install syncthing

# Запустить (и добавить в автозагрузку)
brew services start syncthing
```

Web UI будет доступен на `http://127.0.0.1:8384`.

## Шаг 4: Связка устройств

1. На **Mac** (Syncthing UI): скопировать **Device ID** из **Actions → Show ID**
2. На **сервере** (Syncthing UI): **Add Remote Device** → вставить Device ID Mac
3. На **Mac**: подтвердить запрос на подключение от сервера

## Шаг 5: Расшаривание Obsidian vault

1. На **Mac** (Syncthing UI): **Add Folder**
   - **Folder Path**: путь к вашему Obsidian vault (например, `~/Documents/ObsidianVault`)
   - **Folder ID**: `obsidian-vault` (любой уникальный ID)
   - **Sharing** → отметить сервер
2. На **сервере**: подтвердить запрос, указать путь `/var/syncthing/obsidian-vault`

## Шаг 6: Перезапуск OpenClaw

```bash
cd ~/My_server/openclaw
docker compose down
docker compose up -d
```

Vault будет доступен OpenClaw по пути `obsidian-vault/` в его workspace.

## Шаг 7: Проверка

Попросить OpenClaw (через Telegram/Web):
> Перечисли файлы в папке obsidian-vault

Он должен увидеть содержимое вашего vault.

## Удаление LiveSync (опционально)

Если iOS не используется и Syncthing полностью заменяет LiveSync:

1. В Obsidian: отключить плагин Self-hosted LiveSync
2. На Fly.io: удалить приложение CouchDB (`fly apps destroy <app-name>`)
