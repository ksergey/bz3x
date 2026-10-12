# BZ3X · последовательность STN‑команд для vLinker MC+ (ручной терминал)

Тот же обмен, что делает `bz3x-menu.exe`, но в «родном» для MC+ **STN**‑стиле
(`ST…`), а не только ELM‑`AT…`. Адаптер MC+ понимает оба набора; здесь заменены
только те ELM‑команды, что в STN помечены как **deprecated**, и добавлены
STN‑проверки.

---

## 0. Главное про шину (из‑за чего был `CAN ERROR`)

IHU bZ3X (адреса `72B`/`7AB`) сидит на **HS‑CAN, 500 кбит/с**:

| Что | Команда | Трансивер |
|---|---|---|
| **HS‑CAN ← нужно** | `STP33` (он же `ATTP6`) — ISO 15765, 11‑bit, 500k, DLC=8 | пины 6/14 |
| ❌ НЕ надо | `STP53` — **MS‑CAN**, ISO 15765, 11‑bit, **125k**, DLC=8 | пины 3/11 |
| ❌ НЕ надо | `STP63` — SW‑CAN/GMLAN, 33.3k | пин 1 |

Пресеты `STP` (OBDLink FRPM, Table «OBD Protocol ST Commands»):

```
HS-CAN : 31 ISO11898 11b 500k varDLC | 32 ISO11898 29b 500k varDLC
         33 ISO15765 11b 500k DLC=8   | 34 ISO15765 29b 500k DLC=8
         35/36 ISO15765 250k          | 41/42 J1939
MS-CAN : 51/52 125k varDLC | 53 ISO15765 11b 125k DLC=8 | 54 29b 125k
SW-CAN : 61/62 33.3k varDLC | 63 ISO15765 11b 33.3k DLC=8 | 64 29b 33.3k
```

`STP` не открывает канал сам — канал открывается первым OBD‑запросом
(или явно `STPO`). Сохраняется в NVM только `ATSP`; `STP` — вольтáйл.

---

## 1. Карта замен (exe AT → для MC+)

| exe (ELM‑AT) | Статус в STN | Замена |
|---|---|---|
| `ATTP6` | deprecated | **`STP33`** |
| `ATPC` | deprecated | **`STPC`** |
| `ATSTFF` | deprecated | **`STPTO1020`** (= 255×4 мс) |
| `ATH1 ATS0 ATE0 ATL0 ATR1 ATM0 ATAL ATV0 ATCAF1 ATCFC1 ATAT0` | supported | оставить как есть |
| `ATSH72B` | supported | оставить (`ATSH 72B`) |
| `ATCRA7AB` | supported | оставить (`ATCRA 7AB`) |
| `ATFCSH72B ATFCSD300014 ATFCSM1` | supported | оставить **или** заменить одной **`STCFCPA 72B, 7AB`** |

---

## 2. Префлайт (проверка, что адаптер на нужной шине)

По одной команде, CR в конце, ждём ответ:

```
ATZ            → ...ELM327 v2.2
ATI            → ELM327 v2.2
STP33          → OK          (если `?` — используй ATSP6 как fallback)
STPR           → 33
STPRS          → ISO 15765, 11-bit, 500kbps, DLC=8
STPBRR         → 500000
```

Если `STPRS`/`STPBRR` показывают 125000 или MS/SW — ты не на той шине.

---

## 3. Инициализация — 19 команд (порядок как в exe)

```
ATE0
ATL0
ATH1
ATS0
ATR1
ATM0
STPC              # было ATPC
STP33             # было ATTP6   (HS-CAN 500k)
ATAL
ATV0
ATSH 72B
ATCRA 7AB
ATFCSH 72B
ATFCSD 30 00 14   # было ATFCSD300014
ATFCSM 1
ATCAF 1
ATCFC 1
ATAT 0
STPTO 1020        # было ATSTFF (1020 мс)
```

Опционально, для явности: `STPBR 500000` после `STP33` (для пресета 33 не
обязательно — там уже 500k).

**STN‑нативная замена блока flow‑control** (вместо `ATFCSH/ATFCSD/ATFCSM`):

```
STCFCPA 72B, 7AB  # пара: запрос 72B → ответ 7AB
```
(`STCFCPA` требует normal‑addressing; это дефолт, `STCAF 0`.)

---

## 4. Обмен (UDS)

Ответы при `ATH1` начинаются с `7AB`, multi‑frame ISO‑TP (`7AB10 14 …`, `7AB21 …`).

```
ATI              → ELM327 v2.2
22F190           → 62F190 + VIN (17 ASCII)
22F189           → 62F189 + "8789CVN020  S.242"   ⚠ версия должна совпасть
STPC             → OK          (было ATPC)
1003             → 5003
STPC             → OK          (было ATPC)
2701             → 6701 + SSSSSSSS   ← seed (4 байта)
   ← здесь считаем ключ (bz3x_card.html / bz3x_key.html): seed → KEY
2702<KEY>        → 6702        (ключ принят)
31012B00         → 71012B0000  (меню открыто)
1001             → 5001
22F186           → 62F186 …
ATZ              → баннер, OK  (сброс, выход)
```

Пример: `6701 12345678` → seed `12345678` → ключ `45E15E83` → отправить
`270245E15E83` → ждать `6702`.

---

## 5. Когда СТОП

Немедленно прекращать при любом из:

```
?      ERROR      NO DATA      UNABLE TO CONNECT
CAN ERROR      BUS ERROR      BUFFER FULL      BUS BUSY
7F xx xx   (любой негативный UDS-ответ)
```

И **не отправлять ключ**, если версия ≠ `8789CVN020  S.242`.

---

## 6. Диагностика

| Симптом | Причина / что делать |
|---|---|
| `CAN ERROR` | не та шина/пины/скорость. Проверь `STPR`→33, `STPRS`, `STPBRR`→500000. Убери `STP53`/`STPBR`. |
| `CAN ERROR` сразу | физически нет живой шины на этих пинах (напр. MS‑CAN 3/11) → нет ACK. |
| `NO DATA` | шина верная, но ECU молчит на этом адресе (зажигание/питание IHU, `ATSH`/`ATCRA`). |
| `?` на `STP33` | пресет не поддержан → fallback `ATSP6`. |
| `BUS BUSY` | линия «залипла», проблема проводки/питания. |
| `FC RX TIMEOUT` | фильтр режет FC‑кадр → добавь `STCFCPA 72B, 7AB` / `STFFCA`. |
| Всё ОК, но пусто | мультимедиа выключена / не P / другой разъём. |

---

## 7. Завершение / сброс

```
STPC      # закрыть протокол
ATZ       # полный ресет адаптера (стирает временные настройки)
```
