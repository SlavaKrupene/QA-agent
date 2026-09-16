# Confluence MCP Server — только чтение

Тот же принцип, что и [mcp-jira/](../mcp-jira/): свой минимальный сервер вместо официального
Atlassian MCP (его браузерный OAuth не проходит в этом типе сессии — см. project.md).
Использует **тот же** API-токен, что и Jira (`JIRA_EMAIL` / `JIRA_API_TOKEN` в `.env`) —
токен Atlassian один на весь сайт, для Jira и Confluence Cloud отдельный не нужен.

**Пишущих функций в коде нет вообще** — единственный HTTP-метод, который умеет `server.py`, — `GET`.

## Установка

```powershell
python -m venv mcp-confluence/.venv
mcp-confluence/.venv/Scripts/pip install -r mcp-confluence/requirements.txt
```

Конфиг MCP лежит в `.mcp.json` в корне проекта; он в `.gitignore` (пути к venv зависят от
машины). При переносе: скопировать `.mcp.json.example` → `.mcp.json`. Пути в примере
относительные от корня проекта; если сервер не стартует — прописать абсолютный путь до
`python.exe`. На macOS/Linux вместо `.venv/Scripts/python.exe` — `.venv/bin/python`.

## Конфигурация

Из `.env` в корне проекта (обычно достаточно уже заданных для Jira):

```
JIRA_URL=https://tfgames.atlassian.net
JIRA_EMAIL=<та же почта>
JIRA_API_TOKEN=<тот же токен>
# CONFLUENCE_URL=  — задать отдельно, только если Confluence на другом адресе
```

## Инструменты

| Tool | Описание |
|---|---|
| `confluence_ping` | Проверить подключение |
| `confluence_get_page` | Содержимое страницы по id или по ссылке `.../wiki/spaces/<SPACE>/pages/<id>/<slug>` |
| `confluence_search` | Поиск страниц по CQL |

`body_html` — уже отрендеренный HTML страницы, читается как есть.
