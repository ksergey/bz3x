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

## 0a. ADB по WiFi (без USB)

`adbd` на ГУ умеет слушать TCP/IP. **Но сначала нужен один доверенный заход по USB/USB-ADB** —
по воздуху включить сетевой режим без уже работающего ADB нельзя.

```bash
# 1) по USB (USB-ADB уже включён рутиной 31 01 AE65 01), авторизовать ключ
adb devices                       # подтверди RSA-ключ на экране ГУ, если спросит

# 2) перевести adbd в TCP на порт 5555
adb tcpip 5555

# 3) узнать IP головного устройства в той же WiFi-сети
adb shell ip -f inet addr show wlan0     # или Настройки → WiFi

# 4) подключиться по сети (USB можно отключить)
adb connect 192.168.x.x:5555
adb devices
```

- Комп/телефон и ГУ должны быть **в одной сети** (ГУ в твою точку доступа, либо ты в хотспот ГУ).
- `adb tcpip` держится **до перезагрузки** ГУ; после ребута повторить.
- Вернуть обратно на USB: `adb usb`.

**Автозапуск при каждом старте** (без USB):
```bash
adb shell setprop persist.adb.tcp.port 5555
adb reboot
# проверка:
adb shell getprop persist.adb.tcp.port
```
⚠️ `persist.*` из shell без root часто **не применяется** (как и `persist.sys.locale`). Если
`getprop` вернул пусто — нужен root/helper; тогда остаётся вариант `adb tcpip 5555` после каждого ребута.

**Android 11+ (штатная «Беспроводная отладка» с пин-кодом):**
```bash
adb pair 192.168.x.x:AAAA         # порт и код — с экрана «Беспроводная отладка»
adb connect 192.168.x.x:BBBB
```
Нужен доступ к Developer Options (открыть можно через `OpenSettings.apk`). Классический
`adb tcpip 5555` проще и работает на любой версии.

---

## 0b. Подключение с телефона

Да, можно — **с Android-телефона по WiFi** (iPhone adb штатно не умеет). ГУ уже должно быть
в режиме `adb tcpip 5555` (см. 0a), телефон и ГУ — в одной сети.

**Вариант A — Termux (полноценный adb):**
```bash
pkg update && pkg install android-tools
adb connect 192.168.x.x:5555
adb shell            # дальше любые команды из этого документа
```

**Вариант B — приложение** «Remote ADB Shell» (или аналог): ввести `IP:5555`, подключиться,
получить shell. Удобно для разовых команд без Termux.

- Если при подключении на экране ГУ появится запрос RSA-ключа — **подтверди** (разрешить этому
  устройству). Если adbd на ГУ в «небезопасном» режиме (`ro.adb.secure=0`) — подключится без запроса.
- Первичный `adb tcpip 5555` и авторизацию ключа проще один раз сделать **с компьютера**; дальше
  телефон подключается к `IP:5555` по сети сам.
- USB-OTG «телефон → ГУ» для первичного переключения обычно не годится: ГУ само USB-хост, а не
  устройство. Поэтому первый шаг — ПК по USB, а телефон уже по WiFi.

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
