import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spike import gesture as g

CFG = {
    "thresholds": {"soft_puff": 4.0, "hard_puff": 12.0,
                   "soft_sip": -4.0, "hard_sip": -12.0},
    "debounce_ms": 40,
    "hold_ms": 1500,
    "command_timeout_ms": 4000,
    "sequences": {"puff": "recalibrate", "puff,puff": "mode_toggle"},
}


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, ms):
        self.t += ms / 1000.0


def drive(m, clk, channel, ms, step=10):
    """Hold a channel for `ms`, collecting every event emitted."""
    events = []
    for _ in range(max(1, int(ms // step))):
        events += m.update(channel, clk())
        clk.advance(step)
    return events


# -- classification ----------------------------------------------------

@pytest.mark.parametrize("hpa,expect", [
    (0.0, g.NEUTRAL), (2.0, g.NEUTRAL), (-2.0, g.NEUTRAL),
    (5.0, g.SOFT_PUFF), (12.0, g.HARD_PUFF), (30.0, g.HARD_PUFF),
    (-5.0, g.SOFT_SIP), (-12.0, g.HARD_SIP), (-30.0, g.HARD_SIP),
])
def test_classify(hpa, expect):
    assert g.classify(hpa, CFG["thresholds"]) == expect


# -- the fast path -----------------------------------------------------

def test_soft_puff_emits_left_click_on_release():
    clk = Clock()
    m = g.GestureMachine(CFG, clock=clk)
    drive(m, clk, g.NEUTRAL, 100)
    assert drive(m, clk, g.SOFT_PUFF, 200) == []      # nothing while held
    assert g.EV_LEFT_CLICK in drive(m, clk, g.NEUTRAL, 100)


def test_click_latency_is_only_debounce():
    """The headline property: an ordinary click costs debounce, nothing more.

    If a multi-puff gesture existed on the fast path, this would have to wait
    an inter-puff window on every click. It does not, and this test is what
    stops someone from casually reintroducing one.
    """
    clk = Clock()
    m = g.GestureMachine(CFG, clock=clk)
    drive(m, clk, g.NEUTRAL, 100)
    drive(m, clk, g.SOFT_PUFF, 120)

    t_release = clk()
    fired_at = None
    for _ in range(60):
        if g.EV_LEFT_CLICK in m.update(g.NEUTRAL, clk()):
            fired_at = clk()
            break
        clk.advance(5)
    assert fired_at is not None, "click never fired"
    latency_ms = (fired_at - t_release) * 1000.0
    assert latency_ms <= CFG["debounce_ms"] + 10, (
        "click latency %.0fms exceeds debounce -- something added a wait to "
        "the fast path" % latency_ms)


def test_short_hard_sip_is_an_ordinary_right_click():
    clk = Clock()
    m = g.GestureMachine(CFG, clock=clk)
    drive(m, clk, g.NEUTRAL, 100)
    drive(m, clk, g.HARD_SIP, 300)            # well under hold_ms
    assert g.EV_RIGHT_CLICK in drive(m, clk, g.NEUTRAL, 100)
    assert m.state == g.IDLE


def test_hard_puff_toggles_drag():
    clk = Clock()
    m = g.GestureMachine(CFG, clock=clk)
    drive(m, clk, g.NEUTRAL, 100)
    drive(m, clk, g.HARD_PUFF, 200)
    assert g.EV_DRAG_TOGGLE in drive(m, clk, g.NEUTRAL, 100)


def test_below_debounce_is_ignored():
    clk = Clock()
    m = g.GestureMachine(CFG, clock=clk)
    drive(m, clk, g.NEUTRAL, 100)
    evs = drive(m, clk, g.SOFT_PUFF, 20)      # under debounce_ms
    evs += drive(m, clk, g.NEUTRAL, 100)
    assert g.EV_LEFT_CLICK not in evs


# -- command mode ------------------------------------------------------

def test_long_hard_sip_opens_command_mode():
    clk = Clock()
    m = g.GestureMachine(CFG, clock=clk)
    drive(m, clk, g.NEUTRAL, 100)
    evs = drive(m, clk, g.HARD_SIP, 1800)
    assert g.EV_COMMAND_ENTER in evs
    assert m.state == g.COMMAND


def test_prefix_release_does_not_emit_right_click():
    """Entering command mode must not also fire the right click that the
    same sip would have produced had it been released earlier."""
    clk = Clock()
    m = g.GestureMachine(CFG, clock=clk)
    drive(m, clk, g.NEUTRAL, 100)
    drive(m, clk, g.HARD_SIP, 1800)
    evs = drive(m, clk, g.NEUTRAL, 200)
    assert g.EV_RIGHT_CLICK not in evs


def test_recalibrate_sequence():
    clk = Clock()
    m = g.GestureMachine(CFG, clock=clk)
    drive(m, clk, g.NEUTRAL, 100)
    drive(m, clk, g.HARD_SIP, 1800)           # prefix
    drive(m, clk, g.NEUTRAL, 200)             # release prefix
    drive(m, clk, g.SOFT_PUFF, 150)
    evs = drive(m, clk, g.NEUTRAL, 150)
    assert g.EV_RECALIBRATE in evs
    assert m.state == g.IDLE


def test_two_puff_sequence_reaches_mode_toggle():
    cfg = dict(CFG, sequences={"puff,puff": "mode_toggle"})
    clk = Clock()
    m = g.GestureMachine(cfg, clock=clk)
    drive(m, clk, g.NEUTRAL, 100)
    drive(m, clk, g.HARD_SIP, 1800)
    drive(m, clk, g.NEUTRAL, 200)
    drive(m, clk, g.SOFT_PUFF, 150)
    evs = drive(m, clk, g.NEUTRAL, 150)
    assert g.EV_MODE_TOGGLE not in evs        # "puff" alone is only a prefix
    drive(m, clk, g.SOFT_PUFF, 150)
    evs = drive(m, clk, g.NEUTRAL, 150)
    assert g.EV_MODE_TOGGLE in evs


def test_command_mode_times_out():
    clk = Clock()
    m = g.GestureMachine(CFG, clock=clk)
    drive(m, clk, g.NEUTRAL, 100)
    drive(m, clk, g.HARD_SIP, 1800)
    drive(m, clk, g.NEUTRAL, 200)
    evs = drive(m, clk, g.NEUTRAL, 5000)
    assert g.EV_COMMAND_TIMEOUT in evs
    assert m.state == g.IDLE


def test_dead_end_sequence_exits_without_firing():
    cfg = dict(CFG, sequences={"puff": "recalibrate"})
    clk = Clock()
    m = g.GestureMachine(cfg, clock=clk)
    drive(m, clk, g.NEUTRAL, 100)
    drive(m, clk, g.HARD_SIP, 1800)
    drive(m, clk, g.NEUTRAL, 200)
    drive(m, clk, g.SOFT_SIP, 150)            # no sequence starts with sip
    evs = drive(m, clk, g.NEUTRAL, 150)
    assert g.EV_COMMAND_EXIT in evs
    assert g.EV_RECALIBRATE not in evs
    assert m.state == g.IDLE


def test_no_clicks_leak_while_in_command_mode():
    clk = Clock()
    m = g.GestureMachine(CFG, clock=clk)
    drive(m, clk, g.NEUTRAL, 100)
    drive(m, clk, g.HARD_SIP, 1800)
    drive(m, clk, g.NEUTRAL, 200)
    evs = drive(m, clk, g.SOFT_PUFF, 150) + drive(m, clk, g.NEUTRAL, 150)
    assert g.EV_LEFT_CLICK not in evs
