"""The detector's input mode: colour, gray, or colour-then-gray.

MEASURED 2026-10-04 (see RESULTS.md). The red lamp this project recommends
floods the face with one channel -- R 62.5 / G 16.0 / B 27.2 -- and colour
detection fell to 76%. Grayscale rescued it to 99%, and LOST white light,
95% -> 85%. Neither pure input is safe as a default, so the shipped mode runs
colour first and retries gray only on failure.

The property that makes that safe is the one worth pinning: **"both" can never
return nothing where "colour" would have found something.** It is one `if` away
from being wrong in a way no detection-rate number would obviously reveal --
a reordered retry would still look like it worked in the lighting that was
being debugged at the time.

No interpreters and no model files here; the dispatcher is stubbed the way
test_fullres_crop.py stubs the geometry helpers.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spike.backends.litert_backend import LiteRTBackend


class _Dispatch(LiteRTBackend):
    """Only _run_detector. `found` says which inputs a frame is findable in."""

    def __init__(self, detect_input, found):
        self.detect_input = detect_input
        self.found = found          # set of "colour" / "gray"
        self.calls = []
        self.stats = {"detector_frames": 0, "tracked_frames": 0,
                      "detector_colour_hits": 0, "detector_gray_hits": 0}

    def _detect_once(self, rgb, gray):
        which = "gray" if gray else "colour"
        self.calls.append(which)
        return ("hit", which) if which in self.found else None


CASES = ["colour", "gray", "both"]


@pytest.mark.parametrize("mode", CASES)
def test_rejects_an_unknown_mode(mode):
    with pytest.raises(ValueError):
        LiteRTBackend.__init__(object.__new__(LiteRTBackend), "d", "l",
                              detect_input=mode + "ish")


def test_colour_mode_never_tries_gray():
    d = _Dispatch("colour", {"gray"})
    assert d._run_detector(None) is None
    assert d.calls == ["colour"]


def test_gray_mode_never_tries_colour():
    d = _Dispatch("gray", {"colour"})
    assert d._run_detector(None) is None
    assert d.calls == ["gray"]


def test_both_stops_at_colour_when_colour_succeeds():
    """The no-cost case. The retry must not run, or white light pays for it."""
    d = _Dispatch("both", {"colour", "gray"})
    assert d._run_detector(None) == ("hit", "colour")
    assert d.calls == ["colour"]
    assert d.stats["detector_gray_hits"] == 0


def test_both_retries_gray_when_colour_fails():
    """The red-lamp case: 3 of 4 re-detections were found only by gray."""
    d = _Dispatch("both", {"gray"})
    assert d._run_detector(None) == ("hit", "gray")
    assert d.calls == ["colour", "gray"]
    assert d.stats["detector_gray_hits"] == 1
    assert d.stats["detector_colour_hits"] == 0


def test_both_is_a_superset_of_colour():
    """The whole safety argument, over every findability a frame can have.

    This is the test that would have caught shipping gray as a swap: on a
    colour-only frame, "gray" returns nothing and "both" must not.
    """
    for found in ([], ["colour"], ["gray"], ["colour", "gray"]):
        f = set(found)
        c = _Dispatch("colour", f)._run_detector(None)
        b = _Dispatch("both", f)._run_detector(None)
        if c is not None:
            assert b is not None, "both lost a frame colour found: %s" % found


def test_both_finds_the_frames_gray_alone_would():
    for found in ([], ["colour"], ["gray"], ["colour", "gray"]):
        f = set(found)
        g = _Dispatch("gray", f)._run_detector(None)
        b = _Dispatch("both", f)._run_detector(None)
        if g is not None:
            assert b is not None, "both lost a frame gray found: %s" % found


def test_both_fails_only_when_neither_input_works():
    d = _Dispatch("both", set())
    assert d._run_detector(None) is None
    assert d.calls == ["colour", "gray"]
