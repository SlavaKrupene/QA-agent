#!/usr/bin/env python3
"""
Daily digest of KISS tasks in development, for distributing them between testers.

Read-only: the only HTTP method in this file is GET (same rule as mcp-jira/server.py).
Credentials: JIRA_URL / JIRA_EMAIL / JIRA_API_TOKEN from the project .env.

Two steps, so the facts stay deterministic and the model only writes prose:

  python scripts/jira-digest.py collect   -> digests/<date>.json  (facts + text for summaries)
  (model writes digests/<date>.summaries.json: {"KISS-1": {"gist": "...", "qa": "..."}})
  python scripts/jira-digest.py render    -> digests/<date>.md    (works without summaries too)

"New since last run" uses digests/.state.json; first run looks back one working day.
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "digests"
STATE = OUT_DIR / ".state.json"

PROJECT = "KISS"
TESTER_FIELD = "customfield_11539"
TESTER_JQL = "cf[11539]"
# Jira fills «Тестировщик» with a default person; such a value is not a decision yet.
# Update when the default changes (both may coexist on older tasks for a while).
DEFAULT_TESTERS = {"Радмир Ахметьянов"}
# Status ids, not names: names come back localized. 11481 = «В работе», 10109 = «На ревью»,
# 11417 = «К тестам», 11402 = «Тестирование» (GET /rest/api/3/project/KISS/statuses).
DEV_STATUSES = "11481, 10109"
QA_STATUSES = "11417, 11402"
QA_TYPES = "Task, Bug, Sub-task"
FIELDS = ",".join([
    "summary", "status", "issuetype", "assignee", TESTER_FIELD, "parent", "components",
    "priority", "labels", "statuscategorychangedate", "description", "comment", "issuelinks",
])
LONG_IN_WORK_DAYS = 14
DESC_LIMIT = 1500
COMMENT_LIMIT = 400


# ─── Jira (GET only) ──────────────────────────────────────────────────────────

def _env() -> dict[str, str]:
    env: dict[str, str] = {}
    for raw in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def _ssl_ctx() -> ssl.SSLContext:
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


class Jira:
    def __init__(self) -> None:
        env = _env()
        self.base = env.get("JIRA_URL", "").rstrip("/")
        if not self.base or not env.get("JIRA_EMAIL") or not env.get("JIRA_API_TOKEN"):
            raise SystemExit("JIRA_URL / JIRA_EMAIL / JIRA_API_TOKEN не заданы в .env")
        raw = f"{env['JIRA_EMAIL']}:{env['JIRA_API_TOKEN']}".encode("utf-8")
        self.auth = "Basic " + base64.b64encode(raw).decode("ascii")

    def get(self, path: str) -> Any:
        req = urllib.request.Request(
            self.base + path,
            headers={"Authorization": self.auth, "Accept": "application/json"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, context=_ssl_ctx(), timeout=60) as r:
                return json.loads(r.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="ignore")[:500]
            raise SystemExit(f"Jira HTTP {e.code}: {body}") from e

    def search(self, jql: str, fields: str = FIELDS) -> list[dict]:
        issues: list[dict] = []
        token = ""
        while True:
            q = {"jql": jql, "maxResults": 100, "fields": fields}
            if token:
                q["nextPageToken"] = token
            page = self.get("/rest/api/3/search/jql?" + urllib.parse.urlencode(q))
            issues += page.get("issues", [])
            token = page.get("nextPageToken") or ""
            if page.get("isLast", True) or not token:
                return issues


# ─── Field helpers ────────────────────────────────────────────────────────────

def adf_text(node: Any, urls: list[str]) -> str:
    """Atlassian Document Format -> plain text; collects link URLs into `urls`."""
    if not isinstance(node, dict):
        return ""
    t = node.get("type")
    attrs = node.get("attrs") or {}
    if t == "text":
        for m in node.get("marks") or []:
            href = (m.get("attrs") or {}).get("href")
            if m.get("type") == "link" and href:
                urls.append(href)
        return node.get("text", "")
    if t in ("inlineCard", "blockCard", "embedCard"):
        if attrs.get("url"):
            urls.append(attrs["url"])
        return attrs.get("url", "")
    if t == "mention":
        return attrs.get("text", "")
    if t == "hardBreak":
        return "\n"
    inner = "".join(adf_text(c, urls) for c in node.get("content") or [])
    if t in ("paragraph", "heading", "listItem", "codeBlock", "blockquote", "tableRow"):
        return inner.strip() + "\n"
    return inner


def squeeze(text: str, limit: int) -> str:
    text = re.sub(r"\n{2,}", "\n", re.sub(r"[ \t]+", " ", text)).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def person(v: Any) -> str | None:
    if isinstance(v, list):
        names = [person(x) for x in v]
        return ", ".join(n for n in names if n) or None
    if isinstance(v, dict):
        return v.get("displayName")
    return None


def parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    return datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")


def side(summary: str, components: list[str]) -> str:
    tags = {c.lower() for c in components}
    for m in re.findall(r"\[([^\]]+)\]", summary):
        tags |= {p.strip().lower() for p in re.split(r"[/,]", m)}
    sides = [s for s, keys in (("Client", {"client"}), ("Server", {"server", "room", "migration"}))
             if tags & keys]
    return "/".join(sides)


def slim(issue: dict, base: str, new_keys: set[str], now: datetime) -> dict:
    f = issue["fields"]
    urls: list[str] = []
    desc = squeeze(adf_text(f.get("description"), urls), DESC_LIMIT)
    comments = []
    for c in ((f.get("comment") or {}).get("comments") or [])[-3:]:
        body = squeeze(adf_text(c.get("body"), urls), COMMENT_LIMIT)
        if body:
            comments.append(f"{person(c.get('author')) or '?'}: {body}")
    since = parse_dt(f.get("statuscategorychangedate"))
    parent = f.get("parent") or {}
    components = [c.get("name", "") for c in f.get("components") or []]
    links = []
    for link in f.get("issuelinks") or []:
        other = link.get("outwardIssue") or link.get("inwardIssue") or {}
        if other.get("key"):
            links.append(f"{other['key']} {(other.get('fields') or {}).get('summary', '')}".strip())
    return {
        "key": issue["key"],
        "url": f"{base}/browse/{issue['key']}",
        "summary": f.get("summary", "").strip(),
        "type": (f.get("issuetype") or {}).get("name"),
        "status": (f.get("status") or {}).get("name"),
        "side": side(f.get("summary", ""), components),
        "priority": (f.get("priority") or {}).get("name"),
        "developer": person(f.get("assignee")),
        "tester": person(f.get(TESTER_FIELD)),
        "parent": {"key": parent.get("key"),
                   "summary": (parent.get("fields") or {}).get("summary")} if parent else None,
        "in_status_category_since": since.isoformat(timespec="minutes") if since else None,
        "days_in_work": (now - since).days if since else None,
        "is_new": issue["key"] in new_keys,
        "confluence": sorted({u for u in urls if "atlassian.net/wiki" in u}),
        "figma": bool([u for u in urls if "figma.com" in u]),
        "links": links[:6],
        "description": desc,
        "last_comments": comments,
    }


# ─── collect ──────────────────────────────────────────────────────────────────

def default_since(now: datetime) -> datetime:
    # First run: back to the start of the previous working day (Monday looks at Friday).
    back = 3 if now.weekday() == 0 else 1
    return (now - timedelta(days=back)).replace(hour=0, minute=0, second=0, microsecond=0)


def collect(args: argparse.Namespace) -> Path:
    jira = Jira()
    now = datetime.now()
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    since = (datetime.fromisoformat(args.since) if args.since
             else datetime.fromisoformat(state["last_run"]) if state.get("last_run")
             else default_since(now))
    since_jql = since.strftime("%Y/%m/%d %H:%M")

    dev = jira.search(f"project = {PROJECT} AND status in ({DEV_STATUSES}) "
                      f"AND issuetype in ({QA_TYPES}) ORDER BY updated DESC")
    new_keys = {i["key"] for i in jira.search(
        f'project = {PROJECT} AND status CHANGED TO "In Progress" AFTER "{since_jql}"', "summary")}
    qa_no_tester = jira.search(f"project = {PROJECT} AND status in ({QA_STATUSES}) "
                               f"AND issuetype in ({QA_TYPES}) AND {TESTER_JQL} is EMPTY "
                               f"ORDER BY updated DESC")
    not_qa = jira.search(f"project = {PROJECT} AND status in ({DEV_STATUSES}) "
                         f"AND issuetype not in ({QA_TYPES})", "summary,issuetype")

    data = {
        "generated_at": now.isoformat(timespec="minutes"),
        "new_since": since.isoformat(timespec="minutes"),
        "in_development": [slim(i, jira.base, new_keys, now) for i in dev],
        "in_testing_without_tester": [slim(i, jira.base, set(), now) for i in qa_no_tester],
        "not_for_qa": [{"key": i["key"], "type": i["fields"]["issuetype"]["name"],
                        "summary": i["fields"]["summary"]} for i in not_qa],
    }
    OUT_DIR.mkdir(exist_ok=True)
    out = OUT_DIR / f"{args.date}.json"
    out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    if not args.keep_state:
        STATE.write_text(json.dumps({"last_run": data["generated_at"]}), encoding="utf-8")
    dev_items = data["in_development"]
    print(f"{out.relative_to(ROOT)}: в разработке {len(dev_items)}, "
          f"новых {sum(t['is_new'] for t in dev_items)}, "
          f"без тестировщика {sum(not t['tester'] for t in dev_items)}, "
          f"в тесте без тестировщика {len(data['in_testing_without_tester'])}, "
          f"не для QA {len(data['not_for_qa'])}")
    return out


# ─── render ───────────────────────────────────────────────────────────────────

KIND_ORDER = {"early": 0, "test": 1, "none": 2}


def cell(s: str | None) -> str:
    return (s or "—").replace("|", "\\|").replace("\n", " ").strip()


def fallback_gist(t: dict) -> str:
    first = re.split(r"(?<=[.!?])\s|\n", t["description"] or "", maxsplit=1)[0]
    return squeeze(first, 220) if first else "описания нет"


def kind(t: dict, summaries: dict) -> str:
    # Derived from the phrases runbooks/daily-digest.md prescribes for the "qa" field.
    qa = (summaries.get(t["key"], {}).get("qa") or "").lower()
    if "ранний разбор" in qa:
        return "early"
    if "тестировать нечего" in qa:
        return "none"
    return "test"


def tester(t: dict) -> str:
    name = t["tester"]
    if not name:
        return "**не назначен**"
    return f"{name} (по умолч.)" if name in DEFAULT_TESTERS else name


def for_qa(t: dict, summaries: dict) -> str:
    parts = [summaries.get(t["key"], {}).get("qa") or ""]
    if t["confluence"]:
        parts.append("есть ТЗ")
    if t["figma"]:
        parts.append("есть макет")
    return " · ".join(p for p in parts if p) or "—"


def days(t: dict) -> str:
    d = t["days_in_work"]
    if d is None:
        return "—"
    return f"⏳ {d}" if d >= LONG_IN_WORK_DAYS else str(d)


def link(t: dict) -> str:
    return f"[{t['key']}]({t['url']})"


def table(head: list[str], rows: list[list[str]]) -> list[str]:
    if not rows:
        return ["_Нет._"]
    return (["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
            + ["| " + " | ".join(cell(c) for c in r) + " |" for r in rows])


def render(args: argparse.Namespace) -> Path:
    src = OUT_DIR / f"{args.date}.json"
    data = json.loads(src.read_text(encoding="utf-8"))
    sp = OUT_DIR / f"{args.date}.summaries.json"
    summaries = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {}

    dev = data["in_development"]
    qa_free = data["in_testing_without_tester"]
    new = sorted((t for t in dev if t["is_new"]),
                 key=lambda t: (KIND_ORDER[kind(t, summaries)], t["key"]))
    rest = sorted((t for t in dev if not t["is_new"]),
                  key=lambda t: (t["tester"] or "", -(t["days_in_work"] or 0)))
    gen = datetime.fromisoformat(data["generated_at"])
    since = datetime.fromisoformat(data["new_since"])
    nkinds = defaultdict(int)
    for t in new:
        nkinds[kind(t, summaries)] += 1
    load: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for t in dev:
        load[tester(t)][0] += 1
        load[tester(t)][1] += t["is_new"]
    nq_kinds: dict[str, int] = defaultdict(int)
    for t in data["not_for_qa"]:
        nq_kinds[t["type"]] += 1

    summary_rows = [
        ["В разработке («В работе» и «На ревью»)", str(len(dev))],
        [f"Новые с {since:%d.%m %H:%M}", str(len(new))],
        ["из них кандидаты в ранний разбор", str(nkinds["early"])],
        ["из них тестировать нечего", str(nkinds["none"])],
        ["Тестировщик стоит по умолчанию", str(sum(t["tester"] in DEFAULT_TESTERS for t in dev))],
        ["Уже в тесте без тестировщика", str(len(qa_free))],
        ["Не для QA (" + ", ".join(f"{k} {v}" for k, v in nq_kinds.items()) + ")",
         str(len(data["not_for_qa"]))],
    ]
    new_rows = [[link(t), f"**{t['summary']}.** "
                 f"{summaries.get(t['key'], {}).get('gist') or fallback_gist(t)}",
                 " · ".join(x for x in (t["type"], t["side"]) if x),
                 t["developer"], tester(t), for_qa(t, summaries)] for t in new]
    rest_rows = [[link(t), t["summary"], days(t), t["developer"], tester(t), for_qa(t, summaries)]
                 for t in rest]
    qa_rows = [[link(t), t["summary"], t["status"], t["developer"], for_qa(t, summaries)]
               for t in qa_free]

    out: list[str] = [
        f"# Задачи в разработке — {gen:%d.%m.%Y}",
        "",
        f"Собрано {gen:%d.%m %H:%M}. Типы: задача, баг, подзадача. "
        f"«По умолч.» — тестировщик стоит автоматически, решение за тобой.",
        "",
        *table(["Показатель", "Число"], summary_rows),
        "",
        "## Нагрузка по тестировщикам",
        "",
        *table(["Тестировщик", "В разработке", "Из них новых"],
               [[k, str(v[0]), str(v[1])] for k, v in sorted(load.items(), key=lambda kv: -kv[1][0])]),
        "",
        f"## Новые в работе ({len(new)})",
        "",
        "Сначала кандидаты в ранний разбор, потом обычная проверка, в конце — где тестировать нечего.",
        "",
        *table(["Задача", "Что делают", "Тип", "Разработчик", "Тестировщик", "Для QA"], new_rows),
        "",
        f"## Уже в тесте, тестировщик не назначен ({len(qa_free)})",
        "",
        *table(["Задача", "Название", "Статус", "Разработчик", "Для QA"], qa_rows),
        "",
        f"## Остальные в разработке ({len(rest)})",
        "",
        f"Дней — с перехода в работу; ⏳ — {LONG_IN_WORK_DAYS} и больше.",
        "",
        *table(["Задача", "Название", "Дней", "Разработчик", "Тестировщик", "Для QA"], rest_rows),
    ]
    md = OUT_DIR / f"{args.date}.md"
    md.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")

    # Short version for the chat: the summary and the new tasks only.
    chat = [*table(["Показатель", "Число"], summary_rows[:5]), "",
            *table(["Задача", "Название", "Тестировщик", "Для QA"],
                   [[t["key"], t["summary"], tester(t), for_qa(t, summaries)] for t in new])]
    missing = [t["key"] for t in dev + qa_free if t["key"] not in summaries]
    print(f"{md.relative_to(ROOT).as_posix()}; без краткого описания от модели: {len(missing)}\n")
    print("\n".join(chat))
    return md


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("step", choices=["collect", "render"])
    p.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"), help="имя файлов в digests/")
    p.add_argument("--since", help="ISO-время для «новых»; по умолчанию — прошлый запуск")
    p.add_argument("--keep-state", action="store_true", help="не сдвигать отметку прошлого запуска")
    args = p.parse_args()
    collect(args) if args.step == "collect" else render(args)


if __name__ == "__main__":
    main()
