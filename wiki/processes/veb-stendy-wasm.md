---
title: Веб-стенды kiss2 и WASM — где что выкачено и как понять, какая сборка загрузилась
summary: Хосты веба (stage, stage1, prod), с какого момента там WASM, как отличить wasm от JS-фоллбэка, как форсировать JS, грабли деплоя и кэша.
tags: [web, wasm, stage, deploy, service-worker, phase-2]
updated: 2026-10-12
sources:
  - KISS-4546, проверка стендов curl'ом и gh run list (2026-10-12)
  - kiss-flutter deploy/k8s/values-*.yaml, .github/workflows/web-release.yml, PR #3004
---

**Хосты веба** (ingress в `deploy/k8s/values-*.yaml`):

- stage — `https://stage-ru.kisskissplay.com`, бэкенд stage;
- stage1 — `https://stage1-ru.kisskissplay.com`, бэкенд stage1;
- prod — `https://app-ru.kisskissplay.com`.

Веб есть только у флейвора kiss2.

**С какого момента WASM.**

- Веб собирается с `--wasm` с KISS-4546: коммит `09cea14ac`, в `development` с 2026-09-30.
- Прод на WASM с релиза 10.0.1, деплой 2026-10-06.
- Stage на WASM как минимум с 2026-10-07.
- На stage1 2026-10-07 выкачен коммит до WASM (`4018e798f`, ветка
  `feature/KISS-4546_web_pre_wasm_stage1`). Похоже, это эталон «до» для сравнения. 2026-10-12 с
  машины агента stage1 не отвечал: DNS резолвится, соединения нет.

## Как понять, какая сборка загрузилась

- `--wasm` выпускает оба варианта сразу. Выбор делает загрузчик `flutter.js` в браузере
  пользователя. В `/<host>/flutter_bootstrap.js` есть build config с двумя записями:
  `dart2wasm`/`skwasm` (`main.dart.wasm`, `main.dart.mjs`) и `dart2js`/`canvaskit`
  (`main.dart.js`).
- DevTools → Network: загрузился `main.dart.wasm`, значит WASM. Загрузился `main.dart.js`,
  значит JS-фоллбэк.
- Версия сборки — `?v=<hash>` у этих файлов, одинаковый для всех.
- Ожидаемые заголовки, проверено на stage и проде 2026-10-12:
  - `.wasm` — `application/wasm`;
  - `.mjs` — `application/javascript`;
  - gzip у всех.
- Веса сборки на stage: `main.dart.wasm` — 33,7 МБ, 10,7 МБ с gzip. `main.dart.js` — 8,9 МБ с
  gzip.
- `skwasm` и `canvaskit` загрузчик берёт с `www.gstatic.com/flutter-canvaskit/<engineRevision>`,
  а не со стенда.

## Как получить JS-вариант на том же стенде

Нужен браузер без WasmGC: Safari или iOS ниже 18.2, Chrome ниже 119. Или Firefox с
`about:config` → `javascript.options.wasm_gc` = `false`. Что загрузчик Flutter в этом случае
выберет JS, не проверено — сверить по Network.

Chrome 119–132 поддерживает WasmGC, но не принимает модуль с более чем 100 000 импортов. Фикс
`6e3a11fc2` (KISS-6561, PR #3146) переключает такие браузеры на JS. До его выкатки в Chrome
119–132 WASM-сборка не запустится.

## Грабли

- Веб деплоится вручную: Actions → «Build and Deploy WEB» (`web-release.yml`), выбор
  `stage`/`stage1`/`prod`. С 2026-10-09 запуски падают с `startup_failure`. Падения начались после
  правки workflow `005190ff3` (`cloud: timeweb`). Пока это так, stage может отставать от
  `development`. Что выкачено, смотреть по `gh run list -R playneta/kiss-flutter --workflow
  web-release.yml`.
- Stage и stage1 собираются в `--profile`, прод в `--release`. Скорость на stage хуже прода.
- Service worker кэширует `.html`, `.js`, `.mjs` и `main.dart.wasm` по CacheFirst. Для чистого
  прогона — Application → Clear site data. Для проверки обновления версии, наоборот, не чистить.
- Stage и stage1 на разных бэкендах: аккаунты и данные между ними не совпадают.
- Service worker регистрируется после первого кадра. На первой загрузке он страницу не
  контролирует, и `main.dart.wasm` попадает в его кэш только со второй загрузки.

## Прогон агентом (KISS-4546, 2026-10-12)

- Встроенный браузер Claude — Chromium 152. Он всегда получает WASM-вариант. Замедлить сеть,
  заблокировать запрос и уйти в офлайн в нём нельзя. Для JS-фоллбэка, Chrome < 133 и
  негатива сети нужен обычный браузер с DevTools.
- Что агент снимает в нём сам, без входа: какие файлы загрузились и откуда
  (`performance.getEntriesByType('resource')`), `crossOriginIsolated`, состояние SW и Cache
  Storage (`caches.keys()`), время до инициализации фреймворка (performance mark
  `2-Framework initialization-begin-1`).
- Spine на телефоне надёжно видно на эмотиконах в комнате и в превью «Красивый поцелуй»
  (Инвентарь → «Красивый поцелуй» → «Каталог»). Рамки аватара из Kiss Pass — animated WebP, а не
  Spine.
- На stage приложение при запуске выдаёт каскад модалок. Часть закрывается только действием:
  - награды прошлого сезона Kiss Pass — «Забрать награды»;
  - ежедневная награда — «Забрать бонус»;
  - новая медаль — «Забрать награду».

  В комнате stage обычно нет других игроков: бутылочке нужен второй аккаунт.

## Связано

- [[adb-progon-na-telefone]]
- [[istochniki-pravdy]]
