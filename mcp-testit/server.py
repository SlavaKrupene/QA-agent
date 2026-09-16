#!/usr/bin/env python3
"""
Test IT MCP Server — инструменты для AI-ревью тест-кейсов.

Workflow:
  1. AI экспортирует кейсы в Test IT (testit_export_markdown)
  2. Ревьюер читает кейсы, пишет комментарии, ставит статус NeedsWork
  3. AI читает NeedsWork-кейсы + комментарии, правит / удаляет / создаёт новые

Все параметры подключения берутся из .env в корне проекта:
  TESTIT_BASE_URL, TESTIT_PROJECT_ID, TESTIT_TOKEN
"""
from __future__ import annotations

import html
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
    for p in [root / ".env", root / "export" / "tool" / ".env"]:
        if not p.exists():
            continue
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


BASE_URL = _cfg("TESTIT_BASE_URL").rstrip("/")
TOKEN = _cfg("TESTIT_TOKEN")
PROJECT_ID_RAW = _cfg("TESTIT_PROJECT_ID")

UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}"
    r"-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)
_MD_LINK = re.compile(r"\[([^\]]+)\]\s*\(\s*([^)]+?)\s*\)")
_HTML_TAG = re.compile(r"<[a-zA-Z/][^>]*>")

# ─── HTTP-утилиты ──────────────────────────────────────────────────────────────

def _ssl_ctx() -> ssl.SSLContext:
    if _cfg("TESTIT_INSECURE_SSL").lower() in ("1", "true", "yes"):
        return ssl._create_unverified_context()
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _timeout() -> float:
    try:
        return float(_cfg("TESTIT_REQUEST_TIMEOUT") or "120")
    except ValueError:
        return 120.0


def _api(method: str, path: str, payload: Any = None) -> Any:
    """Выполнить запрос к Test IT API. path должен начинаться с /api/v2/..."""
    if not BASE_URL:
        raise RuntimeError("TESTIT_BASE_URL не задан в .env")
    if not TOKEN:
        raise RuntimeError("TESTIT_TOKEN не задан в .env")

    url = BASE_URL + path
    data = None
    headers = {"Authorization": TOKEN, "Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, context=_ssl_ctx(), timeout=_timeout()) as r:
            raw = r.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"HTTP {e.code} {method} {url}: {body}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"Сетевая ошибка {method} {url}: {e!r}. "
            "Проверьте VPN / TESTIT_INSECURE_SSL / TESTIT_TLS_MAX_1_2."
        ) from e


_project_uuid_cache: str | None = None


def _project_uuid() -> str:
    global _project_uuid_cache
    if _project_uuid_cache:
        return _project_uuid_cache
    pid = PROJECT_ID_RAW
    if not pid:
        raise RuntimeError("TESTIT_PROJECT_ID не задан в .env")
    if UUID_RE.match(pid):
        _project_uuid_cache = pid
        return pid
    proj = _api("GET", f"/api/v2/projects/{urllib.parse.quote(pid)}")
    uuid = proj.get("id") if isinstance(proj, dict) else None
    if not uuid:
        raise RuntimeError(f"Не удалось резолвить UUID проекта для id={pid!r}")
    _project_uuid_cache = uuid
    return uuid


# ─── Форматирование шагов ──────────────────────────────────────────────────────

def _fmt(text: str) -> str:
    """Markdown-ссылки → HTML <a>, убрать **, \n → <br/>.
    Если текст уже содержит HTML-теги — только нормализуем \n, без html.escape()."""
    if not text:
        return text
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text).replace("**", "")
    # Если уже есть HTML — не экранировать повторно, только \n → <br/>
    if _HTML_TAG.search(text):
        return text.replace("\n", "<br/>")
    parts: list[str] = []
    pos = 0
    for m in _MD_LINK.finditer(text):
        chunk = html.escape(text[pos : m.start()], quote=True).replace("\n", "<br/>")
        parts.append(chunk)
        label = html.escape(m.group(1), quote=False)
        href = html.escape(m.group(2).strip(), quote=True)
        parts.append(f'<a href="{href}">{label}</a>')
        pos = m.end()
    parts.append(html.escape(text[pos:], quote=True).replace("\n", "<br/>"))
    return "".join(parts)


def _normalize_steps(raw: list[dict]) -> list[dict]:
    return [
        {
            "action": _fmt(s.get("action") or ""),
            "expected": _fmt(s.get("expected") or "") or None,
            "testData": s.get("testData") or None,
        }
        for s in raw
    ]


def _parse_steps_json(arg: str, fallback: list) -> list[dict]:
    """Парсит JSON-строку шагов; '' = без изменений, '[]' = очистить."""
    if arg == "":
        return fallback
    return _normalize_steps(json.loads(arg))


def _summarize_steps(steps: list) -> list[dict]:
    return [
        {
            "action": s.get("action", ""),
            "expected": s.get("expected") or "",
            "testData": s.get("testData"),
        }
        for s in (steps or [])
    ]


# ─── MCP сервер ────────────────────────────────────────────────────────────────

mcp = FastMCP(
    "testit",
    instructions=(
        "Инструменты для работы с тест-кейсами (work items) в Test IT. "
        "Workflow ревью: "
        "(1) testit_export_markdown — загрузить кейсы из markdown-файла в Test IT; "
        "(2) testit_list_work_items(state='NeedsWork') — найти кейсы, требующие доработки; "
        "(3) testit_get_comments — прочитать комментарии ревьюера; "
        "(4) testit_update_work_item / testit_create_work_item / testit_delete_work_item — внести правки."
    ),
)


# ─── Tool: список секций ───────────────────────────────────────────────────────

@mcp.tool(
    description=(
        "Получить все секции (папки) проекта с их id, name, parentId. "
        "Используй для поиска sectionId перед созданием или фильтрацией кейсов."
    )
)
def testit_list_sections() -> str:
    project_id = _project_uuid()
    sections = _api("GET", f"/api/v2/projects/{project_id}/sections")
    if not isinstance(sections, list):
        return json.dumps({"error": "Неожиданный ответ API", "raw": str(sections)})
    return json.dumps(
        [{"id": s.get("id"), "name": s.get("name"), "parentId": s.get("parentId")} for s in sections],
        ensure_ascii=False,
        indent=2,
    )


# ─── Tool: получить/создать секцию по пути ─────────────────────────────────────

@mcp.tool(
    description=(
        "Найти секцию (папку) проекта по цепочке имён, создавая недостающие уровни. "
        "path: JSON-массив имён ОТ КОРНЯ ПРОЕКТА (первый элемент — корневая секция проекта, "
        "например 'Kiss Kiss 2.0'), например: "
        '\'["Kiss Kiss 2.0", "\\ud83d\\udee0\\ufe0fKiss Kiss 2.0. \\u0412 \\u0440\\u0430\\u0437\\u0440\\u0430\\u0431\\u043e\\u0442\\u043a\\u0435", "Sticker Rush", "\\u041e\\u0431\\u0449\\u0438\\u0435 \\u043f\\u0440\\u043e\\u0432\\u0435\\u0440\\u043a\\u0438"]\'. '
        "Каждый следующий элемент ищется как дочерняя секция предыдущего (по точному имени); "
        "если не находит — создаёт новую с этим именем. Возвращает id последней секции в цепочке. "
        "Используй перед testit_create_work_item / testit_bulk_create_work_items, чтобы кейсы задачи "
        "легли в нужную ветку (обычно '🛠️<проект>. В разработке' → <фича> → <категория>)."
    )
)
def testit_ensure_section(path: str) -> str:
    try:
        names: list[str] = json.loads(path)
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Невалидный JSON в path: {e}"})
    if not isinstance(names, list) or not names:
        return json.dumps({"error": "path должен быть непустым массивом строк"})

    project_id = _project_uuid()
    sections = _api("GET", f"/api/v2/projects/{project_id}/sections")
    if not isinstance(sections, list):
        return json.dumps({"error": "Неожиданный ответ API при чтении секций"})

    parent_id: str | None = None
    created_any = False
    for name in names:
        name = str(name).strip()
        match = next(
            (s for s in sections if s.get("name") == name and s.get("parentId") == parent_id),
            None,
        )
        if not match:
            payload = {"name": name, "projectId": project_id, "parentId": parent_id, "attachments": []}
            match = _api("POST", "/api/v2/sections", payload)
            if not isinstance(match, dict) or not match.get("id"):
                return json.dumps({"error": f"Не удалось создать секцию '{name}'", "raw": str(match)})
            sections.append(match)
            created_any = True
        parent_id = match.get("id")

    return json.dumps({"ok": True, "section_id": parent_id, "created_new": created_any}, ensure_ascii=False)


# ─── Tool: список work items ───────────────────────────────────────────────────

@mcp.tool(
    description=(
        "Получить список work items проекта. "
        "Фильтрация: state (NeedsWork | Ready | NotReady | InProgress | Obsolete), "
        "section_id (UUID секции), entity_type (TestCases | CheckLists). "
        "Возвращает id, globalId, name, state, priority, sectionId, entityTypeName."
    )
)
def testit_list_work_items(
    state: str = "",
    section_id: str = "",
    entity_type: str = "",
    limit: int = 200,
) -> str:
    """
    state: фильтр по статусу. Пустая строка = все статусы.
    section_id: фильтр по UUID секции. Пустая строка = весь проект.
    entity_type: TestCases | CheckLists | '' (все).
    limit: максимальное количество возвращаемых элементов.
    """
    project_id = _project_uuid()

    # Собираем ID всех дочерних секций (включая саму секцию) для клиентской фильтрации
    allowed_section_ids: set[str] | None = None
    if section_id:
        raw_sections = _api("GET", f"/api/v2/projects/{project_id}/sections")
        all_sections: list[dict] = raw_sections if isinstance(raw_sections, list) else []
        # BFS по дереву секций
        queue = [section_id]
        allowed_section_ids = set()
        while queue:
            current = queue.pop()
            allowed_section_ids.add(current)
            for s in all_sections:
                if s.get("parentId") == current:
                    queue.append(s["id"])

    # Используем проектный эндпоинт с фильтром по секциям (как фронтенд Test IT)
    body: dict[str, Any] = {"isDeleted": False}
    if allowed_section_ids:
        body["sectionIds"] = list(allowed_section_ids)

    page_size = 500
    skip = 0
    items: list[dict] = []
    while True:
        url = (
            f"/api/Projects/{project_id}/workItems"
            f"?orderBy=OrderRank%20asc&skip={skip}&take={page_size}&applyOrderingInSection=true"
        )
        page = _api("POST", url, body)
        page_items: list[dict] = page if isinstance(page, list) else []
        items.extend(page_items)
        if len(page_items) < page_size:
            break
        skip += page_size
        if len(items) >= limit:
            break

    result = []
    for item in items:
        if allowed_section_ids and item.get("sectionId") not in allowed_section_ids:
            continue
        if state and item.get("state") != state:
            continue
        if entity_type and item.get("entityTypeName") != entity_type:
            continue
        result.append(
            {
                "id": item.get("id"),
                "globalId": item.get("globalId"),
                "name": item.get("name"),
                "state": item.get("state"),
                "priority": item.get("priority"),
                "sectionId": item.get("sectionId"),
                "entityTypeName": item.get("entityTypeName"),
            }
        )

    return json.dumps(result, ensure_ascii=False, indent=2)


# ─── Tool: получить work item ──────────────────────────────────────────────────

@mcp.tool(
    description=(
        "Получить полные данные work item по UUID: "
        "name, state, priority, preconditionSteps, steps (action + expected), postconditionSteps."
    )
)
def testit_get_work_item(work_item_id: str) -> str:
    data = _api("GET", f"/api/v2/workItems/{work_item_id}")
    if not isinstance(data, dict):
        return json.dumps({"error": "work item не найден"})
    return json.dumps(
        {
            "id": data.get("id"),
            "globalId": data.get("globalId"),
            "name": data.get("name"),
            "state": data.get("state"),
            "priority": data.get("priority"),
            "entityTypeName": data.get("entityTypeName"),
            "sectionId": data.get("sectionId"),
            "projectId": data.get("projectId"),
            "description": data.get("description") or "",
            "preconditionSteps": _summarize_steps(data.get("preconditionSteps")),
            "steps": _summarize_steps(data.get("steps")),
            "postconditionSteps": _summarize_steps(data.get("postconditionSteps")),
            "tags": [t.get("name") for t in (data.get("tags") or []) if t.get("name")],
            "duration": data.get("duration"),
            "attributes": data.get("attributes") or {},
            "links": data.get("links") or [],
        },
        ensure_ascii=False,
        indent=2,
    )


# ─── Tool: комментарии ─────────────────────────────────────────────────────────

@mcp.tool(
    description=(
        "Получить все комментарии к work item. "
        "Возвращает author, text, createdAt. "
        "Используй после нахождения NeedsWork-кейсов для чтения фидбека ревьюера."
    )
)
def testit_get_comments(work_item_id: str) -> str:
    data = _api("GET", f"/api/v2/workItems/{work_item_id}/comments")
    comments = data if isinstance(data, list) else []
    result = []
    for c in comments:
        author = c.get("createdBy") or {}
        result.append(
            {
                "id": c.get("id"),
                "text": c.get("text"),
                "author": (
                    author.get("displayName")
                    or author.get("userName")
                    or author.get("id")
                    or "unknown"
                ),
                "createdAt": c.get("createdDate") or c.get("createdAt"),
            }
        )
    return json.dumps(result, ensure_ascii=False, indent=2)


# ─── Tool: добавить комментарий ────────────────────────────────────────────────

@mcp.tool(description="Добавить текстовый комментарий к work item.")
def testit_add_comment(work_item_id: str, text: str) -> str:
    data = _api("POST", f"/api/v2/workItems/{work_item_id}/comments", {"text": text})
    cid = data.get("id") if isinstance(data, dict) else None
    return json.dumps({"ok": True, "id": cid}, ensure_ascii=False)


# ─── Tool: обновить work item ──────────────────────────────────────────────────

@mcp.tool(
    description=(
        "Обновить work item в Test IT. Передавай только изменяемые поля — "
        "остальные берутся из текущего состояния кейса. "
        "steps / precondition_steps / postcondition_steps: JSON-строка вида "
        '[{"action":"...", "expected":"...", "testData":null}, ...]. '
        "Передай '' чтобы не изменять поле, '[]' чтобы очистить. "
        "state: Ready | NeedsWork | NotReady | InProgress | Obsolete. "
        "priority: Low | Medium | High."
    )
)
def testit_update_work_item(
    work_item_id: str,
    name: str = "",
    state: str = "",
    priority: str = "",
    description: str = "\x00",
    precondition_steps: str = "",
    steps: str = "",
    postcondition_steps: str = "",
) -> str:
    """
    description: передай '' чтобы не менять, любую строку для замены.
    steps и др.: '' = не менять, '[]' = очистить, '[{...}]' = заменить.
    """
    current = _api("GET", f"/api/v2/workItems/{work_item_id}")
    if not isinstance(current, dict):
        return json.dumps({"error": f"work item {work_item_id!r} не найден"})

    try:
        new_preconditions = _parse_steps_json(precondition_steps, current.get("preconditionSteps") or [])
        new_steps = _parse_steps_json(steps, current.get("steps") or [])
        new_postconditions = _parse_steps_json(postcondition_steps, current.get("postconditionSteps") or [])
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Невалидный JSON в steps/precondition_steps/postcondition_steps: {e}"})

    payload = {
        "id": work_item_id,
        "projectId": current.get("projectId"),
        "sectionId": current.get("sectionId"),
        "name": name.strip() if name.strip() else current.get("name"),
        "entityTypeName": current.get("entityTypeName"),
        "description": (
            current.get("description") or ""
            if description == "\x00"
            else description
        ),
        "state": state.strip() if state.strip() else current.get("state"),
        "priority": priority.strip() if priority.strip() else current.get("priority"),
        "duration": current.get("duration") or 600000,
        "attributes": current.get("attributes") or {},
        "tags": current.get("tags") or [],
        "links": current.get("links") or [],
        "attachments": current.get("attachments") or [],
        "preconditionSteps": new_preconditions,
        "steps": new_steps,
        "postconditionSteps": new_postconditions,
    }

    updated = _api("PUT", "/api/v2/workItems", payload)
    if isinstance(updated, dict) and updated.get("id"):
        return json.dumps(
            {"ok": True, "id": updated.get("id"), "name": updated.get("name"), "state": updated.get("state")},
            ensure_ascii=False,
        )
    return json.dumps({"ok": True, "response": updated}, ensure_ascii=False)


# ─── Tool: массовое обновление work items ─────────────────────────────────────

@mcp.tool(
    description=(
        "Массово обновить несколько work items за один вызов. "
        "items: JSON-строка массива объектов. Каждый объект: "
        '{"id": "<uuid>", "name": "...", "state": "...", "priority": "...", '
        '"description": "...", '
        '"precondition_steps": [{"action":"...","expected":"...","testData":null}], '
        '"steps": [...], "postcondition_steps": [...]}. '
        "Поля name/state/priority/description/precondition_steps/steps/postcondition_steps — все опциональны. "
        "Отсутствующие поля берутся из текущего состояния кейса. "
        "Возвращает список результатов: ok/error для каждого id."
    )
)
def testit_bulk_update_work_items(items: str) -> str:
    """
    items: JSON-строка списка объектов с полями:
      id (обязательно), name, state, priority, description,
      precondition_steps, steps, postcondition_steps (все опциональны).
    Обновляет каждый кейс последовательно, возвращает сводку результатов.
    """
    try:
        updates: list[dict] = json.loads(items)
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Невалидный JSON в items: {e}"})

    if not isinstance(updates, list):
        return json.dumps({"error": "items должен быть массивом"})

    results = []
    for upd in updates:
        work_item_id = upd.get("id", "")
        if not work_item_id:
            results.append({"id": work_item_id, "ok": False, "error": "id не задан"})
            continue

        try:
            current = _api("GET", f"/api/v2/workItems/{work_item_id}")
            if not isinstance(current, dict):
                results.append({"id": work_item_id, "ok": False, "error": "work item не найден"})
                continue

            # Шаги: если поле есть в объекте — заменяем, иначе берём из текущего
            def _resolve_steps(key: str, fallback_key: str) -> list[dict]:
                if key in upd:
                    raw = upd[key]
                    if isinstance(raw, str):
                        raw = json.loads(raw)
                    return _normalize_steps(raw)
                return current.get(fallback_key) or []

            new_preconditions = _resolve_steps("precondition_steps", "preconditionSteps")
            new_steps = _resolve_steps("steps", "steps")
            new_postconditions = _resolve_steps("postcondition_steps", "postconditionSteps")

            name = upd.get("name", "").strip()
            state = upd.get("state", "").strip()
            priority = upd.get("priority", "").strip()
            # sentinel \x00 = не менять описание
            desc_sentinel = "\x00"
            description = upd.get("description", desc_sentinel)

            payload = {
                "id": work_item_id,
                "projectId": current.get("projectId"),
                "sectionId": current.get("sectionId"),
                "name": name if name else current.get("name"),
                "entityTypeName": current.get("entityTypeName"),
                "description": (
                    current.get("description") or ""
                    if description == desc_sentinel
                    else description
                ),
                "state": state if state else current.get("state"),
                "priority": priority if priority else current.get("priority"),
                "duration": current.get("duration") or 600000,
                "attributes": current.get("attributes") or {},
                "tags": current.get("tags") or [],
                "links": current.get("links") or [],
                "attachments": current.get("attachments") or [],
                "preconditionSteps": new_preconditions,
                "steps": new_steps,
                "postconditionSteps": new_postconditions,
            }

            updated = _api("PUT", "/api/v2/workItems", payload)
            results.append({
                "id": work_item_id,
                "globalId": current.get("globalId"),
                "ok": True,
                "name": updated.get("name") if isinstance(updated, dict) else current.get("name"),
            })

        except Exception as e:
            results.append({"id": work_item_id, "ok": False, "error": str(e)})

    total = len(results)
    success = sum(1 for r in results if r.get("ok"))
    return json.dumps(
        {"total": total, "success": success, "failed": total - success, "results": results},
        ensure_ascii=False,
        indent=2,
    )


# ─── Tool: удалить work item ───────────────────────────────────────────────────

@mcp.tool(description="Удалить work item по UUID. Необратимая операция.")
def testit_delete_work_item(work_item_id: str) -> str:
    _api("DELETE", f"/api/v2/workItems/{work_item_id}")
    return json.dumps({"ok": True, "deleted": work_item_id})


# ─── Tool: массовое получение work items ──────────────────────────────────────

@mcp.tool(
    description=(
        "Получить полные данные нескольких work items за один вызов. "
        "ids: JSON-строка массива UUID, например '[\"uuid1\", \"uuid2\"]'. "
        "Возвращает список объектов с name, state, priority, preconditionSteps, steps, "
        "postconditionSteps, attributes (включая комментарий ревьюера). "
        "Используй вместо многократных вызовов testit_get_work_item."
    )
)
def testit_bulk_get_work_items(ids: str) -> str:
    """
    ids: JSON-строка массива UUID work items.
    Получает каждый кейс последовательно, возвращает единый список.
    """
    try:
        id_list: list[str] = json.loads(ids)
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Невалидный JSON в ids: {e}"})

    if not isinstance(id_list, list):
        return json.dumps({"error": "ids должен быть массивом"})

    results = []
    for work_item_id in id_list:
        try:
            data = _api("GET", f"/api/v2/workItems/{work_item_id}")
            if not isinstance(data, dict):
                results.append({"id": work_item_id, "error": "не найден"})
                continue
            results.append({
                "id": data.get("id"),
                "globalId": data.get("globalId"),
                "name": data.get("name"),
                "state": data.get("state"),
                "priority": data.get("priority"),
                "entityTypeName": data.get("entityTypeName"),
                "sectionId": data.get("sectionId"),
                "projectId": data.get("projectId"),
                "description": data.get("description") or "",
                "preconditionSteps": _summarize_steps(data.get("preconditionSteps")),
                "steps": _summarize_steps(data.get("steps")),
                "postconditionSteps": _summarize_steps(data.get("postconditionSteps")),
                "tags": [t.get("name") for t in (data.get("tags") or []) if t.get("name")],
                "duration": data.get("duration"),
                "attributes": data.get("attributes") or {},
                "links": data.get("links") or [],
            })
        except Exception as e:
            results.append({"id": work_item_id, "error": str(e)})

    return json.dumps(results, ensure_ascii=False, indent=2)


# ─── Tool: массовое создание work items ───────────────────────────────────────

@mcp.tool(
    description=(
        "Массово создать несколько work items за один вызов. "
        "items: JSON-строка массива объектов. Каждый объект: "
        '{"section_id": "<uuid>", "name": "...", '
        '"precondition_steps": [{"action":"...","expected":"...","testData":null}], '
        '"steps": [...], "postcondition_steps": [...], '
        '"priority": "Low|Medium|High", "state": "Ready|NeedsWork|NotReady", '
        '"entity_type": "TestCases|CheckLists", "description": "..."}. '
        "Обязательны: section_id, name. Остальные поля опциональны. "
        "Возвращает список результатов с созданными id."
    )
)
def testit_bulk_create_work_items(items: str) -> str:
    """
    items: JSON-строка списка объектов.
    Обязательные поля каждого объекта: section_id, name.
    Создаёт кейсы последовательно, возвращает сводку результатов.
    """
    try:
        creates: list[dict] = json.loads(items)
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Невалидный JSON в items: {e}"})

    if not isinstance(creates, list):
        return json.dumps({"error": "items должен быть массивом"})

    project_id = _project_uuid()
    results = []

    for item in creates:
        section_id = item.get("section_id", "")
        name = item.get("name", "")
        if not section_id or not name:
            results.append({"name": name or "<no name>", "ok": False, "error": "section_id и name обязательны"})
            continue

        try:
            def _resolve_new_steps(key: str) -> list[dict]:
                raw = item.get(key, [])
                if isinstance(raw, str):
                    raw = json.loads(raw)
                return _normalize_steps(raw)

            payload = {
                "projectId": project_id,
                "sectionId": section_id,
                "name": name,
                "entityTypeName": item.get("entity_type", "TestCases"),
                "description": item.get("description", ""),
                "state": item.get("state", "Ready"),
                "priority": item.get("priority", "Medium"),
                "duration": 600000,
                "attributes": {},
                "tags": [],
                "links": [],
                "preconditionSteps": _resolve_new_steps("precondition_steps"),
                "steps": _resolve_new_steps("steps"),
                "postconditionSteps": _resolve_new_steps("postcondition_steps"),
            }
            created = _api("POST", "/api/v2/workItems", payload)
            cid = created.get("id", "<no-id>") if isinstance(created, dict) else "<unknown>"
            results.append({"name": name, "ok": True, "id": cid})

        except Exception as e:
            results.append({"name": name, "ok": False, "error": str(e)})

    total = len(results)
    success = sum(1 for r in results if r.get("ok"))
    return json.dumps(
        {"total": total, "success": success, "failed": total - success, "results": results},
        ensure_ascii=False,
        indent=2,
    )


# ─── Tool: создать work item ───────────────────────────────────────────────────

@mcp.tool(
    description=(
        "Создать новый work item (тест-кейс) в указанной секции. "
        "steps / precondition_steps / postcondition_steps: JSON-строка списка "
        '[{"action":"...", "expected":"...", "testData":null}]. '
        "entity_type: TestCases (по умолчанию) | CheckLists. "
        "state: Ready (по умолчанию) | NeedsWork | NotReady. "
        "priority: Low | Medium (по умолчанию) | High."
    )
)
def testit_create_work_item(
    section_id: str,
    name: str,
    steps: str = "[]",
    precondition_steps: str = "[]",
    postcondition_steps: str = "[]",
    priority: str = "Medium",
    state: str = "Ready",
    entity_type: str = "TestCases",
    description: str = "",
) -> str:
    project_id = _project_uuid()

    try:
        parsed_steps = _normalize_steps(json.loads(steps))
        parsed_pre = _normalize_steps(json.loads(precondition_steps))
        parsed_post = _normalize_steps(json.loads(postcondition_steps))
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Невалидный JSON в steps/precondition_steps/postcondition_steps: {e}"})

    payload = {
        "projectId": project_id,
        "sectionId": section_id,
        "name": name,
        "entityTypeName": entity_type,
        "description": description,
        "state": state,
        "priority": priority,
        "duration": 600000,
        "attributes": {},
        "tags": [],
        "links": [],
        "preconditionSteps": parsed_pre,
        "steps": parsed_steps,
        "postconditionSteps": parsed_post,
    }
    created = _api("POST", "/api/v2/workItems", payload)
    cid = created.get("id", "<no-id>") if isinstance(created, dict) else "<unknown>"
    return json.dumps({"ok": True, "id": cid, "name": name}, ensure_ascii=False)


# ─── Tool: проверка подключения ────────────────────────────────────────────────

@mcp.tool(description="Проверить подключение к Test IT и вернуть данные проекта.")
def testit_ping() -> str:
    try:
        project_id = _project_uuid()
        data = _api("GET", f"/api/v2/projects/{project_id}")
        if isinstance(data, dict):
            return json.dumps(
                {
                    "ok": True,
                    "project_id": project_id,
                    "project_name": data.get("name"),
                    "base_url": BASE_URL,
                },
                ensure_ascii=False,
            )
        return json.dumps({"ok": True, "project_id": project_id, "base_url": BASE_URL})
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)})


# ─── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    mcp.run(transport="stdio")
