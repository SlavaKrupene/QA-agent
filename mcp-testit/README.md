# Test IT MCP Server

MCP-сервер для работы с тест-кейсами в Test IT. Взят из отдельного проекта пользователя
(`TestCaseGenerator/testCaseGenerator-main`, генерация кейсов из Confluence-спек) и
адаптирован для этого репозитория — добавлен `testit_ensure_section` (см. ниже).

Настроен и подключён в [.mcp.json](../.mcp.json) этого проекта — переустанавливать не нужно.
Инструкция ниже — на случай переноса на другую машину.

## Установка

```powershell
python -m venv mcp-testit/.venv
mcp-testit/.venv/Scripts/pip install -r mcp-testit/requirements.txt
```

Конфиг MCP лежит в `.mcp.json` в корне проекта; он в `.gitignore` (пути к venv зависят от
машины). При переносе: скопировать `.mcp.json.example` → `.mcp.json`. Пути в примере
относительные от корня проекта; если сервер не стартует — прописать абсолютный путь до
`python.exe`. На macOS/Linux вместо `.venv/Scripts/python.exe` — `.venv/bin/python`.

## Конфигурация

Параметры подключения берутся из `.env` в корне проекта (уже настроен):

```
TESTIT_BASE_URL=https://team-o9bf.testit.software
TESTIT_PROJECT_ID=1
TESTIT_TOKEN=PrivateToken ...
```

## Инструменты

| Tool | Описание |
|---|---|
| `testit_ping` | Проверить подключение и данные проекта |
| `testit_list_sections` | Список секций (папок) проекта с id |
| `testit_ensure_section` | **Своя, не из оригинала.** Найти/создать секцию по цепочке имён от корня проекта |
| `testit_list_work_items` | Список кейсов, фильтр по state/section/type |
| `testit_get_work_item` / `testit_bulk_get_work_items` | Полные данные одного / нескольких кейсов |
| `testit_get_comments` | Комментарии к кейсу |
| `testit_add_comment` | Добавить комментарий |
| `testit_update_work_item` / `testit_bulk_update_work_items` | Обновить один / несколько кейсов |
| `testit_create_work_item` / `testit_bulk_create_work_items` | Создать один / несколько новых кейсов |
| `testit_delete_work_item` | Удалить кейс (необратимо — см. CLAUDE.md) |

`testit_export_markdown` из оригинала **не перенесён** — он зависел от модуля
`export/tool/export_to_testit_api.py` и файлов `artifacts/`, которых в этом проекте нет.
Загрузка кейсов здесь идёт напрямую через `testit_bulk_create_work_items` (см.
`runbooks/generate-checklist.md`, «Экспорт в TestIT»), не через markdown-файл фиксированного
имени.

## Workflow ревью

```
1. Генерация → экспорт
   testit_export_markdown("feature-k20-xxx-test-cases.md")

2. Ревью в UI Test IT
   Ревьюер добавляет комментарии, ставит статус "NeedsWork"

3. Чтение фидбека
   testit_list_work_items(state="NeedsWork")
   testit_get_comments(<work_item_id>)

4. Исправление
   testit_update_work_item(<id>, steps='[...]', state="Ready")
   testit_create_work_item(...)  ← новые кейсы
   testit_delete_work_item(<id>) ← удалить лишние
```

## Значения state

| Значение API | Русский UI |
|---|---|
| `Ready` | Готов |
| `NeedsWork` | Требует доработки |
| `NotReady` | Не готов |
| `InProgress` | В работе |
| `Obsolete` | Устарел |

## Формат steps (JSON-строка)

```json
[
  {"action": "Открыть экран оффера", "expected": "Экран открылся", "testData": null},
  {"action": "Нажать кнопку покупки", "expected": "Появился экран оплаты", "testData": null}
]
```

Передаётся как строка в параметре `steps` инструментов `update` и `create`.
