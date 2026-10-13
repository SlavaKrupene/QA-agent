---
title: Прогон на телефоне (adb, iPhone) — приёмы и ограничения
summary: Как агент гоняет kiss2 на телефоне пользователя: где adb, как читать логи, запросы и аналитику, как сдвигать дату и успевать тапнуть раньше модалки.
tags: [phase-2, adb, android, logcat, analytics, modal-queue]
updated: 2026-10-13
sources:
  - KISS-6975, прогон 2026-10-13 (TECNO LI6, Rooms 10.3.0)
  - KISS-6908, прогон 2026-10-08 (TECNO LI6, kiss2 10.1.0)
---

- **adb** не в `PATH`: `"$LOCALAPPDATA/Android/Sdk/platform-tools/adb.exe"`. Телефон
  пользователя — TECNO LI6, экран 1080x2460, тачскрин `/dev/input/event4`.
- **Вход в аккаунт** делает пользователь: экран входа брендирован «Rooooms». userId видно в
  логах (`userId: <uuid>`, `path=/…/user/<uuid>`).
- **Логи:** до начала поднять буфер — `adb logcat -G 16M`, иначе старт сессии вытесняется за
  минуту. В debug/qa-сборке:
  - запросы — `_tag=net _msg=http method=… path=… st=… ms=…`;
  - роуты — `"Route changed" currentPath=…`;
  - тела ответов печатаются целиком.

  В лог попадают заголовки `authorization` с токеном юзера — лог целиком не копировать и не
  цитировать.
- **Аналитика:** события уходят батчем в `POST /clievent/api/v1/clientEvent`. Тело в логе —
  массив байтов: декодировать в JSON. Имя события = component + `Click`, например
  `showBigUpdateEventClick`, плюс `location` — текущий роут.
- **Сдвиг даты** (раз-в-сутки-логика):
  - `adb shell settings put global auto_time 0`;
  - `adb shell cmd alarm set-time <ms>`;
  - вернуть: `settings put global auto_time 1`.

  `AppDateTime.now()` клиента синхронизирован с сервером, поэтому таймеры и проверки сроков
  сдвиг не замечают. Сдвиг на несколько дней поднимает «Оцените Rooms».
- **Тап раньше модалки очереди.** Модалка открывается через ~0,1–0,9 с после лобби.
  - Не работают: `adb input tap` (старт процесса ~1 с), `sendevent` (запрещён SELinux), monkey
    `--port` (не отвечает).
  - Работает «пулемёт» на устройстве: `while [ ! -f stop ]; do input tap X Y & sleep 0.15; done`
    со стоп-файлом от фонового `logcat | grep -m1 'currentPath=/room'`.
- **Язык и регион без системных настроек** (Android 13+): `adb shell cmd locale set-app-locales
  gg.playneta.kiss2 --user 0 --locales en-KZ`, сброс — `--locales ""`. Flutter видит это как локаль
  устройства: `X-Country: KZ`, `Accept-Language: en-KZ`. `pm clear` этот язык сбрасывает — задавать
  после очистки.
- **Сеть:** `adb shell cmd connectivity airplane-mode enable|disable`. После выключения Wi-Fi поднимается
  10–30 с — ждать `adb shell ping -c1 8.8.8.8`, иначе запросы падают с `connectionError`.
- **Чтение данных приложения** (debuggable-сборка): `adb shell run-as gg.playneta.kiss2 cat
  shared_prefs/FlutterSharedPreferences.xml | grep <ключ>`. Целиком не выводить: там данные аккаунта.
- **Дебаг-экран** (долгое нажатие в правом верхнем углу) через `adb input swipe` / `motionevent` не
  открывается (2026-10-13) — подмену региона заменять языком приложения выше.
- **IP телефона** (Wi-Fi `RT-…`) сервер считает «VK-страной» (2026-10-13): онлайн VK на экране входа
  при любом языке.
- **Очередь модалок:**
  - на экране поиска комнаты (`/room`) очередь на паузе;
  - в ToD-комнате она на паузе, пока ход за юзером;
  - офферы на этом телефоне не грузятся («No app product provider»).

## iPhone (Windows, без Mac)

- Драйвер — приложение «Apple Devices» из Microsoft Store (или iTunes). Телефон по кабелю,
  «Доверять этому компьютеру».
- Инструмент — `pymobiledevice3` (`python -m pip install pymobiledevice3`), ставит
  пользователь. Проверка: `python -m pymobiledevice3 usbmux list`.
- Лог приложения: `python -m pymobiledevice3 syslog live -pn Runner -o <файл>`. Фильтр по
  процессу обязателен, остальной лог телефона — личный. Строки `flutter: _ts=… _tag=net …` —
  в том же формате, что logcat на Android: запросы, роуты, тела ответов. Проверено на
  iPhone17,3, iOS 26.6, stage-сборке 2026-10-08.
- Скриншоты и тапы с Windows недоступны (нужен режим разработчика и туннель) — экран
  присылает пользователь.

## Связано
- [[stage-kiss-pass-boostery]]
