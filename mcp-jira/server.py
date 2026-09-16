#!/usr/bin/env python3
"""
Jira MCP Server — только чтение.

Никакой пишущей функции в этом файле нет вообще (не запрет политикой — физически
не реализовано): ни create/update issue, ни комментарии, ни переходы статуса, ни ворклоги.
Если понадобится что-то из этого — здесь не место, см. CLAUDE.md, «Jira — только чтение».

Аутентификация — API-токен Jira Cloud (Basic: email + токен), НЕ OAuth. Получить токен:
https://id.atlassian.com/manage-profile/security/api-tokens

Все параметры — из .env в корне проекта:
  JIRA_URL, JIRA_EMAIL, JIRA_API_TOKEN
"""
from __future__ import annotations

import base64
import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

# ─── Конфигурация ─────────────────────────────────────────────────────────────

def _load_dotenv() -> dict[str, str]:
    env: dict[str, str] = {}
    root = Path(__file__).resolve().parents[1]
    p = root / ".env"
    if p.exists():
        for raw in p.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


_ENV = _load_dotenv()


def _cfg(key: str) -> str:
    return (os.environ.get(key) or _ENV.get(key) or "").strip()


BASE_URL = _cfg("JIRA_URL").rstrip("/")
EMAIL = _cfg("JIRA_EMAIL")
TOKEN = _cfg("JIRA_API_TOKEN")


def _auth_header() -> str:
    raw = f"{EMAIL}:{TOKEN}".encode("utf-8")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def _ssl_ctx() -> ssl.SSLContext:
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _get(path: str) -> Any:
    """GET-запрос к Jira REST API. path должен начинаться с /rest/api/3/... Метод жёстко GET —
    в этом сервере нет функции, которая умеет отправить что-то ещё."""
    if not BASE_URL:
        raise RuntimeError("JIRA_URL не задан в .env")
    if not EMAIL or not TOKEN:
        raise RuntimeError("JIRA_EMAIL / JIRA_API_TOKEN не заданы в .env")

    url = BASE_URL + path
    headers = {"Authorization": _auth_header(), "Accept": "application/json"}
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, context=_ssl_ctx(), timeout=60) as r:
            raw = r.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"HTTP {e.code} GET {url}: {body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Сетевая ошибка GET {url}: {e!r}") from e


# ─── MCP сервер ────────────────────────────────────────────────────────────────

mcp = FastMCP(
    "jira",
    instructions=(
        "Инструменты только для ЧТЕНИЯ Jira Cloud (API-токен, не OAuth). "
        "jira_get_issue — задача целиком (описание, комментарии, связи, подзадачи). "
        "jira_search — поиск по JQL. Писать в Jira этот сервер не умеет — таких функций нет."
    ),
)


@mcp.tool(description="Проверить подключение к Jira и вернуть текущего пользователя.")
def jira_ping() -> str:
    try:
        me = _get("/rest/api/3/myself")
        return json.dumps(
            {
                "ok": True,
                "base_url": BASE_URL,
                "account_id": me.get("accountId"),
                "display_name": me.get("displayName"),
                "email": me.get("emailAddress"),
            },
            ensure_ascii=False,
        )
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool(
    description=(
        "Получить задачу Jira целиком по ключу (например 'KISS-1234'): summary, description, "
        "status, type, priority, labels, fixVersions, assignee, reporter, parent, subtasks, "
        "issuelinks, ВСЕ комментарии (author, created, body). description/comments приходят как "
        "HTML (renderedFields) — читай как есть, форматирование не имеет значения."
    )
)
def jira_get_issue(key: str) -> str:
    try:
        fields = (
            "summary,description,status,issuetype,priority,labels,fixVersions,"
            "assignee,reporter,parent,subtasks,issuelinks,created,updated"
        )
        issue = _get(
            f"/rest/api/3/issue/{urllib.parse.quote(key)}"
            f"?fields={urllib.parse.quote(fields)}&expand=renderedFields"
        )
        f = issue.get("fields", {}) or {}
        rendered = issue.get("renderedFields", {}) or {}

        comments_data = _get(
            f"/rest/api/3/issue/{urllib.parse.quote(key)}/comment"
            f"?expand=renderedBody&maxResults=100&orderBy=created"
        )
        comments_raw = comments_data.get("comments", []) if isinstance(comments_data, dict) else []
        total_comments = comments_data.get("total", len(comments_raw)) if isinstance(comments_data, dict) else len(comments_raw)

        def _person(p: dict | None) -> str | None:
            if not p:
                return None
            return p.get("displayName") or p.get("emailAddress") or p.get("accountId")

        result = {
            "key": issue.get("key"),
            "summary": f.get("summary"),
            "status": (f.get("status") or {}).get("name"),
            "type": (f.get("issuetype") or {}).get("name"),
            "priority": (f.get("priority") or {}).get("name"),
            "labels": f.get("labels") or [],
            "fix_versions": [v.get("name") for v in (f.get("fixVersions") or [])],
            "assignee": _person(f.get("assignee")),
            "reporter": _person(f.get("reporter")),
            "created": f.get("created"),
            "updated": f.get("updated"),
            "description_html": rendered.get("description") or "",
            "parent": (
                {"key": f["parent"].get("key"), "summary": (f["parent"].get("fields") or {}).get("summary")}
                if f.get("parent")
                else None
            ),
            "subtasks": [
                {"key": s.get("key"), "summary": (s.get("fields") or {}).get("summary"),
                 "status": ((s.get("fields") or {}).get("status") or {}).get("name")}
                for s in (f.get("subtasks") or [])
            ],
            "links": [
                {
                    "type": (link.get("type") or {}).get("name"),
                    "direction": "outward" if "outwardIssue" in link else "inward",
                    "key": (link.get("outwardIssue") or link.get("inwardIssue") or {}).get("key"),
                    "summary": ((link.get("outwardIssue") or link.get("inwardIssue") or {}).get("fields") or {}).get("summary"),
                }
                for link in (f.get("issuelinks") or [])
            ],
            "comments": [
                {
                    "author": _person(c.get("author")),
                    "created": c.get("created"),
                    "body_html": (c.get("renderedBody") or ""),
                }
                for c in comments_raw
            ],
            "comments_truncated": total_comments > len(comments_raw),
        }
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool(
    description=(
        "Поиск задач Jira по JQL (например 'project = KISS AND text ~ \"sticker rush\"' или "
        "'key in (KISS-100, KISS-101)'). Возвращает key/summary/status/type/updated по каждой. "
        "Полезно для поиска связанных задач или проверки, что ключ/проект существует."
    )
)
def jira_search(jql: str, max_results: int = 25) -> str:
    try:
        data = _get(
            f"/rest/api/3/search?jql={urllib.parse.quote(jql)}"
            f"&maxResults={int(max_results)}&fields=summary,status,issuetype,updated"
        )
        issues = data.get("issues", []) if isinstance(data, dict) else []
        result = [
            {
                "key": i.get("key"),
                "summary": (i.get("fields") or {}).get("summary"),
                "status": ((i.get("fields") or {}).get("status") or {}).get("name"),
                "type": ((i.get("fields") or {}).get("issuetype") or {}).get("name"),
                "updated": (i.get("fields") or {}).get("updated"),
            }
            for i in issues
        ]
        return json.dumps({"total": data.get("total"), "issues": result}, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run(transport="stdio")
