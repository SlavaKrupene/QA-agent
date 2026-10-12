---
title: Бустеры Kiss Pass на stage — как выдать и что учесть
summary: Как выдать бустер очков Kiss Pass тестовому юзеру на stage админским запросом, чем он отличается от штатного, и про часовые сезоны stage.
tags: [kiss-pass, battlepass, booster, stage, phase-2]
updated: 2026-10-08
sources:
  - KISS-6908, ответ пользователя в чате (2026-10-08)
  - go-kiss2-battlepass 9360aca, pointrecordctrl/controller.go (CreateBattlePassPointBooster)
---

**Сезон Kiss Pass на проде длится 15 дней, на stage — около часа** (со слов пользователя, 2026-10-08). Часовой stage-сезон подтверждён на
KISS-6908: сезон, в котором выдали бустер в 11:51Z, кончился в 12:29:59Z, и в новом сезоне
`GET /pointBooster` вернул пустой список. Всё, что привязано к сезону, на stage живёт не дольше часа: бустеры, прогресс,
онбординг сезона. На проде такие сценарии не воспроизвести, поэтому тестируем через
админскую выдачу.

## Как выдать бустер

- Скрипт `scripts/stage-booster.sh` в qa-agent:
  - `bash scripts/stage-booster.sh get <userId>` — активные бустеры юзера (label, multiplier,
    endsAt);
  - `bash scripts/stage-booster.sh grant <userId> [type] [multiplier]` — выдать, по умолчанию
    `big_update` x2. Ответ `204` — выдано, или сезона сейчас нет (тогда no-op).
- Ручка: `POST https://api-stage.kisskissplay.com/battlepass/api/v1/pointBooster/{userId}`, тело
  `{"type": "<paid_track|miniapp|big_update>", "modifierMultiplier": <число>}`. Нужен
  админский токен.
- Токен: `ADMIN_TOKEN` в `qa-agent/.env`, живёт меньше часа (на KISS-6908 протух примерно за 40 минут). `401` — протух. Обновить:
  `python scripts/refresh-admin-token.py`. Скрипт логинится админом через хелпер
  KissKiss2QAAssistant. **Запускает пользователь**, агент вход по паролю не выполняет.
- Разрешение для агента: `Bash(bash scripts/stage-booster.sh:*)` в `.claude/settings.json`.

## Чем админский бустер отличается от штатного

- `endsAt` = конец текущего сезона Kiss Pass, а не срок, который задаёт фича (у штатного
  `big_update` — конец ивента).
- Сокет-нотис `battlePassPointBooster.created` **не уходит**: ручка идёт через `Replace`, а
  событие шлёт только `Create`. Клиент узнает о бустере только на следующем старте сессии.
- `pointTypes` пустой, то есть бустер действует на все типы очков, кроме покупки уровня.
- Бустер того же типа заменяется, а не дублируется.
- Новый сезон — бустера в ответе больше нет, выдавать заново.

## Бустеры VIP-баллов — отдельно

Бустеры VIP-баллов живут в `go-kiss2-vip`, а не в battlepass. Пример — `big_update` ивента
«Большое обновление», KISS-6907. Удваивают VIP-баллы за покупки, пока VIP-уровень < 10.
Админской ручки выдачи там нет, только `GET /api/v1/pointBooster/{userId}`, так что на stage
вручную не выдать. Бустеры battlepass и VIP выдаются независимо друг от друга.

## Связано
- [[istochniki-pravdy]]
