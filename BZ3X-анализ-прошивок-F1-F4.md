# Toyota bZ3X (AY5T / IC2065) — разбор прошивок F1–F4

Результат статического разбора архивов `F1–F4` из `~/Toyota_Bz3x`
(гигабайты целиком не распаковывались — читались только нужные части:
оглавления вложенных `zip`, манифесты, подписи, версии).

## Что это за файлы

`F1.rar` и `F2.rar` — **дампы USB‑флешки**, которой обновляли ГУ. Внутри, кроме
папок Android‑хранилища (`Movies`, `Music`, `Pictures`, `DCIM`, `Download`,
`.thumbnails` …), лежат:

- папка с распакованным обновлением (`F1/IC2065/`, `F2/IC04015/`);
- «всё‑в‑одном» архив `…_R_ALL.zip`;
- **`svautoupdate.flag`** — флаг автоматического обновления с подписью.

`F3.zip` / `F4.zip` — «серверные» пакеты обновления (только содержимое).

Внутри каждого пакета — обновление по трём ECU:

```
manifest.txt   JSON: список ECU, target-версии, SHA-256 вложений
manifest.zip   подпись: cert.pem, cert.sf, sig.sig, manifest.txt
mcu.zip        MCU/радио: radio.bin + mcu_version.txt
soc.zip        Android A/B OTA: payload.bin + метаданные
vr.zip         голосовые ресурсы iFlytek
```

Структура «ALL.zip» (F1/F2) — это **streaming‑zip без центрального каталога**
(и `F2/…/GTMC_AY5T_AVNT_S202…_ALL.zip` вдобавок обрезан на 579 МБ — полный
`soc.zip` внутри не поместился). Поэтому `unzip` на них ругается; читать их
можно только по локальным заголовкам/смещениям.

## Сводная таблица версий

| | F2 (AY5T S202) | F3 (AY5T S214) | F4 (AY5T S222) | F1 (CS115 S.G) |
|---|---|---|---|---|
| Модель (manifest) | `IC04015` | `IC2065` | `IC2065` | `IC2065` |
| Сборка AVNT (soc) | `GTMC_AY5T_AVNT_S202_250707_05.13_R` | `GTMC_AY5T_AVNT_S214_251031_01.58_R` | `GTMC_AY5T_AVNT_S222_260227_14.39_R` | `GTMC_CS115_AVNT_S.G_250623_16.52_R` |
| MCU | `AY5T_IC2065_01_21.157_250705_R` | `AY5T_IC2065_01_21.173_251031_R` | `AY5T_IC2065_01_21.185_260131_R` | — (нет mcu.zip) |
| **CAN SoftwareVersion** | `8789CVN020  S.202` | `8789CVN020  S.214` | `8789CVN020  S.222` | — |
| CAN HardwareVersion | `87H9CVN020  H.000` | `87H9CVN020  H.000` | `87H9CVN020  H.000` | — |
| PartNumber | `8545003CVN0202` | `8545003CVN0203` | `8545003CVN0204` | — |
| MCU Checksum | `0x8507` | `0x6d79` | `0x4e25` | — |
| MCU radio.bin md5 | `82e5e0f9…d6e62a` | `fff4f641…006722e` | `882fe29f…414bf04` | — |
| VR (iFlytek) | `…` | `20250905_2` | `20260126_155401` | `20250613-CS115` |

Хронология MCU по датам: **S.202 (июл) → S.214 (окт) → S.222 (янв)**.

> exe `bz3x-menu.exe` требует ровно `8789CVN020  S.242`. Ни один из пакетов
> (S.202/S.214/S.222) ей не равен — то есть на момент разбора в машине была
> **более новая** версия, а гейт версии в exe — просто сверка строки, не защита.

## 🔑 Главное для проекта bZ3X Menu — AES‑ключ сидит в прошивке MCU

В `mcu.zip → radio.bin` (одинаково во **F2, F3, F4**) открытым текстом
(ASCII‑hex, рядом друг с другом) лежат **AES S‑box, RCON и ключ Seed2Key**:

| | F2 | F3 | F4 |
|---|---|---|---|
| RCON `01020408102040801B36` | 1534326 | 1554540 | 1568804 |
| **Ключ `C3D5CF2CA761E641A7312835B24B575E`** | 1534348 | 1554564 | 1568828 |
| AES S‑box `637C777BF26B6FC5…` | 1926116 | 1947444 | 1966788 |

Это **подтверждает провенанс ключа**, который используется в
`bz3x_menu_linux.py`, `index.html` и `card.html`
и проверен на 6 векторах seed→key. Ключ — **константа, одна и та же**
во всех версиях S.202 / S.214 / S.222.

`radio.bin` — ASCII‑hex дамп внутренней flash MCU с читаемыми строками
(`USER:user_on_normal_entry`, `Boot err code : sBoot_CMU_FC…`,
`Standby_pre_shutdown:->CAN_NM_…`, `hse_version err=0x…`, `spi receive 0x…`),
т.е. приложение MCU с логикой CAN‑сети и безопасности.

В Android‑части (`payload.bin`) ключ и строки не встречаются — разделы сжаты
пооперационно, внутри всё закрыто (проверено потоковым поиском по 4.5 ГБ).

## Головное устройство (SoC)

`soc.zip` — штатный Android A/B OTA (`payload.bin`), одинаковый по платформе:

- `post-build = qti/msmnile_gvmq/msmnile_gvmq:11/RQ3A.210805.001.A1/…`
- **Android 11**, устройство `msmnile_gvmq` → Qualcomm **SA8155**.
- Есть отдельный раздел **`system_qnx`** — часть системы крутится на QNX.

Разделов OTA — **27** (одинаковый набор у CS115 и AY5T), см.
`soc_payload/partitions_F4.txt` и `F1/partitions_CS115.txt`:

```
system_qnx, ifs2, bluetooth, dsp, modem, app, boot, dtbo, vbmeta,
vehicledefcfg, xbl, xbl_config, xbl_config_recovery, aop, tz, hyp, abl,
keymaster, cmnlib, cmnlib64, devcfg, qupfw, uefisecapp,
system, vendor, system_ext, product
```

## Подписи и защита обновления

- `manifest.txt` — JSON с версиями и SHA‑256 вложения.
- `cert.sf` — контрольная сумма `manifest.txt` (**SHA‑256**); сверено для всех
  пакетов — **совпадает**.
- `cert.pem` / `sig.sig` — подпись **SM2-with-SM3** (китайская нац. криптография,
  GAC R&D CENTER):
  - Issuer: `C=CN, O=GAC R&D CENTER, CN=GAC SM Engineer User CA`
  - Subject: `… Vehicle Cyber Security Sect. SM Engineer, CN=1429-c2:c9:c5:14:62:63`
  - ключ: SM2 (`id-ecPublicKey`, OID `1.2.156.10197.1.301`)
  - F1/F2: действителен 2025‑02‑15 … 2026‑02‑15
  - F3/F4: пере‑подписан 2025‑10‑29 … 2026‑10‑29 (тот же Subject)
- **`svautoupdate.flag`** (`{number, delayTime, sign}`) — подпись **сырым
  RSA‑4096** (512 байт, не DER): F1 и F2 имеют разные подписи. Это, похоже,
  авторизация автообновления («ставить сразу, delayTime=-1»).

## Данные в этой папке

```
analysis/
 ├─ F1/  manifest.txt, manifest_CS115.txt, cert.pem, cert.sf, cert_CS115.sf,
 │       sig.sig, svautoupdate.flag, soc_metadata_CS115.txt, partitions_CS115.txt
 ├─ F2/  manifest.txt, cert.pem, cert.sf, sig.sig, svautoupdate.flag,
 │       mcu_version.txt, radio.bin.md5
 ├─ F3/  manifest.txt, mcu_version.txt, radio.bin.md5
 ├─ F4/  manifest.txt, mcu_version.txt, radio.bin.md5,
 │       cert.pem, cert.sf, sig.sig, sig.der
 └─ soc_payload/  partitions_F4.txt, payload_properties.txt, metadata.txt, otacert.pem
```

## Ограничения / что не делали

- Разделы внутри `payload.bin` пооперационно сжаты — для поиска внутри нужен
  `payload-dumper` + распаковка образов (в Android‑части ключа нет).
- Проверка SM2‑подписи `openssl` из коробки не проходит (нужен SM2‑контекст);
  алгоритм и сертификат определены однозначно.
- `F2/…/…_ALL.zip` обрезан, `F1/F2` — дампы флешки, а не официальные архивы.
