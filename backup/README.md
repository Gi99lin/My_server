# 🗄️ Server Backup — Restic + Backblaze B2

Ежедневный автоматический бэкап всего сервера `/home/gigglin/` + Docker volumes с загрузкой в Backblaze B2. Бэкап шифруется, дедуплицируется и инкрементален.

**Что входит в бэкап:**

Файлы:
- `/home/gigglin/` — все файлы, конфиги, репозиторий
- `/var/lib/docker/volumes/` — данные всех Docker-контейнеров (БД, сертификаты, etc.)
- `/srv/nextcloud-data` — данные Nextcloud
- `/var/lib/libvirt/images` — диски виртуалок (Win10 VM) — **ISO-файлы исключены**
- `/etc/libvirt/qemu` — XML-определения libvirt-доменов
- `/etc/iptables` — persistent правила iptables (forward между Docker и libvirt)
- `/var/lib/marznode` — marznode keypair, hysteria cert/key, конфиги VPN-нод (bind-mount, не Docker volume)

Дампы баз данных (только если контейнер запущен):
- `nginx-proxy-manager-db` (MariaDB)
- `nextcloud-db` (MariaDB)
- `marzneshin-db` (MariaDB)
- `chat-mongodb` (MongoDB, LibreChat)
- `testcase-db` (Postgres, AI Testcase Generator)
- `guacamole-postgres` (Postgres) — кредлы читаются из `../guacamole/.env` автоматически
- libvirt XML всех доменов (`virsh dumpxml`)

**Расписание:** каждую ночь в 03:00  
**Хранение:** 30 ежедневных | 8 еженедельных | 12 ежемесячных снапшотов  
**Проверка целостности:** каждое воскресенье автоматически

---

## 🚀 Первоначальная настройка (один раз)

### Шаг 1 — Создай аккаунт Backblaze B2

1. Зарегистрируйся на [backblaze.com](https://www.backblaze.com/sign-up/cloud-storage)
2. Перейди в **Buckets → Create a Bucket**
   - Bucket Name: `my-server-backup` (или любое уникальное имя)
   - Files in Bucket are: **Private**
   - Encryption: Enable (Server Side Encryption)
3. Перейди в **Application Keys → Add a New Application Key**
   - Name: `restic-server-key`
   - Access: выбери свой bucket
   - Скопируй **keyID** и **applicationKey** (показывается один раз!)

### Шаг 2 — Настрой `.env` на сервере

```bash
# Подключись к серверу по SSH, затем:
cp /home/gigglin/My_server/backup/.env.example /home/gigglin/My_server/backup/.env
nano /home/gigglin/My_server/backup/.env
```

Заполни (см. `.env.example` для полного списка):
```env
B2_ACCOUNT_ID=<твой keyID>
B2_ACCOUNT_KEY=<твой applicationKey>
B2_BUCKET_NAME=my-server-backup
RESTIC_PASSWORD=<придумай длинный пароль — СОХРАНИ ЕГО ОТДЕЛЬНО!>

# DB root passwords (должны совпадать с .env соответствующих сервисов)
NPM_DB_ROOT_PASSWORD=npm_root_password
NEXTCLOUD_DB_ROOT_PASSWORD=mariadbroot
MARZNESHIN_DB_ROOT_PASSWORD=<see marzneshin/.env>
TESTCASE_DB_PASSWORD=<see ai-testcase-generator/.env>
# Guacamole — пароль читается автоматически из ../guacamole/.env
```

> Если какая-то БД не нужна / выключена / пароль не задан — `backup.sh` молча
> её пропустит. Бэкап не упадёт из-за одной отсутствующей БД.

### Опционально — авто-заполнить пароли из соседних `.env`

Чтобы не копировать руками значения из `../marzneshin/.env`, `../ai-testcase-generator/.env` и т.д. — есть скрипт:

```bash
./sync-credentials.sh             # заполняет только пустые/отсутствующие ключи
./sync-credentials.sh --force     # перезаписывает даже если уже задано
./sync-credentials.sh --dry-run   # показывает план без записи
```

Безопасно: исходные `.env`-файлы только читаются, пароли в stdout не печатаются (только статусы `updated/added/kept/skipped`).

Guacamole-пароль не нужен — `backup.sh` читает его прямо из `../guacamole/.env` в момент дампа.

> ⚠️ **ВАЖНО:** Сохрани `RESTIC_PASSWORD` в менеджере паролей (Bitwarden, 1Password, etc.) или запиши. Без него расшифровать бэкап будет невозможно даже если у тебя есть доступ к B2!

### Шаг 3 — Запусти установку

```bash
sudo bash /home/gigglin/My_server/backup/install.sh
```

Скрипт:
- Установит `restic`
- Создаст права на файлы
- Инициализирует репозиторий в B2
- Создаст cron job (ежедневно в 03:00)

### Шаг 4 — Проверь первый бэкап

```bash
# Запусти вручную (займёт 5-20 мин в зависимости от объёма данных)
sudo /home/gigglin/My_server/backup/backup.sh

# Посмотри список снапшотов
sudo /home/gigglin/My_server/backup/restore.sh list

# Посмотри лог
tail -50 /var/log/restic-backup.log
```

---

## 🔄 Восстановление после аварии

> Ситуация: сервер упал, данные потеряны, нужно восстановить всё с нуля.

### Шаг 1 — Подними новый сервер + установи Docker

```bash
# Ubuntu/Debian
apt update && apt install -y docker.io docker-compose-plugin curl bzip2
```

### Шаг 2 — Клонируй репозиторий с конфигами

```bash
git clone git@github.com:Gi99lin/My_server-minimax-.git /home/gigglin/My_server
```

> Если GitHub недоступен — конфиги также есть в бэкапе (шаг 4)

### Шаг 3 — Установи restic

```bash
# Скачай restic
curl -fsSL https://github.com/restic/restic/releases/download/v0.17.3/restic_0.17.3_linux_amd64.bz2 | bunzip2 > /usr/local/bin/restic
chmod +x /usr/local/bin/restic
```

### Шаг 4 — Восстанови файлы из бэкапа

```bash
# Создай .env с учётными данными B2
nano /home/gigglin/My_server/backup/.env
# (заполни те же данные что и при установке)

# Посмотри доступные снапшоты
sudo /home/gigglin/My_server/backup/restore.sh list

# Восстанови в /tmp/restore (последний снапшот)
sudo /home/gigglin/My_server/backup/restore.sh restore latest /tmp/restore

# Или конкретный снапшот:
sudo /home/gigglin/My_server/backup/restore.sh restore abc12345 /tmp/restore
```

### Шаг 5 — Перенеси данные

```bash
# Конфиги и файлы
rsync -av /tmp/restore/home/gigglin/ /home/gigglin/

# Docker volumes
ls /tmp/restore/var/lib/docker/volumes/

# Для каждого volume (пример):
docker volume create vps-server_nginx-data
docker run --rm \
  -v vps-server_nginx-data:/dest \
  -v /tmp/restore/var/lib/docker/volumes/vps-server_nginx-data/_data:/src \
  alpine sh -c "cp -a /src/. /dest/"
```

### Шаг 6 — Восстанови базы данных

Дампы лежат в `/tmp/restore/tmp/restic-db-dumps/`:

```bash
# Список доступных дампов
ls /tmp/restore/tmp/restic-db-dumps/
```

**NPM (MariaDB):**
```bash
cd /home/gigglin/My_server && docker compose up -d db
sleep 10
cat /tmp/restore/tmp/restic-db-dumps/npm-all-databases.sql | \
  docker exec -i nginx-proxy-manager-db mysql -uroot -p"${NPM_DB_ROOT_PASSWORD}"
```

**Nextcloud (MariaDB):**
```bash
cat /tmp/restore/tmp/restic-db-dumps/nextcloud-all-databases.sql | \
  docker exec -i nextcloud-db mariadb -uroot -p"mariadbroot"
```

**Marzneshin (MariaDB):**
```bash
cat /tmp/restore/tmp/restic-db-dumps/marzneshin-all-databases.sql | \
  docker exec -i marzneshin-db mariadb -uroot -p"${MARZNESHIN_DB_ROOT_PASSWORD}"
```

**LibreChat (MongoDB):**
```bash
docker exec -i chat-mongodb mongorestore --archive --gzip \
  < /tmp/restore/tmp/restic-db-dumps/librechat-mongo.archive.gz
```

**Guacamole (Postgres):**
```bash
source /home/gigglin/My_server/guacamole/.env
cat /tmp/restore/tmp/restic-db-dumps/guacamole.sql | \
  docker exec -i -e PGPASSWORD="${POSTGRES_PASSWORD}" guacamole-postgres \
    psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}"
```

**AI Testcase Generator (Postgres):**
```bash
source /home/gigglin/My_server/backup/.env
cat /tmp/restore/tmp/restic-db-dumps/testcase-all-databases.sql | \
  docker exec -i -e PGPASSWORD="${TESTCASE_DB_PASSWORD}" testcase-db \
    psql -U "${TESTCASE_DB_USER:-postgres}"
```

### Шаг 6.5 — Восстанови виртуалки libvirt

```bash
# Скопируй XML определения
sudo cp /tmp/restore/tmp/restic-db-dumps/libvirt/*.xml /etc/libvirt/qemu/

# Скопируй диски (qcow2)
sudo cp /tmp/restore/var/lib/libvirt/images/*.qcow2 /var/lib/libvirt/images/

# Перерегистрируй и запусти
for xml in /etc/libvirt/qemu/*.xml; do
  sudo virsh define "$xml"
done
sudo virsh start win10

# Восстанови iptables FORWARD-правила
sudo cp /tmp/restore/etc/iptables/rules.v4 /etc/iptables/
sudo netfilter-persistent reload
```

> Винда после восстановления загрузится «как будто после внезапного выключения» —
> NTFS journal сам приведёт ФС в порядок, чтобы это было быстро лучше делать
> `virsh shutdown win10` перед бэкапом, но и без этого обычно ОК.

### Шаг 7 — Запусти все сервисы

```bash
cd /home/gigglin/My_server
docker compose up -d

cd /home/gigglin/My_server/marzneshin
docker compose up -d

cd /home/gigglin/My_server/omniroute
docker compose up -d

cd /home/gigglin/My_server/openclaw
docker compose up -d
# ... и т.д.
```

---

## 🔧 Полезные команды

```bash
# Посмотреть список снапшотов
sudo /home/gigglin/My_server/backup/restore.sh list

# Статистика репозитория (сколько занимает в B2)
sudo /home/gigglin/My_server/backup/restore.sh stats

# Проверить целостность
sudo /home/gigglin/My_server/backup/restore.sh check

# Посмотреть лог последнего бэкапа
tail -100 /var/log/restic-backup.log

# Запустить бэкап вручную
sudo /home/gigglin/My_server/backup/backup.sh
```

---

## 📋 Структура файлов

```
backup/
├── install.sh      ← запустить один раз для настройки
├── backup.sh       ← основной скрипт (запускается cron'ом)
├── restore.sh      ← восстановление из снапшота
├── .env            ← учётные данные (не в git!)
├── .env.example    ← шаблон
└── README.md       ← эта инструкция
```
