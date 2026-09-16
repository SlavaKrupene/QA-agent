# Подсказки: Flutter (Dart, BLoC, feature-модули)

Заготовка для project.md → «Куда смотреть в коде» для кроссплатформенных Flutter-проектов.
Пути ниже проверены на репозитории `kiss-flutter` (see [project.md](../project.md)) — при
подключении другого Flutter-проекта проверить `Glob`'ом заново, лишнее выкинуть.

## Куда смотреть в коде

| Что нужно узнать | Куда смотреть |
|---|---|
| Версия приложения, зависимости | `pubspec.yaml`, `pubspec.lock` |
| Флейворы / клоны приложения (app id, имя, версия) | `flavors/flavors.properties`, `flavors/*.yaml` |
| `applicationId` / `minSdk` / `targetSdk` (Android) | `android/app/build.gradle` |
| Bundle id (iOS) | `ios/Runner.xcodeproj/project.pbxproj` (`PRODUCT_BUNDLE_IDENTIFIER`) |
| Фичи и их структура (слои) | `lib/src/features/<feature>/{bloc,domain,data,presentation}` — см. `docs/architecture/unified-feature-architecture.md` |
| Экраны и навигация | `Grep "GoRoute\|<feature>_scope.dart"`; ScopedState/роут на фичу |
| BLoC: события, состояния, эффекты | `lib/src/features/<feature>/bloc/*.dart` (`Event`/`State`/`Effect` в одном файле `*_bloc.dart`) |
| Бизнес-правила команды | `lib/src/features/<feature>/domain/<feature>_service.dart` |
| Доменные модели | `lib/src/features/<feature>/domain/model/` (`@freezed`) |
| Сетевые запросы, эндпоинты | `Grep "@RestApi"` и `Grep "@GET\|@POST\|@PUT\|@DELETE\|@PATCH"` в `lib/src/features/<feature>/data/` (Retrofit-подобный кодоген); DTO — `lib/src/features/<feature>/data/model/` или общий кодоген `lib/api` |
| Мапперы DTO → доменная модель | `lib/src/features/<feature>/data/*mapper*.dart` |
| Локальное хранилище | `lib/src/foundation/storage/common_local_storage.dart`, `secured_local_storage.dart` — ключи через `Grep "LocalStorage\|SecuredLocalStorage"` |
| Фиче-флаги / доступ к фиче | `lib/src/features/feature_access/` (`feature_access_source_repository.dart`, `feature_access_grant_source.dart`) |
| Аналитика | `lib/src/foundation/product_analytics/` (`product_analytics.dart`, `product_analytics_api.dart`) — новые/изменённые события |
| Пуши / реалтайм-уведомления | `Grep "FirebaseMessaging\|onMessage"`, чат — `lib/src/features/chat/base/bloc/chat_unread_bloc.dart` как пример |
| Realtime / сокет-каналы | `Grep "Channel\|NoticeHandler"` в `data/` фичи — см. §4 архитектурного эталона |
| DI фичи | `<feature>_scope.dart` в каждой фиче, `lib/src/app/locator/app_scope.dart` — общий корень |
| Локализация | `Grep "AppLocalizations\|intl_"`, файлы переводов (Weblate — коммиты `Translations update from Kiss Weblate`) |
| Юнит-тесты | `test/src/<feature>/<layer>/…_test.dart` (зеркалит слои фичи), `packages/*/test` |
| Архитектурные гварды (не поведенческие тесты) | `test/architecture/` |
| UI/интеграционные тесты | `integration_test/` — на момент настройки только нативный webp-плагин, тестов фич нет |
| Debug-инструменты (для ручной проверки) | `lib/src/app/debug/presentation/` (`feature_config_debug_screen.dart`, `messages_debug_screen.dart`) |

## Платформенные риски (для лупы platform и для кейсов типа `platform`)

Проверяй только то, что дифф реально задевает:

- **Жизненный цикл.** Уход в фон/возврат, поворот экрана, смена языка/темы — состояние BLoC не
  теряется, повторный запрос не уходит. `AppLifecycleState` — обработка в фичах реального времени
  (чат, комнаты).
- **Флейворы / клоны.** Изменение в общем коде затрагивает все 3 флейворца (kiss2, lovium, gozo) —
  если правка привязана к одному бренду, проверить, не потекла ли она в остальные (тексты,
  фиче-флаги, ассеты). `lovium`/`gozo` — апдейт поверх старой Unity-игры: миграция локальных данных,
  `versionCode` не должен откатывать пользователя (`VERSION_DOWNGRADE`).
- **Обе платформы.** Правка в общем Dart-коде — по умолчанию задевает и Android, и iOS (и web, если
  экран/поток там доступен); отдельно смотреть платформенные каналы (`MethodChannel`,
  `webp_animation_ffi`, нативные плагины).
- **Локальное хранилище / кеш.** Переименованный ключ или изменённая структура объекта в
  `LocalStorage`/`SecuredLocalStorage` — потеря данных при обновлении. Кейс: поставить прошлую
  версию, набить данные, обновить.
- **Совместимость с бэкендом.** Новый DTO-контракт (`data/model`, `lib/api`) — старые версии
  приложения продолжают ходить в обновлённый API; проверить, что новое поле опционально/с
  дефолтом на старых клиентах.
- **Сеть.** Офлайн на входе и посреди операции, медленная сеть, повтор после восстановления —
  через `Repository`/`Api`, без дублей и без вечного лоадера.
- **Фиче-флаги / доступ.** Новый источник доступа (`feature_access`) — проверить и включённое, и
  выключенное состояние, и переход между ними без перезахода.
- **Локализация.** Новый текст без перевода на других языках — кандидат в кейс (Weblate синхронизируется отдельным коммитом, не мгновенно).
- **Realtime.** Сообщение/событие пришло, пока экран фичи закрыт/приложение в фоне — устройство
  должно отреагировать при возврате, а не потерять событие.
- **Релизная сборка.** Обфускация/`--split-debug-info` может скрывать другое поведение, чем debug —
  проверять на release-подобной сборке критичные сериализации, если дифф их касается.
- **Доступность.** Семантика (`Semantics`, `contentDescription`-аналоги), размер нажимаемой зоны,
  масштаб шрифта.
