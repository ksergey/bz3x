"""Client preflight: adapter channel + read-only IHU VIN. No activation keys.

Восстановлено из BZ3X_Client_Check.exe (diagnostic.py 1.1.0) и доработано для Linux:
- порты /dev/ttyUSB*, /dev/ttyACM*, /dev/rfcomm*, /dev/serial/by-id/* (на Windows по-прежнему COMn);
- монопольное открытие порта и понятные ошибки при нехватке прав или занятом порте;
- инвентаризация устройств через /sys вместо PowerShell;
- консольный запуск: python3 diagnostic.py --help
Команды адаптеру и логика проверки не менялись.
"""
import argparse
import datetime
import errno
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import threading
import time
import zipfile

import serial
from serial.tools import list_ports

IS_WINDOWS = os.name == "nt"
if IS_WINDOWS:
    PORT_RE, PORT_FLAGS = r"COM[1-9][0-9]*", re.I
else:
    PORT_RE, PORT_FLAGS = (r"/dev/(?:tty(?:USB|ACM|S|AMA|XRUSB)[0-9]+|rfcomm[0-9]+"
                           r"|serial/by-(?:id|path)/[\w.:+@-]+)"), 0

VERSION = "1.1.0"
BAUDS = (38400, 115200, 57600, 9600, 19200, 230400, 500000, 1000000, 2000000)
ALLOWED = frozenset(("ATI", "STI", "ATRV", "ATRD", "STPR", "STPBRR", "STPRS", "ATE0", "ATL0", "ATS0", "ATH1",
                     "ATAL", "STP33", "STPBR500000", "ATSP6", "ATSH72B", "ATCRA7AB", "ATFCSH72B",
                     "ATFCSD300000", "ATFCSM1", "ATCFC1", "ATCAF1", "ATAT2", "ATST96",
                     "STCFCPC", "STCFCPA72B,7AB", "22F190"))


class CheckError(Exception):
    pass


class Cancelled(CheckError):
    pass


def ports():
    return [dict(device=p.device, description=p.description, vid=p.vid, pid=p.pid,
                 serial_number=p.serial_number, manufacturer=p.manufacturer)
            for p in sorted(list_ports.comports(), key=lambda x: x.device)]


def preferred_port(items):
    usb = [p for p in items if p.get("vid") is not None]
    if len(usb) == 1:
        return usb[0]["device"]
    return items[0]["device"] if len(items) == 1 else None


def parse(raw, command):
    if b">" not in raw:
        raise CheckError("Нет ответа с приглашением >. Возможны неверная скорость, питание или занятый порт.")
    body = raw.split(b">", 1)[0]
    if any(b not in (9, 10, 13) and not 32 <= b <= 126 for b in body):
        raise CheckError("Нечитаемый ответ адаптера; следующие команды не отправлены.")
    # строки ответа без пустых и без эха самой команды
    return [s.strip() for s in body.decode("ascii").splitlines()
            if s.strip() and "".join(s.upper().split()) != command.upper()]


def identify(lines):
    return lines[0] if len(lines) == 1 and re.fullmatch(
        r"(?:ELM327|STN\d{4}|OBDLink[ A-Za-z0-9+-]*)\s+v?\d[\w. -]*", lines[0], re.I) else None


def decode_vin(lines):
    """Strict 7AB ISO-TP, 62 F1 90 + 17 ASCII; not a general CAN decoder."""
    data = None
    result = None
    seq = 1
    for line in lines:
        value = "".join(line.upper().split()).strip(">")
        if not value.startswith("7AB"):
            continue
        raw = value[3:]
        if len(raw) % 2:  # с DLC-цифрой перед данными
            if raw[:1] not in "12345678" or len(raw[1:]) != int(raw[0], 16) * 2:
                raise CheckError("Неверная длина CAN-кадра.")
            raw = raw[1:]
        try:
            frame = bytes.fromhex(raw)
        except ValueError:
            raise CheckError("Некорректный CAN-кадр.") from None
        if not 1 <= len(frame) <= 8 or result is not None:
            raise CheckError("Некорректный или неоднозначный ответ VIN.")
        kind = frame[0] >> 4
        if kind == 0:  # Single Frame
            size = frame[0] & 0x0F
            payload = frame[1:1 + size]
            if data is None and size == 3 and len(payload) == 3 and payload[:2] == b"\x7f\x22":
                if payload[2] == 0x78:  # responsePending
                    continue
                raise CheckError(f"ГУ отклонило чтение VIN: NRC {payload[2]:02X}.")
            raise CheckError("Короткий ответ не является полным VIN.")
        elif kind == 1:  # First Frame, длина 0x014 = 3 + 17
            if data is not None or len(frame) != 8 or ((frame[0] & 0x0F) << 8 | frame[1]) != 20:
                raise CheckError("Неверное начало многокадрового VIN.")
            data = bytearray(frame[2:])
        elif kind == 2:  # Consecutive Frame
            if data is None or frame[0] & 0x0F != seq or len(frame) != 8:
                raise CheckError("Нарушена последовательность кадров VIN.")
            data.extend(frame[1:])
            seq = (seq + 1) & 0x0F
            if len(data) >= 20:
                result = bytes(data[:20])
        else:
            raise CheckError("Неожиданный тип CAN-кадра.")
    if result is None or not result.startswith(b"\x62\xf1\x90"):
        raise CheckError("Полный VIN от ГУ не получен. Проверьте питание ГУ и физический канал адаптера.")
    try:
        vin = result[3:].decode("ascii")
    except UnicodeDecodeError:
        raise CheckError("VIN содержит недопустимые символы.") from None
    if not re.fullmatch(r"[A-HJ-NPR-Z0-9]{17}", vin):
        raise CheckError("VIN не прошёл проверку 17 символов.")
    return vin


class Link:
    def __init__(self, connection, stop, log, clock=time.monotonic):
        self.connection, self.stop, self.log, self.clock = connection, stop, log, clock
        self.stn2120 = False

    def check_stop(self):
        if self.stop.is_set():
            raise Cancelled("Проверка остановлена. Канал адаптера автоматически не восстанавливается.")

    def query(self, command, timeout=3):
        if command not in ALLOWED:
            raise CheckError("Команда вне разрешённого списка диагностики.")
        self.check_stop()
        self.connection.reset_input_buffer()
        self.log("TX " + command)
        self.connection.write((command + "\r").encode("ascii"))
        self.connection.flush()
        raw = bytearray()
        deadline = self.clock() + timeout
        stopped = False
        while self.clock() < deadline:
            self.check_stop()
            raw.extend(self.connection.read(min(self.connection.in_waiting or 1, 4096)))
            if len(raw) > 16384:
                raise CheckError("Ответ адаптера слишком длинный.")
            if b">" in raw:
                break
            if command == "22F190" and self.stn2120 and not stopped and raw.endswith((b"\r", b"\n")):
                try:
                    decode_vin(raw.decode("ascii").splitlines())
                except (CheckError, UnicodeDecodeError):
                    continue
                # STN2120 может продолжать слушать шину после ответа;
                # любой символ прерывает приём и возвращает приглашение >.
                self.connection.write(b" ")
                self.connection.flush()
                self.log("TX SPACE (полный VIN получен; завершение приёма)")
                stopped = True
                deadline = self.clock() + 3
        self.log("RX " + repr(bytes(raw)))
        return parse(bytes(raw), command)

    def checked(self, command, expected="OK"):
        if self.query(command) != [expected]:
            raise CheckError(command + ": адаптер не подтвердил настройку; следующие команды не отправлены.")


def check(port, stop, log, stage=lambda *_: None, factory=serial.Serial, bauds=BAUDS, settle=0.25):
    result = dict(version=VERSION, port=port, ok=False, stage="com", vin=None,
                  route_confirmed=False, no_adb=True, no_security_access=True,
                  no_ecu_settings_writes=True, physical_pins_measured=False,
                  adapter_settings_may_have_changed=False)
    connection = None
    try:
        if not re.fullmatch(PORT_RE, port or "", PORT_FLAGS):
            raise CheckError("Последовательный порт не выбран или имя не похоже на адаптер "
                             "(ожидается " + ("COMn" if IS_WINDOWS else "/dev/ttyUSBn, /dev/ttyACMn, /dev/rfcommn") + ").")
        extra = {} if IS_WINDOWS else {"exclusive": True}  # не делить порт с ModemManager и др.
        connection = factory(port=None, baudrate=bauds[0], timeout=0.08, write_timeout=1,
                             bytesize=8, parity="N", stopbits=1, xonxoff=False, rtscts=False, dsrdtr=False,
                             **extra)
        connection.dtr = False
        connection.rts = False
        connection.port = port
        try:
            connection.open()
        except (serial.SerialException, OSError) as exc:
            raise CheckError(open_error_hint(port, exc)) from exc
        link = Link(connection, stop, log)
        link.check_stop()
        stage("com", "OK — " + port)
        result["stage"] = "adapter"
        found = None
        for baud in bauds:
            link.check_stop()
            connection.baudrate = baud
            if stop.wait(settle):
                link.check_stop()
            log(f"UART {baud} бод (это не скорость CAN)")
            try:
                found = identify(link.query("ATI", 1.6))
                if found and identify(link.query("ATI", 1.6)) == found:
                    result.update(baud=baud, ati=found)
                    break
            except Cancelled:
                raise
            except CheckError:
                pass
            found = None
        if not found:
            raise CheckError("Адаптер не распознан ни на одной скорости. Проверьте питание OBD, драйвер и кабель.")
        sti = link.query("STI")
        result["sti"] = sti
        stn1170 = sti == ["STN1170 v3.3.1"]
        stn2120 = len(sti) == 1 and re.fullmatch(r"STN2120(?:\s+v?[0-9][\w. -]*)?", sti[0], re.I)
        elm = sti == ["?"] and found.upper().startswith("ELM327")
        if not (stn1170 or stn2120 or elm):
            raise CheckError("Неизвестная модель/версия STN. Автопереключение и запрос VIN не выполнялись.")
        result["adapter"] = sti[0] if not elm else found + " (обычный ELM)"
        stage("adapter", "OK — " + result["adapter"])
        result["voltage"] = link.query("ATRV")
        link.stn2120 = bool(stn2120)
        result["stage"] = "pins"
        if not elm:
            result["before"] = {c: link.query(c) for c in ("STPR", "STPBRR", "STPRS")}
        result["adapter_settings_may_have_changed"] = True
        for command in ("ATE0", "ATL0", "ATS0", "ATH1", "ATAL"):
            link.checked(command)
        if elm:
            link.checked("ATSP6")
            result["route"] = "HS-CAN через ELM (ISO 15765-4, 11-бит, 500 кбит/с, пины 6/14)."
            stage("pins", "HS-CAN / 6–14 (стандартная разводка OBD)")
        else:
            link.checked("STP33")
            after = result["after"] = {c: link.query(c) for c in ("STPR", "STPBRR", "STPRS")}
            if (after["STPR"] != ["33"] or after["STPBRR"] != ["500000"] or len(after["STPRS"]) != 1
                    or not re.search(r"500K/11B", after["STPRS"][0], re.I)):
                raise CheckError("Не подтверждён HS-CAN 500K/11B; запрос VIN не отправлен.")
            result.update(route_confirmed=True, route="HS-CAN 33, 500000, 11-bit; стандартная разводка OBD 6/14")
            stage("pins", "OK — HS-CAN / 6–14 (стандартная разводка OBD)")
        for command in ("ATSH72B", "ATCRA7AB", "ATFCSH72B", "ATFCSD300000", "ATFCSM1",
                        "ATCFC1", "ATCAF1", "ATAT2", "ATST96"):
            link.checked(command)
        if not elm:
            for command in ("STCFCPC", "STCFCPA72B,7AB"):
                link.checked(command)
        result["stage"] = "vin"
        stage("vin", "Чтение из ГУ…")
        result["vin"] = decode_vin(link.query("22F190", 10))
        stage("vin", result["vin"])
        result.update(ok=True, stage="done",
                      summary="Связь с ГУ подтверждена, VIN прочитан. Это не проверка готовности ADB/русификации.")
    except Cancelled as exc:
        result.update(cancelled=True, summary=str(exc))
    except (CheckError, serial.SerialException, OSError) as exc:
        result.update(summary=str(exc), error_type=type(exc).__name__)
        stage(result["stage"], "Не подтверждено — " + str(exc))
    finally:
        if connection is not None:
            connection.close()
    return result


def windows_devices():
    """Small read-only PnP inventory. No elevation, driver install or network."""
    script = ("[Console]::OutputEncoding = [System.Text.Encoding]::UTF8\n"
              "@(Get-CimInstance Win32_PnPEntity | Where-Object {\n"
              " $_.PNPClass -eq 'Ports' -or $_.PNPDeviceID -match 'VID_(0403|067B|1A86|10C4)'\n"
              "} | Select-Object Name,PNPClass,ConfigManagerErrorCode,Status,Manufacturer) | ConvertTo-Json -Compress")
    try:
        exe = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        run = subprocess.run([str(exe), "-NoProfile", "-NonInteractive", "-Command", script],
                             capture_output=True, timeout=15,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if run.returncode:
            return {"error": "Не удалось прочитать PnP, код " + str(run.returncode)}
        return json.loads(run.stdout.decode("utf-8-sig") or "[]")
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return {"error": "Сведения PnP недоступны; это не результат проверки адаптера."}


def save_report(folder, result, inventory, events, pnp):
    folder = Path(folder)
    report = dict(result, created=datetime.datetime.now().astimezone().isoformat(),
                  windows=platform.platform(), ports=inventory, pnp=pnp,
                  privacy="Содержит VIN и USB-серийный номер. Автоматической отправки нет.")
    summary = ("BZ3X — проверка подключения " + VERSION + "\n" + result["summary"]
               + "\nVIN: " + (result.get("vin") or "не прочитан")
               + "\nКанал: " + result.get("route", "не подтверждён")
               + "\nФизические контакты не измерены. ADB и русификация не проверялись.\n"
                 "Настройки CAN адаптера могли измениться; EEPROM и настройки автомобиля не записывались.\n"
                 "Передайте этот ZIP установщику. Он содержит VIN и сведения USB/COM.\n")
    archive = folder / ("BZ3X_CHECK_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f") + ".zip")
    with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED) as z:
        z.writestr("RESULT.txt", summary.encode("utf-8-sig"))
        z.writestr("report.json", json.dumps(report, ensure_ascii=False, indent=2))
        z.writestr("serial.log", "\n".join(events))
    return archive


# --------------------------------------------------------------------------- Linux / CLI

def open_error_hint(port, exc):
    """Человекочитаемая причина, почему порт не открылся."""
    text = str(exc)
    code = getattr(exc, "errno", None)
    if IS_WINDOWS:
        return "Не удалось открыть " + port + ": " + text
    if code == errno.ENOENT or "No such file" in text:
        return f"{port} не существует. Подключите адаптер; список портов: python3 diagnostic.py --list"
    if code == errno.EACCES or "Permission denied" in text:
        group = port_group(port) or "dialout"
        return (f"Нет прав на {port}. Добавьте пользователя в группу {group}: "
                f"sudo usermod -aG {group} $USER, затем перелогиньтесь (или временно: sudo chmod a+rw {port}).")
    if code in (errno.EBUSY, errno.EAGAIN) or "exclusively lock" in text or "busy" in text.lower():
        return (f"{port} занят другой программой (часто ModemManager, minicom, screen, другая диагностика). "
                "Закройте её или: sudo systemctl stop ModemManager")
    return "Не удалось открыть " + port + ": " + text


def port_group(port):
    try:
        import grp
        return grp.getgrgid(os.stat(port).st_gid).gr_name
    except (ImportError, OSError, KeyError):
        return None


def linux_devices():
    """Read-only инвентаризация tty-устройств из /sys (аналог windows_devices)."""
    out = []
    try:
        entries = sorted(Path("/sys/class/tty").iterdir())
    except OSError as exc:
        return {"error": "Сведения /sys недоступны: " + str(exc)}
    for entry in entries:
        dev = entry / "device"
        if not dev.exists():
            continue
        name = "/dev/" + entry.name
        if entry.name.startswith("ttyS") and not (dev / "driver").exists():
            continue
        item = {"Name": name}
        try:
            item["Driver"] = (dev / "driver").resolve().name
        except OSError:
            item["Driver"] = None
        usb = dev.resolve()
        for _ in range(4):  # поднимаемся до USB-устройства с idVendor
            if (usb / "idVendor").exists():
                for key in ("idVendor", "idProduct", "manufacturer", "product", "serial"):
                    try:
                        item[key] = (usb / key).read_text().strip()
                    except OSError:
                        pass
                break
            usb = usb.parent
        if os.path.exists(name):
            item["Group"] = port_group(name)
            item["Access"] = os.access(name, os.R_OK | os.W_OK)
        out.append(item)
    return out


def devices():
    return windows_devices() if IS_WINDOWS else linux_devices()


def default_report_dir():
    return Path.cwd()  # отчёт кладётся в текущую директорию


def main(argv=None):
    ap = argparse.ArgumentParser(description="BZ3X — проверка подключения " + VERSION +
                                 " (канал адаптера + чтение VIN из ГУ, только чтение)")
    ap.add_argument("-p", "--port", help="порт адаптера, напр. /dev/ttyUSB0 (по умолчанию — единственный USB-порт)")
    ap.add_argument("-l", "--list", action="store_true", help="показать порты и выйти")
    ap.add_argument("-o", "--out", type=Path, default=None, help="папка для ZIP-отчёта (по умолчанию — текущая директория)")
    ap.add_argument("--no-report", action="store_true", help="не сохранять ZIP-отчёт")
    ap.add_argument("-y", "--yes", action="store_true", help="не спрашивать подтверждение")
    ap.add_argument("-q", "--quiet", action="store_true", help="не печатать обмен TX/RX")
    args = ap.parse_args(argv)

    inventory = ports()
    if args.list or not inventory:
        if not inventory:
            print("Последовательных портов не найдено — проверьте USB и драйвер.", file=sys.stderr)
        for p in inventory:
            vidpid = f"{p['vid']:04X}:{p['pid']:04X}" if p["vid"] is not None else "-"
            print(f"{p['device']:<22} {vidpid:<10} {p['description'] or ''}")
        return 0 if inventory else 2

    port = args.port or preferred_port(inventory)
    if not port:
        print("Найдено несколько портов — укажите адаптер через --port (список: --list).", file=sys.stderr)
        return 2

    if not args.yes:
        print(f"Порт: {port}\nМашина в P, адаптер выбран верно, питание ГУ включено? [y/N] ", end="", flush=True)
        if sys.stdin.readline().strip().lower() not in ("y", "yes", "д", "да"):
            print("Отменено, команды не отправлялись.")
            return 1

    events = []

    def log(message):
        line = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3] + " " + message
        events.append(line)
        if not args.quiet:
            print("  " + line, file=sys.stderr)

    def stage(name, text):
        events.append(f"[{name}] {text}")
        print(f"[{name}] {text}")

    stop = threading.Event()
    box = {}
    worker = threading.Thread(target=lambda: box.update(result=check(port, stop, log, stage)), daemon=True)
    worker.start()
    try:
        while worker.is_alive():
            worker.join(0.2)
    except KeyboardInterrupt:
        print("\nОстанавливаю проверку…", file=sys.stderr)
        stop.set()
        worker.join()
    result = box.get("result") or {"ok": False, "summary": "Проверка завершилась без результата."}

    print()
    print("ИТОГ:", result.get("summary", ""))
    if result.get("vin"):
        print("VIN: ", result["vin"])
    if result.get("route"):
        print("Канал:", result["route"])

    if not args.no_report:
        folder = args.out or default_report_dir()
        try:
            folder.mkdir(parents=True, exist_ok=True)
            archive = save_report(folder, result, inventory, events, devices())
            print("Отчёт:", archive)
        except OSError as exc:
            print("Не удалось сохранить отчёт:", exc, file=sys.stderr)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
