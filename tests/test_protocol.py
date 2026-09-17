import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spike import protocol as p


def test_roundtrip_gaze():
    kind, f = p.decode(p.gaze(960, 540, 0.87, 0))
    assert kind == "G"
    assert int(f[0]) == 960 and int(f[1]) == 540
    assert abs(float(f[2]) - 0.87) < 0.01


def test_roundtrip_event_and_pressure():
    kind, f = p.decode(p.event("left_click", 12345))
    assert kind == "E" and f[0] == "left_click" and int(f[1]) == 12345
    kind, f = p.decode(p.pressure(-7.25, 999))
    assert kind == "P" and abs(float(f[0]) + 7.25) < 0.01


def test_messages_end_with_newline():
    for m in (p.gaze(1, 2), p.heartbeat(5), p.state("ok"), p.target("t1", 3, 4)):
        assert m.endswith("\n")
        assert "*" in m


def test_single_bit_flip_is_caught():
    """UART on jumper wires next to a switching supply does flip bits, and a
    corrupted coordinate that teleports the cursor is worse than a dropped
    frame. Verify the CRC actually catches corruption in the payload."""
    good = p.gaze(960, 540, 1.0, 0)
    body = good[:good.rfind("*")]
    caught = 0
    for i in range(len(body)):
        if not body[i].isdigit():
            continue
        flipped = body[:i] + str((int(body[i]) + 1) % 10) + body[i + 1:]
        corrupt = flipped + good[good.rfind("*"):]
        with pytest.raises(p.ProtocolError):
            p.decode(corrupt)
        caught += 1
    assert caught > 5, "test did not actually exercise any corruption"


@pytest.mark.parametrize("bad", [
    "", "   ", "G 1 2 3", "G 1 2*ZZ", "G 1 2*1", "*AB", "G 1 2*",
])
def test_malformed_input_raises_cleanly(bad):
    with pytest.raises(p.ProtocolError):
        p.decode(bad)


def test_decode_accepts_bytes():
    kind, _ = p.decode(p.heartbeat(1).encode("ascii"))
    assert kind == "H"


# -- framing -----------------------------------------------------------

def test_line_reader_splits_on_newlines():
    r = p.LineReader()
    assert r.feed("A*00\nB*00\n") == ["A*00", "B*00"]


def test_line_reader_handles_split_packets():
    r = p.LineReader()
    assert r.feed("G 960 5") == []
    assert r.feed("40 1.00 0*") == []
    out = r.feed("%s\n" % format(p.crc8(b"G 960 540 1.00 0"), "02X"))
    assert len(out) == 1
    kind, f = p.decode(out[0])
    assert kind == "G" and int(f[0]) == 960


def test_line_reader_buffer_is_bounded():
    """A wedged peer that never sends a newline must not grow this without
    limit on a board with 256KB of RAM."""
    r = p.LineReader(max_line=64)
    for _ in range(50):
        r.feed("x" * 32)
    assert len(r._buf) <= 64
    assert r.overruns > 0


def test_crc8_is_deterministic_and_byte_sized():
    for s in (b"", b"G 1 2", b"a" * 200):
        c = p.crc8(s)
        assert 0 <= c <= 255
        assert c == p.crc8(s)
