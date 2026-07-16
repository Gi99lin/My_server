# Skill: YouTrack Ops — вся работа с задачами через yt.py

## Инструмент
Единственный способ читать/писать задачи — терминал:
```bash
python3 /opt/data/scripts/yt.py <command> ...
```
Переменные `YOUTRACK_URL` / `YOUTRACK_TOKEN` уже в окружении контейнера.

## Команды

```bash
# создать задачу (печатает ID, например PROJ-17)
yt.py create --project PROJ --summary "Написать шаблон отклика" \
  --state Next --sphere "🏗 Проекты" --size "M (≤2 ч)" --energy Light \
  --due 2026-07-20 --tags agent --description "..."

# подзадача
yt.py create --project PROJ --summary "..." --parent PROJ-17

# списки (query — обычный синтаксис поиска YouTrack)
yt.py list --query "#Unresolved State: {In Progress}"
yt.py list --query "#Unresolved Due: * .. {Today}"          # просроченные + сегодня
yt.py list --query "#Unresolved tag: agent"
yt.py list --query "#Unresolved State: Next sort by: {issue id}"
yt.py list --query "#Unresolved summary: *фриланс*"          # поиск дубликатов

# одна задача (+описание)
yt.py get PROJ-17

# любое изменение — командой YouTrack (как в командном диалоге UI)
yt.py cmd PROJ-17 "State Done"
yt.py cmd PROJ-17 "State {In Progress}"
yt.py cmd PROJ-17 "Due 2026-07-22 Size {S (≤30 мин)}"
yt.py cmd PROJ-17 "tag needle-mover"
yt.py cmd PROJ-18 "subtask of PROJ-17"

# комментарий (лог агента, результаты, ссылки на outputs)
yt.py comment PROJ-17 --text "Черновик готов: workspace/tasks/outputs/proj-17-otklik.md"
```

## Конвенции полей

| Поле | Значения | Правило |
|---|---|---|
| State | Backlog, Next, In Progress, Waiting, Someday, Done, Dropped | Next = отобрано на ближайшие дни; Waiting = ждём внешнего; Someday = «отложено до лучших времён» |
| Sphere | 🏗 Проекты, 💰 Финансы, 🧠 Здоровье, ❤️ Отношения, 💼 Карьера, 🔧 Быт | всегда проставляй |
| Size | S (≤30 мин), M (≤2 ч), L (полдня+), XL (декомпозировать) | XL не может уходить в Next — сначала декомпозиция |
| Energy | Deep, Light, Errand | Deep — творческая работа, планируй на утро/выходной; Errand — можно в «мёртвое» время |
| Due | дата | только реальные сроки |
| tag agent | — | задача/подзадача, которую агент может сделать сам |
| tag needle-mover | — | одна главная вещь недели (выбирается на воскресном ревью) |

## Значения с пробелами/эмодзи в `cmd`
Всегда оборачивай в фигурные скобки: `Sphere {🧠 Здоровье}`, `State {In Progress}`.
