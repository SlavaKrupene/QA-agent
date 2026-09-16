#!/usr/bin/env python3
"""
Confluence MCP Server — только чтение.

Никакой пишущей функции в этом файле нет вообще (не запрет политикой — физически
не реализовано): ни создание/правка страниц, ни комментарии. Единственный HTTP-метод,
который умеет `server.py`, — GET.

Аутентификация — тот же API-токен Jira Cloud, что и в mcp-jira/ (Atlassian-токен работает
для Jira и Confluence Cloud одного сайта одинаково). Получить токен, если ещё нет:
https://id.atlassian.com/manage-profile/security/api-tokens

Все параметры — из .env в корне проекта:
  JIRA_URL (тот же сайт, что и у Jira — Confluence на нём же, путь /wiki)
  JIRA_EMAIL, JIRA_API_TOKEN
  CONFLUENCE_URL — опционально, если Confluence на другом адресе, чем JIRA_URL
"""
from __future__ import annotations

import base64
import json
import os
import re
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


SITE_URL = (_cfg("CONFLUENCE_URL") or _cfg("JIRA_URL")).rstrip("/")
EMAIL = _cfg("JIRA_EMAIL")
TOKEN = _cfg("JIRA_API_TOKEN")

_PAGE_ID_RE = re.compile(r"/wiki/spaces/[^/]+/pages/(\d+)")


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
    """GET-запрос к Confluence REST API. path начинается с /wiki/... Метод жёстко GET —
    в этом сервере нет функции, которая умеет отправить что-то ещё."""
    if not SITE_URL:
        raise RuntimeError("JIRA_URL / CONFLUENCE_URL не заданы в .env")
    if not EMAIL or not TOKEN:
        raise RuntimeError("JIRA_EMAIL / JIRA_API_TOKEN не заданы в .env")

    url = SITE_URL + path
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
    "confluence",
    instructions=(
        "Инструменты только для ЧТЕНИЯ Confluence Cloud (тот же API-токен, что и Jira). "
        "confluence_get_page — содержимое страницы по id или по ссылке вида "
        ".../wiki/spaces/<SPACE>/pages/<id>/<slug>. confluence_search — поиск по тексту (CQL). "
        "Писать в Confluence этот сервер не умеет — таких функций нет."
    ),
)


@mcp.tool(description="Проверить подключение к Confluence и вернуть текущего пользователя.")
def confluence_ping() -> str:
    try:
        me = _get("/wiki/rest/api/user/current")
        return json.dumps(
            {"ok": True, "site_url": SITE_URL, "display_name": me.get("displayName"), "account_id": me.get("accountId")},
            ensure_ascii=False,
        )
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool(
    description=(
        "Получить содержимое страницы Confluence по id ИЛИ по полной ссылке на страницу "
        "(вида 'https://<site>/wiki/spaces/<SPACE>/pages/<id>/<slug>' — id вытащит сам). "
        "Возвращает title, space, version, body_html (отрендеренный HTML — читай как есть), "
        "ancestors (родительские страницы, для контекста раздела)."
    )
)
def confluence_get_page(page_id_or_url: str) -> str:
    try:
        m = _PAGE_ID_RE.search(page_id_or_url)
        page_id = m.group(1) if m else page_id_or_url.strip()
        if not page_id.isdigit():
            return json.dumps({"ok": False, "error": f"Не удалось выделить id страницы из {page_id_or_url!r}"})

        data = _get(
            f"/wiki/rest/api/content/{page_id}"
            f"?expand=body.view.value,space,version,ancestors"
        )
        body = ((data.get("body") or {}).get("view") or {}).get("value") or ""
        result = {
            "id": data.get("id"),
            "title": data.get("title"),
            "space": (data.get("space") or {}).get("key"),
            "version": (data.get("version") or {}).get("number"),
            "ancestors": [a.get("title") for a in (data.get("ancestors") or [])],
            "url": f"{SITE_URL}/wiki{data.get('_links', {}).get('webui', '')}" if data.get("_links") else None,
            "body_html": body,
        }
        return json.dumps(result, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)


@mcp.tool(
    description=(
        "Поиск страниц Confluence по тексту (CQL, например 'text ~ \"sticker rush\"' или "
        "'space = K20 AND title ~ \"большой вызов\"'). Возвращает id/title/space по каждой "
        "найденной странице — id используй в confluence_get_page."
    )
)
def confluence_search(cql: str, max_results: int = 15) -> str:
    try:
        data = _get(
            f"/wiki/rest/api/content/search?cql={urllib.parse.quote(cql)}"
            f"&limit={int(max_results)}&expand=space"
        )
        results = data.get("results", []) if isinstance(data, dict) else []
        out = [
            {"id": r.get("id"), "title": r.get("title"), "space": (r.get("space") or {}).get("key")}
            for r in results
        ]
        return json.dumps({"total_size": data.get("size"), "results": out}, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)


if __name__ == "__main__":
    mcp.run(transport="stdio")
