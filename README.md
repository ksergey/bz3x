# bZ3X · команды и ключ (GitHub Pages)

Одностраничный справочник: команды для ELM327 / vLinker MC+ и офлайн‑генератор
ключа Seed→Key (AES‑128 из `bz3x-menu.exe`). Всё считается в браузере, без сети.

## Публикация на GitHub Pages

1. Создать репозиторий и залить файлы:
   ```bash
   cd bz3x-pages
   git init -b main
   git add index.html README.md
   git commit -m "bZ3X commands + key generator"
   gh repo create bz3x-pages --public --source=. --push
   ```
   (без `gh`: создать репозиторий на github.com и `git remote add origin … && git push -u origin main`)

2. Включить Pages:
   - **Settings → Pages → Build and deployment**
   - Source: **Deploy from a branch**
   - Branch: **main** / **/(root)** → **Save**

3. Через ~1 минуту страница будет доступна:
   `https://<username>.github.io/bz3x-pages/`

Если репозиторий назвать `<username>.github.io`, адрес будет
`https://<username>.github.io/`.

## Оффлайн

Страница самодостаточна: скачай `index.html` и открой в браузере телефона
(`file:///sdcard/Download/index.html`). Буфер обмена и кнопки работают и без сети.
