# bZ3X · веб‑терминал + команды (GitHub Pages)

Страницы:

- **`index.html`** — **веб‑терминал (TUI)**: моноширинный лог‑экран, нижний prompt
  со слэш‑командами (`/connect`, `/ble`, `/run`, `/key …`, `/vin`, `/dtc`, `/bus`),
  статус‑строка. Сам открывает адаптер из браузера (Web Serial для USB/RFCOMM
  и Web Bluetooth для BLE), шлёт всю последовательность с проверками, лог TX/RX,
  авто‑подстановка seed→key и отправка `2702<KEY>`. TesterPresent‑keepalive держит
  сессию; при ошибке протокол восстанавливается. Останавливается при любой ошибке.
- **`terminal-classic.html`** — прежний веб‑терминал с кнопками (тот же обмен,
  те же фиксы: keepalive, дренаж RX, восстановление протокола).
- **`card.html`** — шпаргалка: команды для ELM327 / vLinker MC+ и офлайн‑генератор
  ключа Seed→Key (AES‑128 из `bz3x-menu.exe`). Всё считается в браузере, без сети.

Документация (Markdown):

- **[BZ3X-инструкция-терминал.md](BZ3X-инструкция-терминал.md)** — пошаговое
  открытие инженерного меню вручную (Android‑терминал + vLinker MC+).
- **[BZ3X-STN-команды-MC+.md](BZ3X-STN-команды-MC+.md)** — тот же обмен в «родном»
  для MC+ STN‑стиле (`ST…` вместо ELM‑`AT…`, MS‑CAN `STP53`).
- **[BZ3X-команды-MC+.md](BZ3X-команды-MC+.md)** — короткая шпаргалка команд.
- **[BZ3X-анализ-прошивок-F1-F4.md](BZ3X-анализ-прошивок-F1-F4.md)** — разбор
  прошивок F1–F4 (ключ AES, версии MCU, подписи, структура OTA).

## Веб‑терминал (`index.html`)

- **Web Serial** — Chrome/Edge на компьютере (USB‑адаптеры) и **Chrome for Android
  117+** (Bluetooth RFCOMM/SPP, т.е. vLinker MC+ по классическому BT). Нужен HTTPS
  или `localhost`; на Android — заранее спарить адаптер.
- **Web Bluetooth** — BLE‑режим адаптера. UUID сервиса у разных моделей свой; если
  авто‑поиск не находит, есть поле для ручного UUID и кнопка «Показать сервисы
  устройства».
- Авто‑baud (38400/115200/9600/57600), сырой RX (`/raw on`), ручная отправка
  любой команды, подтверждение риска перед последовательностью (`/run yes`).
- После `STP53` терминал читает `STPBRR` и печатает реальный битрейт шины —
  видно сразу, 125k там или 500k.

## Публикация на GitHub Pages

1. Инициализировать репозиторий и залить файлы:
   ```bash
   cd bz3x
   git init -b main
   git add -A
   git commit -m "bZ3X commands + key generator + web terminal"
   gh repo create bz3x --public --source=. --push
   ```
   (без `gh`: создать репозиторий на github.com и `git remote add origin … && git push -u origin main`)

   Обновление уже опубликованной версии:
   ```bash
   git add -A && git commit -m "обновление" && git push
   ```

2. Включить Pages:
   - **Settings → Pages → Build and deployment**
   - Source: **Deploy from a branch**
   - Branch: **main** / **/(root)** → **Save**

3. Через ~1 минуту страница будет доступна:
   `https://<username>.github.io/bz3x/`

Если репозиторий назвать `<username>.github.io`, адрес будет
`https://<username>.github.io/`.

## Оффлайн

Обе страницы самодостаточны: скачай `index.html` и `card.html` в одну папку и открой
в браузере телефона. Генератор ключа, буфер обмена и кнопки работают и без сети.
Веб‑терминал (`index.html`) требует разрешения на доступ к устройству и работает
в Chrome/Edge; Web Serial/Web Bluetooth доступны только в безопасном контексте
(HTTPS или `localhost`), поэтому «живое» подключение удобнее через GitHub Pages.
