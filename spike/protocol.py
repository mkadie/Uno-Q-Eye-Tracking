"""Framed serial protocol: UNO Q (Linux, vision) <-> breath board (CircuitPython).

Wire format, one message per line, ASCII, newline terminated:

    <TYPE> <field> <field> ... *<CRC8>\n

ASCII rather than binary because you will be debugging this over a USB-serial
adapter with a terminal open at 3am, and being able to read the traffic is
worth more than the bytes you save. At 115200 baud a 40-byte line costs about
3.5ms, which is nothing against a 30fps frame budget.

CRC8 because UART on jumper wires next to a switching supply does flip bits,
and a corrupted gaze coordinate that silently teleports the cursor is much
worse than a dropped frame.

UNO Q -> breath board:
    G <x> <y> <conf> <flags>    gaze sample, x/y in screen px, conf 0..1
    T <id> <x> <y>              current dwell-free target under gaze (for
                                click-time ground truth capture)
    S <state>                   pipeline state: ok | nofail | lost | blink

breath board -> UNO Q:
    E <event> <t_ms>            gesture event (left_click, recalibrate, ...)
    P <hpa> <t_ms>              raw pressure telemetry (for threshold tuning)
    H <uptime_ms>               heartbeat

The heartbeat matters: if the breath board stops talking, the UNO Q must know
within a frame or two, because a pointing device whose click channel has died
should stop moving the cursor rather than sit there looking functional.
"""

_CRC8_POLY = 0x07


def crc8(data):
    """CRC-8/ATM. Small, adequate for 40-byte frames, trivial on CircuitPython."""
    crc = 0
    for b in bytearray(data):
        crc ^= b
        for _ in range(8):
            crc = ((crc << 1) ^ _CRC8_POLY) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def encode(msg_type, *fields):
    body = msg_type
    for f in fields:
        if isinstance(f, float):
            body += " %.2f" % f
        else:
            body += " %s" % f
    return "%s*%02X\n" % (body, crc8(body.encode("ascii")))


class ProtocolError(Exception):
    pass


def decode(line):
    """Parse one line. Returns (type, [fields]). Raises ProtocolError."""
    if isinstance(line, (bytes, bytearray)):
        line = line.decode("ascii", "replace")
    line = line.strip()
    if not line:
        raise ProtocolError("empty line")
    star = line.rfind("*")
    if star < 0:
        raise ProtocolError("no checksum delimiter")
    body, want = line[:star], line[star + 1:]
    if len(want) != 2:
        raise ProtocolError("malformed checksum field")
    try:
        want_v = int(want, 16)
    except ValueError:
        raise ProtocolError("non-hex checksum")
    got = crc8(body.encode("ascii"))
    if got != want_v:
        raise ProtocolError("checksum mismatch: got %02X want %02X" % (got, want_v))
    parts = body.split()
    if not parts:
        raise ProtocolError("no message type")
    return parts[0], parts[1:]


# -- convenience constructors ------------------------------------------

def gaze(x, y, conf=1.0, flags=0):
    return encode("G", int(round(x)), int(round(y)), float(conf), int(flags))


def target(tid, x, y):
    return encode("T", tid, int(round(x)), int(round(y)))


def state(name):
    return encode("S", name)


def event(name, t_ms):
    return encode("E", name, int(t_ms))


def pressure(hpa, t_ms):
    return encode("P", float(hpa), int(t_ms))


def heartbeat(uptime_ms):
    return encode("H", int(uptime_ms))


class LineReader:
    """Incremental newline framer for a non-blocking serial stream.

    Bounded buffer: a wedged peer that never sends a newline must not be able
    to grow this without limit on a board with 256KB of RAM.
    """

    def __init__(self, max_line=256):
        self._buf = ""
        self.max_line = max_line
        self.overruns = 0

    def feed(self, chunk):
        """Add received bytes/str, yield complete lines."""
        if isinstance(chunk, (bytes, bytearray)):
            chunk = chunk.decode("ascii", "replace")
        self._buf += chunk
        out = []
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            out.append(line)
        if len(self._buf) > self.max_line:
            self._buf = ""
            self.overruns += 1
        return out
