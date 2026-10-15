# bZ3X — ADB-команды (по мотивам bz3x-tool 1.2.4)

Шпаргалка ADB-операций, которые выполняет `bz3x-tool` после включения **USB ADB** на
головном устройстве (ГУ) Toyota bZ3X. Пригодится, чтобы делать то же самое вручную.

> ⚠️ **Предусловие.** ADB на ГУ включается по UDS (рутина `31 01 AE65 01` после
> `10 03 → 27 01 → 27 02 <key>`). Этот документ — про шаги **после** того, как ADB уже доступен.
> Машина в «P», питание ГУ включено. Всё ниже пишет в систему ГУ — делай осознанно.

---

## 0. Подключение и проверка

```bash
# найти устройство (USB или по сети)
adb devices -l
adb wait-for-device

# по сети (если ГУ отдаёт ADB по TCP, напр. через adb tcpip/ENET)
adb connect 192.168.x.x:5555

# базовая информация
adb shell getprop ro.build.version.sdk      # уровень Android (API)
adb shell getprop ro.product.device
adb shell getprop ro.product.model
adb shell getprop persist.sys.locale         # текущая локаль
adb shell getprop persist.sys.timezone       # текущий часовой пояс

# что уже установлено нештатного (сторонние пакеты)
adb shell pm list packages -3
```

---

## 1. Русификация — смена локали на `ru-RU`

Штатно сменить системную локаль без root нельзя (`setprop persist.sys.locale` не сработает).
`bz3x-tool` обходит это **вшитым helper-jar**, который запускается через `app_process` и
дёргает `updatePersistentConfiguration(LocaleList)`.

**Как делает тул (точная схема):**

```bash
# 1) залить helper-jar на устройство
adb push bz3x-locale.jar /data/local/tmp/bz3x-locale.jar

# 2) применить локаль через app_process (без root)
adb shell "CLASSPATH=/data/local/tmp/bz3x-locale.jar app_process / Bz3xVisitHelper locale ru-RU --apply"
#   варианты локали:
#     ru-RU          — только русский
#     ru-RU,en-US    — русский + английский (fallback)
#     en-US          — вернуть только английский

# 3) проверить и перезагрузиться
adb shell getprop persist.sys.locale
adb reboot
```

> `Bz3xVisitHelper` — проприетарный класс из jar самого тула. Если своего jar нет, рабочие
> альтернативы для смены локали без root — утилиты вроде **ADB Change Language** (ставят
> временную IME-службу с правом `CHANGE_CONFIGURATION`). Через чистый `adb shell` одной
> командой это не делается — нужен такой helper.

---

## 2. Часовой пояс

```bash
# прочитать текущий
adb shell getprop persist.sys.timezone

# попытка задать напрямую (сработает только с root / на части ГУ)
adb shell setprop persist.sys.timezone "Europe/Moscow"

# без root — через системный сервис alarm (надёжнее):
adb shell service call alarm 3 s16 "Europe/Moscow"

adb reboot
```

Поддерживаемые тулом зоны (как в меню): `Europe/Kaliningrad` (UTC+2), **`Europe/Moscow` (UTC+3)**,
`Europe/Samara` (UTC+4), `Asia/Yekaterinburg` (UTC+5), `Asia/Omsk` (UTC+6),
`Asia/Novosibirsk`/`Asia/Krasnoyarsk` (UTC+7), `Asia/Irkutsk` (UTC+8), `Asia/Yakutsk` (UTC+9),
`Asia/Vladivostok` (UTC+10), `Asia/Magadan` (UTC+11), `Asia/Kamchatka` (UTC+12).

---

## 3. Установка APK

Тул пробует несколько путей (с фоллбэком, если ГУ блокирует `pm`/`cmd`).

**Способ A — проще всего:**

```bash
adb install -r app.apk
# или с заливкой во временную папку:
adb push app.apk /data/local/tmp/bz3x-install.apk
adb shell pm install -r /data/local/tmp/bz3x-install.apk
```

**Способ B — сессия (когда install -r капризничает):**

```bash
adb push app.apk /data/local/tmp/bz3x-install.apk
# создать сессию -> получить ID
adb shell pm install-create -r
# -> Success: created install session [12345]
adb shell pm install-write 12345 base.apk /data/local/tmp/bz3x-install.apk
adb shell pm install-commit 12345
# отмена, если нужно:
adb shell pm install-abandon 12345
```

**Способ C — `cmd package` (аналог B одной строкой):**

```bash
adb shell cmd package install -r /data/local/tmp/bz3x-install.apk
```

**Способ D — обход блокировки `pm`/`cmd` через `app_process`:**
тул при заблокированных `pm`/`cmd` заливает вшитый `installer.jar` и ставит APK им:

```bash
adb push installer.jar /data/local/tmp/bz3x-installer.jar
adb shell "CLASSPATH=/data/local/tmp/bz3x-installer.jar app_process / <installer-main> /data/local/tmp/bz3x-install.apk"
adb shell rm -f /data/local/tmp/bz3x-installer.jar
```

> `<installer-main>` — главный класс jar’а тула (проприетарный). Способ D нужен только там,
> где штатный установщик вырезан/заблокирован.

---

## 4. Право ставить приложения (REQUEST_INSTALL_PACKAGES)

Чтобы магазин/лаунчер (напр. RuStore) мог сам устанавливать APK:

```bash
# выдать конкретному пакету право «устанавливать неизвестные приложения»
adb shell appops set <package> REQUEST_INSTALL_PACKAGES allow
# альтернатива (на части прошивок):
adb shell pm grant <package> android.permission.REQUEST_INSTALL_PACKAGES

# пример для RuStore:
adb shell appops set ru.vk.store REQUEST_INSTALL_PACKAGES allow
```

---

## 5. Интернет приложениям (отключить штатный фаервол)

На bZ3X сторонним приложениям сеть режет системный фаервол **`com.gxa.firewall`**.
Тул его отключает:

```bash
# отключить фаервол GAC (возвращает приложениям интернет)
adb shell pm disable-user --user 0 com.gxa.firewall

# проверить состояние пакета
adb shell pm list packages -d | grep gxa          # disabled-пакеты
# включить обратно, если что:
adb shell pm enable com.gxa.firewall
```

> При желании так же можно отключать/включать любой нештатный или мешающий пакет:
> `adb shell pm disable-user --user 0 <package>` / `adb shell pm enable <package>`.

---

## 6. Полезные приложения (идут в комплекте тула)

| APK | Пакет | Зачем |
|---|---|---|
| RuStore | `ru.vk.store` | российский магазин приложений (ставит остальное) |
| Head Unit Reviced | `com.andrerinas.headunitrevived` | сервер Android Auto на ГУ |
| OpenSettings | — | ярлык на скрытые настройки Android |

```bash
# открыть системные настройки Android напрямую (без OpenSettings.apk)
adb shell am start -a android.settings.SETTINGS
# конкретные экраны:
adb shell am start -a android.settings.DATE_SETTINGS
adb shell am start -a android.settings.LOCALE_SETTINGS
adb shell am start -a android.settings.APPLICATION_DETAILS_SETTINGS -d package:<package>

# назначить приложение домашним (лаунчером), если поддерживается:
adb shell cmd package set-home-activity <package>/<activity>
```

---

## 7. Уборка

```bash
adb shell rm -f /data/local/tmp/bz3x-install.apk
adb shell rm -f /data/local/tmp/bz3x-install*.apk
adb shell rm -f /data/local/tmp/bz3x-locale.jar
adb shell rm -f /data/local/tmp/bz3x-installer.jar
```

---

## Шпаргалка одной колонкой

```bash
adb wait-for-device
adb shell getprop ro.build.version.sdk
adb shell getprop persist.sys.locale
adb shell getprop persist.sys.timezone
adb shell pm list packages -3

# локаль (нужен helper-jar тула)
adb push bz3x-locale.jar /data/local/tmp/bz3x-locale.jar
adb shell "CLASSPATH=/data/local/tmp/bz3x-locale.jar app_process / Bz3xVisitHelper locale ru-RU,en-US --apply"

# часовой пояс
adb shell service call alarm 3 s16 "Europe/Moscow"

# установка APK
adb install -r app.apk

# право на установку (для RuStore)
adb shell appops set ru.vk.store REQUEST_INSTALL_PACKAGES allow

# интернет приложениям
adb shell pm disable-user --user 0 com.gxa.firewall

adb reboot
```

---

**Примечания**

- Команды с `app_process` и вшитыми `*.jar` — проприетарная часть `bz3x-tool`; без этих jar
  смена локали/обход блокировки `pm` ровно так не повторяется (для локали есть сторонние
  helper-утилиты).
- `setprop persist.*` и `pm disable-user` на части ГУ требуют активного ADB-доступа с нужными
  правами; если команда «молча» не применилась — проверь `getprop`/`pm list packages -d` до и после.
- Всё обратимо: локаль вернуть `en-US`, фаервол — `pm enable com.gxa.firewall`, приложения —
  удалить `adb uninstall <package>`.
