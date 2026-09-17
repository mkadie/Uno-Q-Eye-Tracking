"""Breath board firmware: gaze + breath fusion, HID output.

Runs on your existing CircuitPython board. It stays the single HID endpoint --
your tested pressure sensing, thresholds and debounce keep working exactly as
they do now, and the UNO Q is demoted to a sensor that streams coordinates in
over UART.

That split is deliberate. It means the eye tracker is a bolt-on that anyone
who already built the sip-n-puff can add, rather than a rewrite that orphans
existing builds -- which matters more for an open-source assistive project
than architectural tidiness does.

Copy to CIRCUITPY/code.py. Copy gesture.py alongside it. Copy config.toml to
CIRCUITPY/config.toml.

Wiring:
  UNO Q header TX  ->  this board RX     (both 3.3V; verify before connecting)
  UNO Q header RX  ->  this board TX
  UNO Q GND        ->  this board GND
  pressure sensor  ->  I2C (SDA/SCL) as you already have it

Dependencies (lib/): adafruit_hid, adafruit_mprls (or your sensor's driver),
adafruit_bus_device.
"""

import struct
import supervisor
import time

import board
import busio
import usb_hid
from adafruit_hid.mouse import Mouse

import gesture

try:
    import tomllib
except ImportError:
    tomllib = None

# ---------------------------------------------------------------- config

DEFAULT_CFG = {
    "thresholds": {"soft_puff": 4.0, "hard_puff": 12.0,
                   "soft_sip": -4.0, "hard_sip": -12.0},
    "debounce_ms": 40,
    "hold_ms": 1500,
    "command_timeout_ms": 4000,
    "sequences": {"puff": "recalibrate", "puff,puff": "mode_toggle"},
    "gaze_timeout_ms": 400,
    "move_deadzone_px": 3,
}


def load_config(path="/config.toml"):
    cfg = dict(DEFAULT_CFG)
    if tomllib is None:
        return cfg
    try:
        with open(path, "rb") as f:
            user = tomllib.load(f)
        breath = user.get("breath", {})
        for k, v in breath.items():
            if k == "thresholds" and isinstance(v, dict):
                cfg["thresholds"].update(v)
            else:
                cfg[k] = v
    except Exception as e:
        print("config load failed (%s); using defaults" % e)
    return cfg


CFG = load_config()

# ---------------------------------------------------------------- sensor

i2c = busio.I2C(board.SCL, board.SDA)

_sensor = None
_baseline = 0.0


def init_sensor():
    """Replace with your sensor's driver if it is not an MPRLS.

    Whatever it is, the contract is: read_pressure() returns SIGNED hPa
    relative to ambient, positive for puff. Keeping that contract is what lets
    the thresholds in config.toml mean the same thing on somebody else's build.
    """
    global _sensor
    import adafruit_mprls
    _sensor = adafruit_mprls.MPRLS(i2c, psi_min=0, psi_max=25)


def tare(n=32):
    """Capture ambient. Room pressure and altitude both matter, so this has
    to happen at boot rather than being baked into the thresholds."""
    global _baseline
    total = 0.0
    for _ in range(n):
        total += _sensor.pressure
        time.sleep(0.01)
    _baseline = total / n
    print("tared at %.2f hPa" % _baseline)


def read_pressure():
    return _sensor.pressure - _baseline


# ---------------------------------------------------------------- serial

uart = busio.UART(board.TX, board.RX, baudrate=115200, timeout=0)

_CRC8_POLY = 0x07


def crc8(data):
    crc = 0
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = ((crc << 1) ^ _CRC8_POLY) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def send(msg_type, *fields):
    body = msg_type
    for f in fields:
        body += " %.2f" % f if isinstance(f, float) else " %s" % f
    uart.write(("%s*%02X\n" % (body, crc8(body.encode("ascii")))).encode("ascii"))


def parse(line):
    star = line.rfind("*")
    if star < 0:
        return None
    body = line[:star]
    try:
        if crc8(body.encode("ascii")) != int(line[star + 1:], 16):
            return None
    except ValueError:
        return None
    parts = body.split()
    return (parts[0], parts[1:]) if parts else None


# ---------------------------------------------------------------- main

mouse = Mouse(usb_hid.devices)
machine = gesture.GestureMachine(CFG)

gaze_x = gaze_y = None
gaze_t = 0.0
target_id = None
target_xy = None
drag = False
rx = ""


def ms():
    return int(time.monotonic() * 1000)


def handle_events(events):
    global drag
    for ev in events:
        if ev == gesture.EV_LEFT_CLICK:
            mouse.click(Mouse.LEFT_BUTTON)
            # Report the click back so the UNO Q can harvest it as free
            # calibration ground truth: it knows where the gaze estimate was,
            # and the UI knows what was actually hit.
            send("E", "left_click", ms())
        elif ev == gesture.EV_RIGHT_CLICK:
            mouse.click(Mouse.RIGHT_BUTTON)
            send("E", "right_click", ms())
        elif ev == gesture.EV_DRAG_TOGGLE:
            drag = not drag
            if drag:
                mouse.press(Mouse.LEFT_BUTTON)
            else:
                mouse.release(Mouse.LEFT_BUTTON)
            send("E", "drag_%s" % ("on" if drag else "off"), ms())
        elif ev in (gesture.EV_RECALIBRATE, gesture.EV_MODE_TOGGLE):
            send("E", ev, ms())
        elif ev == gesture.EV_COMMAND_ENTER:
            send("E", "command_enter", ms())
        elif ev == gesture.EV_COMMAND_EXIT:
            send("E", "command_exit", ms())
        elif ev == gesture.EV_COMMAND_TIMEOUT:
            send("E", "command_timeout", ms())


def main():
    global gaze_x, gaze_y, gaze_t, rx, target_id, target_xy
    init_sensor()
    tare()
    print("ready")

    last_beat = 0.0
    last_sent = [0, 0]

    while True:
        now = time.monotonic()

        # -- breath ---------------------------------------------------
        try:
            p = read_pressure()
        except Exception:
            continue
        chan = gesture.classify(p, CFG["thresholds"])
        handle_events(machine.update(chan, now))

        # -- inbound gaze ---------------------------------------------
        n = uart.in_waiting
        if n:
            rx += uart.read(n).decode("ascii", "replace")
            while "\n" in rx:
                line, rx = rx.split("\n", 1)
                msg = parse(line.strip())
                if not msg:
                    continue
                kind, f = msg
                if kind == "G" and len(f) >= 2:
                    gaze_x, gaze_y = int(f[0]), int(f[1])
                    gaze_t = now
                elif kind == "T" and len(f) >= 3:
                    target_id = f[0]
                    target_xy = (int(f[1]), int(f[2]))
            if len(rx) > 256:
                rx = ""

        # -- pointing -------------------------------------------------
        # Suppress movement in COMMAND mode: the user is issuing a gesture,
        # not pointing, and a cursor wandering during that is confusing.
        stale = (now - gaze_t) * 1000.0 > CFG["gaze_timeout_ms"]
        if (gaze_x is not None and not stale
                and machine.state != gesture.COMMAND):
            dx = gaze_x - last_sent[0]
            dy = gaze_y - last_sent[1]
            if abs(dx) + abs(dy) >= CFG["move_deadzone_px"]:
                # HID relative movement is a signed byte per report.
                while dx or dy:
                    sx = max(-127, min(127, dx))
                    sy = max(-127, min(127, dy))
                    mouse.move(x=sx, y=sy)
                    dx -= sx
                    dy -= sy
                last_sent = [gaze_x, gaze_y]

        # -- telemetry ------------------------------------------------
        if now - last_beat > 0.5:
            last_beat = now
            send("H", ms())
            send("P", float(p), ms())


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        # A crash here leaves someone without a pointing device. Surface the
        # error, release any held button, and let the auto-reload recover.
        print("FATAL: %s" % e)
        try:
            Mouse(usb_hid.devices).release_all()
        except Exception:
            pass
        time.sleep(2)
        supervisor.reload()
