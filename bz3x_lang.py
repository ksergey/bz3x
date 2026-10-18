#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bz3x_lang.py — переключение языка Toyota bZ3X по UDS/DoIP (ISO 13400).

Работает поверх doip.py (из того же каталога): UDS-сессия + SecurityAccess
+ чтение/запись DID в головном устройстве (AVNT).

DID (target 0x0E80, выявлено разбором UDS-потока HMI):
  0x0110 — язык главного дисплея (Android HMI). Значение: 0=китайский, 1=английский.
  0x0101 — язык малого дисплея (QNX-кластер). Длинная запись (~0x2C+ байт),
           язык = бит 0x02 одного из байтов записи (по умолчанию offset 0x29
           от начала данных — уточняется ключом --offset).

Полный реестр языков Android-HMI (styleId из SYSettingHmi, классы Language$Xxx):
  0=Chinese 1=English 2=Arabic 3=Russian 4=ChineseHK 5=German 6=French 7=Italian
  8=Spanish 9=Holland 10=Norway 11=Sweden 12=Portugal 13=Vietnam 14=Thai
  15=Indonesia 16=Malay 17=Latin 18=Brazil 19=Unknown
  (через DID 0x0110 переключаются только 0/1; остальные styleId HMI применяет
   штатно через CarSettingService -> someIP ClusterLanguage, минуя этот DID.)

Подкоманды:
  read                       прочитать оба DID и объяснить значения (read-only)
  en | cn                    главный дисплей: 0x01 / 0x00 в DID 0x0110 (ЗАПИСЬ)
  set N                      главный дисплей: записать произвольный байт N (ЗАПИСЬ)
  cluster_on | cluster_off   кластер: поставить/снять бит 0x02 (ЗАПИСЬ 1 байта)
  raw  HEX                   произвольный UDS-запрос после unlock (напр. 220101)

Все команды записи сначала ЧИТАЮТ текущее значение и печатают его — это откат.

Примеры:
  adb forward tcp:13400 tcp:13400 && ./bz3x_lang.py read
  ./bz3x_lang.py --host 10.1.0.79 en
  ./bz3x_lang.py cluster_on --offset 0x2A
  ./bz3x_lang.py raw 220101

ВНИМАНИЕ: зажигание в ACC/ON, автомобиль в «P», другие диагностики закрыты.
read — безопасна; остальные отправляют SecurityAccess и запись DID в ГУ.
"""
import argparse
import socket
import struct
import sys

from doip import Doip, seed2key

DID_HMI = 0x0110        # язык главного дисплея: 0=zh, 1=en
DID_CLUST = 0x0101      # язык кластера: длинная запись, бит 0x02 = английский
LANG_NAMES = {0: "Chinese", 1: "English", 2: "Arabic", 3: "Russian", 4: "ChineseHK",
              5: "German", 6: "French", 7: "Italian", 8: "Spanish", 9: "Holland",
              10: "Norway", 11: "Sweden", 12: "Portugal", 13: "Vietnam", 14: "Thai",
              15: "Indonesia", 16: "Malay", 17: "Latin", 18: "Brazil", 19: "Unknown"}


def _did_hex(did):
    """DID на проводе little-endian: 0x0110 -> '1001', 0x0101 -> '0101'."""
    return struct.pack("<H", did).hex().upper()


def _read(d, did):
    """22 <didLE> -> bytes('62 <didLE> <данные...>')"""
    r = d.uds("22" + _did_hex(did), expect="62")
    return bytes.fromhex(r)


def _write_byte(d, did, val):
    """2E <didLE> <1 байт> -> bytes('6E <didLE>')"""
    r = d.uds("2E" + _did_hex(did) + "%02X" % val, expect="6E")
    return bytes.fromhex(r)


def unlock(d, session=0x02, level=0x01, verbose=True):
    """10 <session>; 27 <level>; 27 <level> <key>.

    seed2key из doip.py: plaintext = seed(перевёрнутый?) + level-байт x12,
    AES-128-ECB фиксированным ключом — уровень 0x01 зашит в реализации.
    """
    d.uds("10%02X" % session, expect="50")
    r = d.uds("27%02X" % level, expect="67")
    seed = r[4:12]
    key = seed2key(seed)
    d.uds("27%02X%s" % (level, key), expect="67")
    if verbose:
        print("unlock: session=0x%02X level=0x%02X seed=%s key=%s"
              % (session, level, seed, key))


def show_cluster(resp, offset):
    """Печать записи DID 0x0101 с указанием байта-языка."""
    body = resp[3:]  # 62 + DID(2) -> данные
    print("  запись (%d байт данных): %s" % (len(body), body.hex()))
    idx = 3 + offset
    if len(resp) > idx:
        b = resp[idx]
        print("  байт[0x%02X]=0x%02X -> %s" % (idx, b,
              "английский (бит 0x02 установлен)" if b & 0x02
              else "китайский (бит 0x02 снят)"))
    else:
        print("  запись короче выбранного --offset (0x%02X): данных только %d байт"
              % (idx, len(body)))


def cmd_read(d, args):
    h = _read(d, DID_HMI)
    v = h[3]
    print("главный  DID 0x%04X: %s -> 0x%02X = %s"
          % (DID_HMI, h.hex(), v, LANG_NAMES.get(v, "?")))
    c = _read(d, DID_CLUST)
    print("кластер  DID 0x%04X:" % DID_CLUST)
    show_cluster(c, args.offset)


def cmd_hmi(d, args, val):
    old = _read(d, DID_HMI)[3]
    if old == val:
        print("главный: уже %d (%s)" % (val, LANG_NAMES.get(val, "?")))
        return
    print("главный: 0x%02X -> 0x%02X; откат: ./bz3x_lang.py set %d"
          % (old, val, old))
    _write_byte(d, DID_HMI, val)
    new = _read(d, DID_HMI)[3]
    ok = "OK" if new == val else "НЕ изменился — смотри NRC выше"
    print("главный: перечитано 0x%02X (%s)" % (new, ok))


def cmd_set(d, args):
    _write_byte(d, DID_HMI, args.n)
    print("главный: перечитано", _read(d, DID_HMI).hex())


def cmd_cluster(d, args, want_bit):
    c = _read(d, DID_CLUST)
    idx = 3 + args.offset
    if len(c) <= idx:
        raise SystemExit("запись коротка (%d байт данных) — подбери --offset "
                         "0..%d" % (len(c) - 3, len(c) - 4))
    old = c[idx]
    new = (old | 0x02) if want_bit else (old & 0xFD)
    if old == new:
        print("кластер: байт[0x%02X]=0x%02X — уже %s"
              % (idx, old, "EN" if want_bit else "CN"))
        return
    print("кластер: байт[0x%02X] 0x%02X -> 0x%02X; откат: ./bz3x_lang.py raw 2E0101%02X"
          % (idx, old, new, old))
    d.uds("2E" + _did_hex(DID_CLUST) + "%02X" % new, expect="6E")
    c2 = _read(d, DID_CLUST)
    ok = "OK" if c2[idx] == new else "НЕ изменился — смотри NRC выше"
    print("кластер: перечитано, байт[0x%02X]=0x%02X (%s)" % (idx, c2[idx], ok))
    show_cluster(c2, args.offset)


def cmd_raw(d, args):
    r = d.uds(args.hex, expect=None)
    print("ответ:", r)


def main():
    ap = argparse.ArgumentParser(
        description="переключение языка Toyota bZ3X по UDS/DoIP")
    ap.add_argument("--host", default="127.0.0.1",
                    help="IP AVNT (10.1.0.79 напрямую, 127.0.0.1 через adb forward)")
    ap.add_argument("--port", type=int, default=13400)
    ap.add_argument("--source", type=lambda x: int(x, 0), default=0x0722,
                    help="адрес тестера (по умолчанию 0x0722, как в HMI)")
    ap.add_argument("--target", type=lambda x: int(x, 0), default=0x0E80,
                    help="адрес AVNT (0x0E80)")
    ap.add_argument("--version", type=lambda x: int(x, 0), default=0x02,
                    help="версия заголовка DoIP")
    ap.add_argument("--timeout", type=float, default=5.0)
    ap.add_argument("--offset", type=lambda x: int(x, 0), default=0x29,
                    help="индекс байта-языка в ответе DID 0x0101 (от начала UDS-ответа)")
    ap.add_argument("-q", "--quiet", action="store_true",
                    help="не печатать TX/RX-дамп")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("read", help="прочитать оба DID (read-only)")
    sub.add_parser("en", help="главный дисплей -> английский (DID 0x0110 = 0x01)")
    sub.add_parser("cn", help="главный дисплей -> китайский (DID 0x0110 = 0x00)")
    p_set = sub.add_parser("set", help="главный: записать произвольный байт")
    p_set.add_argument("n", type=lambda x: int(x, 0))
    sub.add_parser("cluster_on", help="кластер -> английский (поставить бит 0x02)")
    sub.add_parser("cluster_off", help="кластер -> китайский (снять бит 0x02)")
    p_raw = sub.add_parser("raw", help="произвольный UDS-запрос после unlock")
    p_raw.add_argument("hex", help="напр. 220101")
    args = ap.parse_args()

    try:
        with Doip(args.host, args.port, args.source, args.target,
                  args.version, args.timeout, verbose=not args.quiet) as d:
            unlock(d, verbose=not args.quiet)
            if args.cmd == "read":
                cmd_read(d, args)
            elif args.cmd == "en":
                cmd_hmi(d, args, 1)
            elif args.cmd == "cn":
                cmd_hmi(d, args, 0)
            elif args.cmd == "set":
                cmd_set(d, args)
            elif args.cmd == "cluster_on":
                cmd_cluster(d, args, True)
            elif args.cmd == "cluster_off":
                cmd_cluster(d, args, False)
            elif args.cmd == "raw":
                cmd_raw(d, args)
    except (socket.error, OSError, ValueError, RuntimeError) as e:
        print("ОШИБКА:", e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
