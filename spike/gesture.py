"""Breath gesture state machine.

Runs on BOTH CPython (for the tests) and CircuitPython (on the breath board).
So: no dataclasses, no typing, no enum, no f-string debug specifiers. Keep it
to the intersection of the two languages.

DESIGN NOTE -- why there is no multi-puff click gesture
-------------------------------------------------------
The obvious way to spell "recalibrate" is triple-puff or puff-sip-puff. Both
are wrong here, and the reason is latency, not recognition difficulty.

To recognise a multi-puff sequence you must wait after every puff to see
whether another one follows. That wait is added to the latency of every
ordinary left click, forever. A pointing device that delays every click by
400ms to watch for a sequence that fires twice a day is a device people stop
using.

So sequences live behind a prefix that is not itself a click: a hard sip held
past HOLD_MS. A normal sip-click releases long before that threshold, so the
fast path is untouched -- zero added latency on every ordinary click. Once
COMMAND mode is entered, multi-event sequences are free, because nothing in
command mode is latency-critical.

States:
  IDLE     -- normal pointing. Puff = left click, sip = right click.
  ARMING   -- a sip is being held; may still resolve to a normal right click.
  COMMAND  -- prefix confirmed. Collecting a sequence. Pointing suppressed.
"""

try:
    from time import monotonic as _now
except ImportError:  # pragma: no cover
    from time import time as _now

IDLE = "idle"
ARMING = "arming"
COMMAND = "command"

# Breath channel classification
NEUTRAL = 0
SOFT_PUFF = 1
HARD_PUFF = 2
SOFT_SIP = -1
HARD_SIP = -2

# Emitted events
EV_LEFT_CLICK = "left_click"
EV_RIGHT_CLICK = "right_click"
EV_DRAG_TOGGLE = "drag_toggle"
EV_RECALIBRATE = "recalibrate"
EV_MODE_TOGGLE = "mode_toggle"
EV_COMMAND_ENTER = "command_enter"
EV_COMMAND_EXIT = "command_exit"
EV_COMMAND_TIMEOUT = "command_timeout"


def classify(pressure_hpa, thresholds):
    """Map a differential pressure reading to a breath channel.

    pressure_hpa is signed: positive = puff, negative = sip. Because the sensor
    is I2C and reports real units, these thresholds mean the same thing on
    somebody else's build -- which is the whole reason to expose them in a
    config file rather than as ADC counts.
    """
    p = pressure_hpa
    if p >= thresholds["hard_puff"]:
        return HARD_PUFF
    if p >= thresholds["soft_puff"]:
        return SOFT_PUFF
    if p <= thresholds["hard_sip"]:
        return HARD_SIP
    if p <= thresholds["soft_sip"]:
        return SOFT_SIP
    return NEUTRAL


class GestureMachine:
    """Consume classified breath channels, emit input events.

    cfg keys (all durations in milliseconds):
      debounce_ms          -- minimum time in a channel before it counts
      hold_ms              -- hard-sip hold that opens COMMAND mode
      command_timeout_ms   -- inactivity in COMMAND before bailing out
      sequences            -- dict mapping a sequence string to an event name,
                              e.g. {"puff": "recalibrate", "puff,puff": "mode_toggle"}
    """

    def __init__(self, cfg, clock=None):
        self.cfg = cfg
        self._clock = clock or _now
        self.state = IDLE
        self._chan = NEUTRAL
        self._chan_since = self._clock()
        self._stable_chan = NEUTRAL
        self._seq = []
        self._last_cmd_activity = 0.0
        self._suppress_release = False

    # -- helpers ---------------------------------------------------------
    def _ms(self, a, b):
        return (a - b) * 1000.0

    def _seq_key(self):
        return ",".join(self._seq)

    def _resolve_sequence(self):
        return self.cfg.get("sequences", {}).get(self._seq_key())

    # -- main ------------------------------------------------------------
    def update(self, channel, now=None):
        """Feed one classified sample. Returns a list of emitted events."""
        now = self._clock() if now is None else now
        events = []

        # Debounce: a channel must persist before we believe it.
        if channel != self._chan:
            self._chan = channel
            self._chan_since = now
            return events
        if self._ms(now, self._chan_since) < self.cfg["debounce_ms"]:
            return events

        prev = self._stable_chan
        cur = channel
        changed = cur != prev
        if changed:
            self._stable_chan = cur

        if self.state == IDLE:
            if changed and prev == NEUTRAL and cur == HARD_SIP:
                self.state = ARMING
                self._suppress_release = False
            elif changed and prev != NEUTRAL and cur == NEUTRAL:
                # Release of a completed breath -> emit the click on RELEASE,
                # not on press, so the user can abort by easing off.
                if prev == SOFT_PUFF:
                    events.append(EV_LEFT_CLICK)
                elif prev == HARD_PUFF:
                    events.append(EV_DRAG_TOGGLE)
                elif prev == SOFT_SIP:
                    events.append(EV_RIGHT_CLICK)

        elif self.state == ARMING:
            held = self._ms(now, self._chan_since)
            if cur == HARD_SIP and held >= self.cfg["hold_ms"]:
                self.state = COMMAND
                self._seq = []
                self._last_cmd_activity = now
                self._suppress_release = True
                events.append(EV_COMMAND_ENTER)
            elif changed and cur == NEUTRAL:
                # Released before the hold threshold: it was an ordinary
                # right click after all. No latency was added to it.
                if not self._suppress_release:
                    events.append(EV_RIGHT_CLICK)
                self.state = IDLE

        elif self.state == COMMAND:
            if self._ms(now, self._last_cmd_activity) >= self.cfg["command_timeout_ms"]:
                self.state = IDLE
                self._seq = []
                events.append(EV_COMMAND_TIMEOUT)
                events.append(EV_COMMAND_EXIT)
                return events

            if changed and prev != NEUTRAL and cur == NEUTRAL:
                if self._suppress_release:
                    # This is the release of the prefix sip itself. Swallow it.
                    self._suppress_release = False
                    self._last_cmd_activity = now
                    return events
                token = None
                if prev in (SOFT_PUFF, HARD_PUFF):
                    token = "puff"
                elif prev in (SOFT_SIP, HARD_SIP):
                    token = "sip"
                if token:
                    self._seq.append(token)
                    self._last_cmd_activity = now
                    hit = self._resolve_sequence()
                    if hit:
                        events.append(hit)
                        self.state = IDLE
                        self._seq = []
                        events.append(EV_COMMAND_EXIT)
                    elif not self._any_prefix():
                        # Dead end -- no configured sequence starts this way.
                        self.state = IDLE
                        self._seq = []
                        events.append(EV_COMMAND_EXIT)

        return events

    def _any_prefix(self):
        key = self._seq_key()
        for k in self.cfg.get("sequences", {}):
            if k.startswith(key):
                return True
        return False
