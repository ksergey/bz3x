#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""doip.py — UDS поверх DoIP (ISO 13400) для головного устройства Toyota bZ3X.

Linux, только stdlib. Транспорт DoIP заменяет ELM327/CAN: CAN-шина не трогается.
Нужен IP-доступ к ГУ:
  - `adb forward tcp:13400 tcp:13400`  ->  --host 127.0.0.1 (по умолчанию);
  - DoIP-адаптер в OBD / бортовая сеть ->  --host 10.1.0.79 (см. README.md).

Подкоманды (БЕЗОПАСНО = read-only, ЗАПИСЬ = отправляет записи в ЭБУ):
  vin                          VIN (22 F190)                         БЕЗОПАСНО
  lang                         язык обоих дисплеев: DID 0x0110/0x0101  БЕЗОПАСНО
  en | cn                      главный дисплей -> EN / CN             ЗАПИСЬ
  set N                        главный дисплей, произвольный байт     ЗАПИСЬ
  cluster_on | cluster_off     малый дисплей -> EN / CN               ЗАПИСЬ
  uds  HEX [HEX ...]           произвольные UDS-запросы (после unlock)
  menu                         открыть инженерное меню                ЗАПИСЬ
  adb                          включить ADB                           ЗАПИСЬ
  discover                     UDP-broadcast поиск DoIP-узлов         БЕЗОПАСНО

Примеры:
  adb forward tcp:13400 tcp:13400 && ./doip.py vin
  ./doip.py --host 10.1.0.79 lang
  ./doip.py en && ./doip.py cluster_on
  ./doip.py menu
  ./doip.py uds 22F189 22F186

ВНИМАНИЕ: en/cn/set/cluster_*/menu/adb — SecurityAccess и запись в ГУ. Машина
в «P», питание ГУ включено, другие программы диагностики закрыты, на ходу — нет.
"""
import argparse
import socket
import struct
import sys
import time

# ------------------------------- AES-128 (encrypt-only, pure python) ----------
SBOX = [
    0x63,0x7c,0x77,0x7b,0xf2,0x6b,0x6f,0xc5,0x30,0x01,0x67,0x2b,0xfe,0xd7,0xab,0x76,
    0xca,0x82,0xc9,0x7d,0xfa,0x59,0x47,0xf0,0xad,0xd4,0xa2,0xaf,0x9c,0xa4,0x72,0xc0,
    0xb7,0xfd,0x93,0x26,0x36,0x3f,0xf7,0xcc,0x34,0xa5,0xe5,0xf1,0x71,0xd8,0x31,0x15,
    0x04,0xc7,0x23,0xc3,0x18,0x96,0x05,0x9a,0x07,0x12,0x80,0xe2,0xeb,0x27,0xb2,0x75,
    0x09,0x83,0x2c,0x1a,0x1b,0x6e,0x5a,0xa0,0x52,0x3b,0xd6,0xb3,0x29,0xe3,0x2f,0x84,
    0x53,0xd1,0x00,0xed,0x20,0xfc,0xb1,0x5b,0x6a,0xcb,0xbe,0x39,0x4a,0x4c,0x58,0xcf,
    0xd0,0xef,0xaa,0xfb,0x43,0x4d,0x33,0x85,0x45,0xf9,0x02,0x7f,0x50,0x3c,0x9f,0xa8,
    0x51,0xa3,0x40,0x8f,0x92,0x9d,0x38,0xf5,0xbc,0xb6,0xda,0x21,0x10,0xff,0xf3,0xd2,
    0xcd,0x0c,0x13,0xec,0x5f,0x97,0x44,0x17,0xc4,0xa7,0x7e,0x3d,0x64,0x5d,0x19,0x73,
    0x60,0x81,0x4f,0xdc,0x22,0x2a,0x90,0x88,0x46,0xee,0xb8,0x14,0xde,0x5e,0x0b,0xdb,
    0xe0,0x32,0x3a,0x0a,0x49,0x06,0x24,0x5c,0xc2,0xd3,0xac,0x62,0x91,0x95,0xe4,0x79,
    0xe7,0xc8,0x37,0x6d,0x8d,0xd5,0x4e,0xa9,0x6c,0x56,0xf4,0xea,0x65,0x7a,0xae,0x08,
    0xba,0x78,0x25,0x2e,0x1c,0xa6,0xb4,0xc6,0xe8,0xdd,0x74,0x1f,0x4b,0xbd,0x8b,0x8a,
    0x70,0x3e,0xb5,0x66,0x48,0x03,0xf6,0x0e,0x61,0x35,0x57,0xb9,0x86,0xc1,0x1d,0x9e,
    0xe1,0xf8,0x98,0x11,0x69,0xd9,0x8e,0x94,0x9b,0x1e,0x87,0xe9,0xce,0x55,0x28,0xdf,
    0x8c,0xa1,0x89,0x0d,0xbf,0xe6,0x42,0x68,0x41,0x99,0x2d,0x0f,0xb0,0x54,0xbb,0x16,
]
RCON = [0x01,0x02,0x04,0x08,0x10,0x20,0x40,0x80,0x1B,0x36]

# Ключ SecurityAccess bZ3X (из libdesaysv_uds_server.so / MCU radio.bin)
AES_KEY = [0xc3,0xd5,0xcf,0x2c,0xa7,0x61,0xe6,0x41,0xa7,0x31,0x28,0x35,0xb2,0x4b,0x57,0x5e]


def _xtime(a):
    a <<= 1
    if a & 0x100:
        a ^= 0x11b
    return a & 0xff


def _expand_key(key):
    w = [[key[i*4], key[i*4+1], key[i*4+2], key[i*4+3]] for i in range(4)]
    for i in range(4, 44):
        t = list(w[i-1])
        if i % 4 == 0:
            t = [t[1], t[2], t[3], t[0]]
            t = [SBOX[t[0]], SBOX[t[1]], SBOX[t[2]], SBOX[t[3]]]
            t[0] ^= RCON[i//4 - 1]
        p = w[i-4]
        w.append([p[j] ^ t[j] for j in range(4)])
    return w


def _encrypt_block(key, block):
    w = _expand_key(key)
    st = [[block[r + 4*c] ^ w[c][r] for r in range(4)] for c in range(4)]
    for rnd in range(1, 11):
        for c in range(4):
            for r in range(4):
                st[c][r] = SBOX[st[c][r]]
        st = [[st[(c+r) % 4][r] for r in range(4)] for c in range(4)]  # ShiftRows
        if rnd != 10:
            mo = []
            for c in range(4):
                a0, a1, a2, a3 = st[c]
                mo.append([
                    _xtime(a0) ^ _xtime(a1) ^ a1 ^ a2 ^ a3,
                    a0 ^ _xtime(a1) ^ _xtime(a2) ^ a2 ^ a3,
                    a0 ^ a1 ^ _xtime(a2) ^ _xtime(a3) ^ a3,
                    _xtime(a0) ^ a0 ^ a1 ^ a2 ^ _xtime(a3),
                ])
            st = mo
        for c in range(4):
            for r in range(4):
                st[c][r] ^= w[rnd*4 + c][r]
    return [st[c][r] for c in range(4) for r in range(4)]


def seed2key(seed_hex):
    """4-байтовый seed (8 hex) -> 4-байтовый key (8 hex). AES-128, свёртка XOR."""
    s = "".join(ch for ch in seed_hex if ch in "0123456789abcdefABCDEF").upper()
    if len(s) != 8:
        raise ValueError("нужно 8 hex-символов (4 байта) seed, получено: %r" % seed_hex)
    seed = [int(s[i*2:i*2+2], 16) for i in range(4)]
    ct = _encrypt_block(AES_KEY, seed + [1]*12)
    k = [
        (ct[12] ^ ct[3]) ^ (ct[15] ^ ct[0]),
        (ct[13] ^ ct[2]) ^ (ct[14] ^ ct[1]),
        ct[14] ^ ct[1],
        ct[15] ^ ct[0],
    ]
    return "".join("%02X" % b for b in k)


# --------------------------------- DoIP ---------------------------------------
PT_VID_REQ   = 0x0001   # Vehicle Identification Request
PT_VID_RESP  = 0x0004   # Vehicle Announcement / ID Response
PT_RA_REQ    = 0x0005   # Routing Activation Request
PT_RA_RESP   = 0x0006   # Routing Activation Response
PT_ALIVE_REQ = 0x0007
PT_DIAG      = 0x8001   # Diagnostic Message
PT_DIAG_ACK  = 0x8002   # Diagnostic Message positive ACK
PT_DIAG_NACK = 0x8003   # Diagnostic Message negative ACK

RA_OK = 0x10            # routing activation: success

NRC = {  # ISO 14229 negative response codes (для 7F xx)
    0x10: "generalReject", 0x11: "serviceNotSupported", 0x12: "subFunctionNotSupported",
    0x13: "incorrectMessageLengthOrInvalidFormat", 0x22: "conditionsNotCorrect",
    0x24: "requestSequenceError", 0x31: "requestOutOfRange", 0x33: "securityAccessDenied",
    0x35: "invalidKey", 0x36: "exceedNumberOfAttempts", 0x37: "requiredTimeDelayNotExpired",
    0x78: "responsePending", 0x7E: "subFunctionNotSupportedInActiveSession",
    0x7F: "serviceNotSupportedInActiveSession",
}


class DoipError(Exception):
    pass


class Doip:
    def __init__(self, host, port=13400, source=0x0001, target=0x0DFF,
                 version=0x02, timeout=5.0, verbose=True):
        self.host, self.port = host, port
        self.source, self.target = source, target
        self.version = version
        self.timeout = timeout
        self.verbose = verbose
        self.sock = None

    # --- framing ---
    def _hdr(self, ptype, payload):
        return struct.pack(">BBHI", self.version, self.version ^ 0xFF,
                           ptype, len(payload)) + payload

    def _send(self, ptype, payload):
        if self.verbose:
            print("TX doip type=0x%04X %s" % (ptype, payload.hex()))
        self.sock.sendall(self._hdr(ptype, payload))

    def _recvn(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise DoipError("соединение закрыто (получено %d из %d байт)" % (len(buf), n))
            buf += chunk
        return buf

    def _recv(self):
        ver, nver, ptype, plen = struct.unpack(">BBHI", self._recvn(8))
        if ver ^ 0xFF != nver:
            raise DoipError("битый заголовок DoIP: ver=0x%02X ~ver=0x%02X" % (ver, nver))
        payload = self._recvn(plen) if plen else b""
        if self.verbose:
            print("RX doip type=0x%04X %s" % (ptype, payload.hex()))
        return ptype, payload

    # --- lifecycle ---
    def open(self):
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self.sock.settimeout(self.timeout)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        self.routing_activation()
        return self

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            finally:
                self.sock = None

    def __enter__(self):
        return self.open()

    def __exit__(self, *a):
        self.close()

    # --- protocol ---
    def routing_activation(self, act_type=0x00):
        body = struct.pack(">HB", self.source, act_type) + b"\x00\x00\x00\x00"
        self._send(PT_RA_REQ, body)
        ptype, data = self._recv()
        if ptype != PT_RA_RESP:
            raise DoipError("ожидался routing activation response (0x0006), получен 0x%04X" % ptype)
        code = data[4] if len(data) >= 5 else 0xFF
        if code != RA_OK:
            raise DoipError("routing activation отклонена, код 0x%02X" % code)
        if self.verbose:
            print("DoIP: routing activation OK (tester=0x%04X)" % self.source)

    def uds(self, req_hex, expect=None):
        """Отправить UDS-запрос (hex) и вернуть ответ (hex-строка без source/target)."""
        req = bytes.fromhex(req_hex.replace(" ", ""))
        body = struct.pack(">HH", self.source, self.target) + req
        self._send(PT_DIAG, body)
        t0 = time.time()
        while True:
            ptype, data = self._recv()
            if ptype == PT_DIAG_NACK:
                code = data[4] if len(data) >= 5 else 0xFF
                raise DoipError("diagnostic NACK 0x%02X" % code)
            if ptype == PT_DIAG_ACK:
                continue  # положительный ACK — ждём собственно ответ ЭБУ
            if ptype == PT_DIAG:
                resp = data[4:]  # после source(2)+target(2)
                # 7F SID NRC -> отрицательный ответ (0x78 = responsePending, ждём дальше)
                if len(resp) >= 3 and resp[0] == 0x7F:
                    nrc = resp[2]
                    if nrc == 0x78 and time.time() - t0 < self.timeout * 4:
                        continue
                    raise DoipError("UDS 7F %02X %02X (%s)" % (resp[1], nrc, NRC.get(nrc, "?")))
                r = resp.hex().upper()
                if expect and not r.startswith(expect.upper()):
                    raise DoipError("ожидался ответ %s, получен %s" % (expect.upper(), r or "пусто"))
                return r
            # прочие типы (alive check и т.п.) — пропускаем
            if time.time() - t0 > self.timeout:
                raise DoipError("таймаут ожидания ответа на %s" % req_hex)


def ascii_from_hex(hexstr, skip_bytes):
    """Декод ASCII из hex-ответа, пропустив первые skip_bytes байт (SID+DID)."""
    data = bytes.fromhex(hexstr)
    return data[skip_bytes:].decode("ascii", "replace").strip()


# ------------------------------- язык дисплеев --------------------------------
DID_HMI = 0x0110        # язык главного дисплея (Android HMI): 0=CN, 1=EN
DID_CLUST = 0x0101      # конфигурация кластера (QNX): бит 0x02 байта = EN

LANG_NAMES = {0: "Chinese", 1: "English", 2: "Arabic", 3: "Russian", 4: "ChineseHK",
              5: "German", 6: "French", 7: "Italian", 8: "Spanish", 9: "Holland",
              10: "Norway", 11: "Sweden", 12: "Portugal", 13: "Vietnam", 14: "Thai",
              15: "Indonesia", 16: "Malay", 17: "Latin", 18: "Brazil", 19: "Unknown"}

LANG_CMDS = {"lang", "en", "cn", "set", "cluster_on", "cluster_off"}


def _did_hex(did):
    """DID на проводе little-endian: 0x0110 -> '1001', 0x0101 -> '0101'."""
    return struct.pack("<H", did).hex().upper()


def _read_did(d, did):
    """22 <didLE> -> bytes('62 <didLE> <данные...>')"""
    return bytes.fromhex(d.uds("22" + _did_hex(did), expect="62"))


def _write_byte(d, did, val):
    """2E <didLE> <1 байт> -> bytes('6E <didLE>')"""
    return bytes.fromhex(d.uds("2E" + _did_hex(did) + "%02X" % val, expect="6E"))


def _unlock_lang(d):
    """Сессия 0x02 + SecurityAccess level 0x01 (как в специализированном скрипте)."""
    d.uds("1002", expect="5002")
    r = d.uds("2701", expect="6701")
    seed = r[4:12]
    key = seed2key(seed)
    d.uds("2701" + key, expect="6701")
    print("unlock: session=0x02 seed=%s key=%s" % (seed, key))


def show_cluster(resp, offset):
    body = resp[3:]  # 62 + DID(2) -> данные
    print("  запись (%d байт данных): %s" % (len(body), body.hex()))
    idx = 3 + offset
    if len(resp) > idx:
        b = resp[idx]
        print("  байт[0x%02X]=0x%02X -> %s" % (idx, b,
              "английский (бит 0x02 установлен)" if b & 0x02
              else "китайский (бит 0x02 снят)"))
    else:
        print("  запись короче --offset 0x%02X: данных только %d байт"
              % (idx, len(body)))


def cmd_lang(d, args):
    h = _read_did(d, DID_HMI)
    v = h[3]
    print("главный  DID 0x%04X: %s -> 0x%02X = %s"
          % (DID_HMI, h.hex(), v, LANG_NAMES.get(v, "?")))
    c = _read_did(d, DID_CLUST)
    print("кластер  DID 0x%04X:" % DID_CLUST)
    show_cluster(c, args.offset)


def cmd_hmi_set(d, args, val):
    old = _read_did(d, DID_HMI)[3]
    if old == val:
        print("главный: уже %d (%s)" % (val, LANG_NAMES.get(val, "?")))
        return
    print("главный: 0x%02X -> 0x%02X; откат: ./doip.py set %d" % (old, val, old))
    _write_byte(d, DID_HMI, val)
    new = _read_did(d, DID_HMI)[3]
    ok = "OK" if new == val else "НЕ изменился — смотри NRC выше"
    print("главный: перечитано 0x%02X (%s)" % (new, ok))


def cmd_set(d, args):
    _write_byte(d, DID_HMI, args.n)
    print("главный: перечитано", _read_did(d, DID_HMI).hex())


def cmd_cluster(d, args, want_bit):
    c = _read_did(d, DID_CLUST)
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
    print("кластер: байт[0x%02X] 0x%02X -> 0x%02X; откат: ./doip.py uds 2E0101%02X"
          % (idx, old, new, old))
    d.uds("2E" + _did_hex(DID_CLUST) + "%02X" % new, expect="6E")
    c2 = _read_did(d, DID_CLUST)
    ok = "OK" if c2[idx] == new else "НЕ изменился — смотри NRC выше"
    print("кластер: перечитано, байт[0x%02X]=0x%02X (%s)" % (idx, c2[idx], ok))
    show_cluster(c2, args.offset)


# ------------------------------- прочие команды -------------------------------
def cmd_vin(d, _args):
    r = d.uds("22F190", expect="62F190")
    print("VIN:", ascii_from_hex(r, 3))


def cmd_uds(d, args):
    for h in args.hex:
        try:
            r = d.uds(h)
            print("%s -> %s" % (h.upper(), r))
        except DoipError as e:
            print("%s -> ОШИБКА: %s" % (h.upper(), e))


def _unlock_sequence(d, routine_hex, label):
    print("10 03 — extended session")
    d.uds("1003", expect="5003")
    print("27 01 — запрос seed")
    r = d.uds("2701", expect="6701")
    seed = r[4:12]
    key = seed2key(seed)
    print("  seed=%s  key=%s" % (seed, key))
    print("27 02 — отправка ключа")
    d.uds("2702" + key, expect="6702")
    print("%s — %s" % (routine_hex, label))
    r = d.uds(routine_hex)
    print("  ответ:", r)
    print("1001 — default session")
    try:
        d.uds("1001", expect="5001")
    except DoipError:
        pass
    print("ГОТОВО:", label)


def cmd_menu(d, _args):
    _unlock_sequence(d, "31012B00", "открыть инженерное меню")


def cmd_adb(d, _args):
    _unlock_sequence(d, "3101AE6501", "включить ADB")


def cmd_discover(args):
    """UDP-broadcast Vehicle Identification Request (payload type 0x0001)."""
    msg = struct.pack(">BBHI", args.version, args.version ^ 0xFF, PT_VID_REQ, 0)
    s = socket.socket(socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    s.settimeout(args.timeout)
    s.sendto(msg, ("255.255.255.255", args.port))
    print("discover: отправлен Vehicle Identification Request на :%d, жду %.0f c..."
          % (args.port, args.timeout))
    found = 0
    try:
        while True:
            data, addr = s.recvfrom(1024)
            found += 1
            print("  узел %s  payload=%s" % (addr[0], data.hex()))
    except socket.timeout:
        pass
    finally:
        s.close()
    if not found:
        print("  узлов не найдено (возможно, ГУ доступно только через adb forward на 127.0.0.1)")


# --------------------------------- main ---------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description="UDS over DoIP (ISO 13400) для Toyota bZ3X")
    ap.add_argument("--host", default="127.0.0.1",
                    help="IP ГУ (127.0.0.1 — через adb forward, 10.1.0.79 — через адаптер/бортсеть)")
    ap.add_argument("--port", type=int, default=13400)
    ap.add_argument("--source", type=lambda x: int(x, 0), default=None,
                    help="logical address тестера (по умолч.: 0x0722 для языка, 0x0001 для остального)")
    ap.add_argument("--target", type=lambda x: int(x, 0), default=None,
                    help="logical address ГУ (по умолч.: 0x0E80 для языка, 0x0DFF для остального)")
    ap.add_argument("--version", type=lambda x: int(x, 0), default=0x02,
                    help="версия заголовка DoIP (0x02=2012, 0x03=2019)")
    ap.add_argument("--timeout", type=float, default=5.0)
    ap.add_argument("--offset", type=lambda x: int(x, 0), default=0x29,
                    help="индекс байта-языка в ответе DID 0x0101 (для cluster_*)")
    ap.add_argument("-q", "--quiet", action="store_true", help="не печатать TX/RX")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("vin", help="прочитать VIN (read-only)")
    sub.add_parser("lang", help="прочитать язык обоих дисплеев (read-only)")
    sub.add_parser("en", help="главный дисплей -> английский (ЗАПИСЬ)")
    sub.add_parser("cn", help="главный дисплей -> китайский (ЗАПИСЬ)")
    p_set = sub.add_parser("set", help="главный дисплей: записать произвольный байт (ЗАПИСЬ)")
    p_set.add_argument("n", type=lambda x: int(x, 0))
    sub.add_parser("cluster_on", help="малый дисплей -> английский (ЗАПИСЬ)")
    sub.add_parser("cluster_off", help="малый дисплей -> китайский (ЗАПИСЬ)")
    p_uds = sub.add_parser("uds", help="отправить произвольные UDS-запросы")
    p_uds.add_argument("hex", nargs="+", help="например 22F189 22F186")
    sub.add_parser("menu", help="открыть инженерное меню (ЗАПИСЬ)")
    sub.add_parser("adb", help="включить ADB (ЗАПИСЬ)")
    sub.add_parser("discover", help="UDP-broadcast поиск DoIP-узлов")
    args = ap.parse_args(argv)

    # auto source/target по группе команд (переопределяется --source/--target)
    if args.cmd in LANG_CMDS:
        args.source = args.source if args.source is not None else 0x0722
        args.target = args.target if args.target is not None else 0x0E80
    else:
        args.source = args.source if args.source is not None else 0x0001
        args.target = args.target if args.target is not None else 0x0DFF

    if args.cmd == "discover":
        cmd_discover(args)
        return 0

    try:
        with Doip(args.host, args.port, args.source, args.target,
                  args.version, args.timeout, verbose=not args.quiet) as d:
            if args.cmd == "vin":
                cmd_vin(d, args)
            elif args.cmd == "lang":
                _unlock_lang(d)
                cmd_lang(d, args)
            elif args.cmd in ("en", "cn"):
                _unlock_lang(d)
                cmd_hmi_set(d, args, 1 if args.cmd == "en" else 0)
            elif args.cmd == "set":
                _unlock_lang(d)
                cmd_set(d, args)
            elif args.cmd == "cluster_on":
                _unlock_lang(d)
                cmd_cluster(d, args, True)
            elif args.cmd == "cluster_off":
                _unlock_lang(d)
                cmd_cluster(d, args, False)
            elif args.cmd == "uds":
                cmd_uds(d, args)
            elif args.cmd == "menu":
                cmd_menu(d, args)
            elif args.cmd == "adb":
                cmd_adb(d, args)
    except (DoipError, OSError, ValueError) as e:
        print("ОШИБКА:", e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
