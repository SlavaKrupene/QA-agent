# Профиль проекта

Всё, что отличает этот проект от шаблона. Заполняется при настройке ([START-HERE.md](START-HERE.md))
и дополняется по ходу работы. Runbook'и берут конкретику отсюда — сами они общие.
Секретов здесь не держать: токены и пароли — в `.env`, здесь только «где лежит».

```yaml
status: configured          # not-configured | configured
configured_at: 2026-09-11   # пробный прогон KISS-5470 сделан, замечания QA внесены
language: ru                # язык чек-листов
lens_model: opus            # opus | sonnet — модель суб-агентов-луп (sonnet экономит лимиты)
publish: git                # git — коммит и push checklists/ + wiki/ в https://github.com/SlavaKrupene/QA-agent
```

## Трекер

```yaml
tracker: jira-mcp           # jira-mcp — через MCP | paste — пользователь вставляет текст задачи
jira_url: https://tfgames.atlassian.net
jira_auth: api-token        # api-token (mcp-jira/, свой сервер) | oauth (официальный Atlassian MCP)
project_key: KISS           # предположение по веткам/коммитам (KISS-XXXX) — подтвердить
mcp_read_tools:
  - jira_ping
  - jira_get_issue
  - jira_search
confluence: mcp             # mcp-confluence/, тот же API-токен — читать, когда в задаче ссылка на ТЗ
confluence_read_tools:
  - confluence_ping
  - confluence_get_page
  - confluence_search
```

Официальный Atlassian MCP (`https://mcp.atlassian.com/v2/mcp`, OAuth в браузере, покрывает
и Jira, и Confluence) не смог пройти авторизацию в этом типе сессии (десктоп-приложение
сообщало «non-interactive», вход через `/mcp` не заводился). Вместо него — свои серверы
[mcp-jira/](../mcp-jira/) и [mcp-confluence/](../mcp-confluence/) на одном и том же
API-токене Jira/Confluence Cloud (Basic auth), **без единой пишущей функции в коде** (не
просто запрет политикой — физическое отсутствие реализации). Оба проверены на реальных
данных (2026-09-11): `jira_get_issue` прочитал KISS-5470/KISS-5469,
`confluence_get_page` — страницу ТЗ «Сокровища Египта», на которую там ссылка. Если в
другом окружении OAuth заработает — можно вернуться к официальному серверу, см.
`mcp-jira/README.md`.

## Репозитории приложения

Только чтение. Путь — локальная папка (абсолютный путь или `repos/<name>` внутри этого проекта).

| Имя | Путь | Что это | Стек |
|---|---|---|---|
| kiss-flutter | repos/kiss-flutter | Приложение (3 флейвора: kiss2/lovium/gozo) | Flutter (Android/iOS/Web), Dart |
| kiss2-miniapp-bigchallenge | repos/kiss2-miniapp-bigchallenge | Мини-апп «Большой вызов» (WebView внутри kiss-flutter/kiss2) — отдельный репозиторий на одну фичу | Node.js/TS: Fastify+Prisma+Redis+Kafka (backend), React Router 7 (frontend) |

### kiss-flutter

```yaml
base_branch: development
branch_pattern: "feature/<KEY>_slug, bugfix/<KEY>_slug, release/x.y.z"
commit_pattern: "<KEY> описание (#PR)  или  <KEY>: описание"
examples:
  - feature/KISS-6593_prestige_points_source_state
  - bugfix/KISS-6198_season_reward_fitting_room
  - feature/KISS-6015_punk_driver-0
```

### kiss2-miniapp-bigchallenge

**Другой workflow — не по образцу kiss-flutter.** Одна ветка `main`, задачные ветки не
хранятся (PR мержится и ветка удаляется), в коммитах **нет** ключей Jira (conventional
commits: `feat:`/`fix:`/`ci:` с описанием на английском). Весь репозиторий — одна фича
(«Большой вызов», KISS-5469/KISS-5470 и связанные), поэтому «дифф задачи» тут не ищется
по ветке/коммиту.

```yaml
base_branch: main
branch_pattern: "нет постоянных задачных веток — PR в main, ветка удаляется после мержа"
commit_pattern: "conventional commits (feat:/fix:/ci:), без ключей Jira"
diff_strategy: whole-tree     # для одноцелевого репозитория без веток на задачу —
                              # подтверждено пользователем (2026-09-11) на KISS-5470:
                              # весь текущий packages/frontend + packages/backend
                              # в main = предмет приёмочной проверки, не инкремент
spec_source: docs/spec.md     # копия ТЗ из Confluence в самом репо — дешевле и быстрее
                              # 40k-токенной страницы Confluence, сверять актуальность
                              # по дате в шапке файла
```

## Платформа и стек

```yaml
platform: flutter                      # кроссплатформенно: Android + iOS (+ web)
application_id: gg.playneta.kiss2      # флейвор kiss2 (дефолт); lovium=mahjong.club.casino.poker.solitaire; gozo=dominoes.battle.vamos.higgs
min_sdk:                               # задаётся Flutter SDK (flutter.minSdkVersion), не зафиксировано в проекте
target_sdk:                            # задаётся Flutter SDK (flutter.targetSdkVersion)
build_variants: "3 флейвора (kiss2/lovium/gozo) × стандартные Flutter build types (debug/profile/release)"
tests: "юнит: test/src/<feature>/<layer> (зеркалит lib/src/features), packages/*/test; test/architecture — архитектурные гварды; integration_test/ — только нативный webp-плагин, UI/e2e тестов фич нет"
```

## Куда смотреть в коде

Таблица «что нужно узнать → где в ЭТОМ репо смотреть». Собирается при настройке из
`stack-hints/` и проверяется на реальных путях. Используется правилом R3 в
[runbooks/generate-checklist.md](runbooks/generate-checklist.md) и всеми лупами.

Полная таблица (проверена Glob'ом на репо) — [stack-hints/flutter.md](../stack-hints/flutter.md)
(завели отдельный файл под Flutter — в шаблоне был только Android). Кратко:

| Что нужно узнать | Куда смотреть |
|---|---|
| Флейворы/клоны (kiss2, lovium, gozo) | `flavors/flavors.properties` |
| Фичи и слои (bloc/domain/data/presentation) | `lib/src/features/<feature>/` |
| Эталон архитектуры | `docs/architecture/unified-feature-architecture.md` |
| Сетевые запросы | `Grep "@RestApi"` в `data/` фичи |
| Локальное хранилище | `lib/src/foundation/storage/` |
| Фиче-флаги/доступ | `lib/src/features/feature_access/` |
| Аналитика | `lib/src/foundation/product_analytics/` |
| Юнит-тесты | `test/src/<feature>/<layer>/…_test.dart` |

## Тест-менеджмент (TestIT)

```yaml
testit: mcp                 # mcp — через MCP-сервер testit | none
testit_base_url: https://team-o9bf.testit.software
testit_project: "Kiss Kiss 2.0"    # project_id=1 в .env, UUID резолвится сервером
testit_new_cases_root:      # ["Kiss Kiss 2.0", "🛠️Kiss Kiss 2.0. В разработке", "<фича>", "<Category>"]
testit_new_case_state: NotReady    # статус свежесозданного кейса — всегда, не Ready
testit_auto_upload: no      # выгрузка в TestIT — только по явной просьбе, не автоматически после /qa
```

MCP-сервер — [mcp-testit/](../mcp-testit/) (взят и адаптирован из отдельного проекта
пользователя `TestCaseGenerator/testCaseGenerator-main`, который генерирует тест-кейсы из
Confluence-спек — другой источник, тот же TestIT и тот же стиль оформления). Добавлен свой
инструмент `testit_ensure_section` (ищет/создаёт секцию по цепочке имён) — в оригинале эта
логика была только в отдельном экспорт-скрипте, не в MCP. Полный список инструментов и их
описание — [mcp-testit/README.md](../mcp-testit/README.md).

Из того же проекта переняты правила оформления, принятые в команде для TestIT (см.
runbooks/generate-checklist.md, «Формулировки — принятый в команде стиль для TestIT»):
шаг → результат парой на каждый шаг, «ёлочки» вместо `**bold**`, без «по ТЗ» / «согласно
диффу», без «Проверено, что», Category — подкатегория без имени фичи.

## Стенд и устройства (фаза 2)

```yaml
devices: "реальный телефон, подключается к рабочему компьютеру пользователя"
adb: no                     # adb не установлен на этой машине на момент настройки
install_build: "флейвор kiss2, debug/qa"
backend_stand: https://api-stage.kisskissplay.com
backend_access: "клиентские логи через Android Studio (logcat); серверных логов и БД нет; тестовый аккаунт — свой у пользователя"
roles: "гость (без регистрации) / обычный / diamond-подписчик / участник-владелец клуба"
test_accounts: "свой аккаунт пользователя (логин/креды — не здесь, при необходимости в .env)"
```

## Глоссарий

Термины, названия экранов/фич, принятые сокращения. Чек-лист пишется в этих терминах.

| Термин | Что значит / как писать в чек-листе |
|---|---|
| | |

## Адаптации

Чем эта копия отличается от шаблона: что поменяли в механизме и зачем. Одна строка — одно
изменение. Пишется при настройке и при `/qa-adapt`.

| Дата | Что изменили | Зачем |
|---|---|---|
| 2026-09-11 | Завели [stack-hints/flutter.md](../stack-hints/flutter.md) | В шаблоне был только Android; проект — Flutter (BLoC, 3 флейвора) |
| 2026-09-11 | `origin` репозитория → `https://github.com/SlavaKrupene/QA-agent`, шаблон — в `upstream` | Пользователь дал свой пустой репозиторий для хранения чек-листов |
| 2026-09-11 | Тест-кейс: `Steps` — пары действие→результат на каждый шаг вместо одного общего `Expected`; добавлено поле `Category` | Так устроен TestIT-экспорт (API): у каждого шага свой `expected`, не общий на кейс |
| 2026-09-11 | Подключён MCP `testit` (скопирован и адаптирован из `TestCaseGenerator/testCaseGenerator-main` пользователя, добавлен `testit_ensure_section`) | Кейсы фазы 1 нужно класть прямо в TestIT, а не только в markdown-файл |
| 2026-09-11 | В «Стиль» добавлены правила оформления TestIT (ёлочки, без «по ТЗ», Category без имени фичи и т.д.) | Перенесено из уже принятого в команде стиля другого QA-инструмента на этом же TestIT |
| 2026-09-11 | Загрузка кейсов в TestIT — только по явной просьбе, не автоматически в конце `/qa` | Пользователь предпочёл ревьюить перед загрузкой в общий проект, не заливать сразу |
| 2026-09-11 | Официальный Atlassian MCP заменён на свой [mcp-jira/](../mcp-jira/) (API-токен вместо OAuth, только чтение по построению) | Браузерный OAuth не проходил в этом типе сессии; вставка текста задачи руками не годится — в задачах бывает пустое описание |
| 2026-09-11 | Добавлен [mcp-confluence/](../mcp-confluence/) (тот же токен, только чтение) | Пробный прогон показал: описание задачи в Jira часто пустое, а реальное ТЗ — в Confluence по ссылке |
