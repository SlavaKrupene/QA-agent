# Jira MCP Server — только чтение

Свой минимальный MCP-сервер для Jira Cloud, на случай когда официальный Atlassian MCP
(OAuth в браузере) недоступен в текущем типе сессии. Аутентификация — API-токен
(`https://id.atlassian.com/manage-profile/security/api-tokens`), Basic Auth (email + токен),
без входа через браузер.

**Пишущих функций в коде нет вообще** — не запрет политикой, а отсутствие реализации.
Единственный HTTP-метод, который умеет `server.py`, — `GET`.

## Установка

```powershell
python -m venv mcp-jira/.venv
mcp-jira/.venv/Scripts/pip install -r mcp-jira/requirements.txt
```

Конфиг MCP лежит в `.mcp.json` в корне проекта; он в `.gitignore` (пути к venv зависят от
машины). При переносе: скопировать `.mcp.json.example` → `.mcp.json`. Пути в примере
относительные от корня проекта; если сервер не стартует — прописать абсолютный путь до
`python.exe`. На macOS/Linux вместо `.venv/Scripts/python.exe` — `.venv/bin/python`.

## Конфигурация

Из `.env` в корне проекта:

```
JIRA_URL=https://tfgames.atlassian.net
JIRA_EMAIL=<почта аккаунта Jira>
JIRA_API_TOKEN=<токен из id.atlassian.com>
```

## Инструменты

| Tool | Описание |
|---|---|
| `jira_ping` | Проверить подключение, вернуть текущего пользователя |
| `jira_get_issue` | Задача целиком: поля, описание, ВСЕ комментарии, связи, подзадачи |
| `jira_search` | Поиск по JQL |

`description` и текст комментариев приходят как HTML (`renderedFields` API Jira) — читаются
как есть, парсить в markdown не нужно.

## Если официальный Atlassian MCP заработает

Если в другой сессии/окружении браузерный OAuth пройдёт нормально — можно вернуться к
официальному серверу (`https://mcp.atlassian.com/v2/mcp`, см. историю `.mcp.json`) и
отключить этот. Официальный обычно даёт больше (запись, Confluence и т.д.), но в проекте
всё равно используется только чтение — разницы для пайплайна `/qa` нет.
