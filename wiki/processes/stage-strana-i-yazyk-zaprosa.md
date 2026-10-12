---
title: Страна и язык запроса на stage — откуда их берёт бэк
summary: Бэк на stage берёт страну по IP, а не из клиентского X-Country; подмены X-Override-Country и X-Override-Accept-Language работают. Как проверить запросом.
tags: [stage, headers, region, auth, debug-screen]
updated: 2026-10-12
sources:
  - KISS-6975, чтение kiss2-infra (lua-шлюз dev-fra1) и go-kiss2-lib/headers, запросы к api-stage 2026-10-12
---

Важно для любой фичи, которая зависит от страны или языка: способы входа, офферы, VK.

- **Страна.** Шлюз api-stage (`kiss2-infra`,
  `manifests/dev-fra1/gateway-api/configmap-api-headers-lua.yaml`) пишет `X-Calculated-Country`.
  Это `X-Override-Country`, если он задан, иначе страна по IP (MaxMind). Бэк
  (`go-kiss2-lib` `headers.GetCountry`) читает сначала `X-Calculated-Country`. Клиентский
  `X-Country` на ответ не влияет: запрос с `X-Country: RU` с болгарского IP получил список без
  VK.
- **Язык.** `X-Override-Accept-Language`, если задан, подменяет `Accept-Language`. Бэк берёт
  первые две буквы до `-`; если код языка не из двух букв — `en`.
- **Подмена в приложении.** Дебаг-экран → «Region Override» (Country, Accept-Language). Действует
  только на stage-бэкенде, применяется после «Save» с перезапуском. Переживает выход из аккаунта.
- **IP машины агента** 12.10.2026 — BG. Телефон в той же сети, вероятно, тоже BG: язык en без
  подмены даёт ответы «не из VK-стран».
- **Проверка запросом** (без авторизации):
  `curl -H "X-Platform: android" -H "Accept-Language: en-US" [-H "X-Override-Country: RU"] https://api-stage.kisskissplay.com/user/api/v1/login/availability`.

## Связано
- [[adb-progon-na-telefone]]
- [[veb-stendy-wasm]]
