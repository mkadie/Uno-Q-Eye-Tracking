"""The exit chip: geometry only, which is the part that can silently break."""
import importlib.machinery
import importlib.util
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from spike import menu as M


def _load_talker():
    loader = importlib.machinery.SourceFileLoader(
        "talkerbin", os.path.join(ROOT, "bin", "talker"))
    spec = importlib.util.spec_from_loader("talkerbin", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


T = _load_talker()

BOARD = """[menu]
name = Home
columns = 3
rows = 2

[a]
label = A
sound = a.wav
position = 1
"""


@pytest.fixture
def board(tmp_path):
    p = tmp_path / "home.menu"
    p.write_text(BOARD)
    return M.load(str(p))


SIZES = [(1920, 1080), (1280, 720), (1024, 768), (640, 480)]


@pytest.mark.parametrize("w,h", SIZES)
def test_exit_chip_steals_no_cell(board, w, h):
    """The chip must cost the board no word, at every screen size.

    It sits in the title strip, where cell_at returns None. That is an
    invariant between two numbers written in different functions -- the
    strip height and the chip's height plus padding -- and if it ever
    breaks, the symptom is a word that speaks *and* exits.
    """
    x0, y0, x1, y1 = T.exit_rect(w, h)
    for x in (x0, (x0 + x1) // 2, x1):
        for y in (y0, (y0 + y1) // 2, y1):
            assert T.cell_at(x, y, board, w, h) is None, (x, y, w, h)


@pytest.mark.parametrize("w,h", SIZES)
def test_exit_chip_is_on_screen(w, h):
    x0, y0, x1, y1 = T.exit_rect(w, h)
    assert 0 <= x0 < x1 <= w
    assert 0 <= y0 < y1 <= h


@pytest.mark.parametrize("w,h", SIZES)
def test_in_exit_is_true_only_in_the_corner(w, h):
    x0, y0, x1, y1 = T.exit_rect(w, h)
    assert T.in_exit((x0 + x1) // 2, (y0 + y1) // 2, w, h)
    assert not T.in_exit(w // 2, h // 2, w, h)
    assert not T.in_exit(x0 - 5, (y0 + y1) // 2, w, h)
    assert not T.in_exit((x0 + x1) // 2, y1 + 5, w, h)


def test_the_chip_stays_smaller_than_the_gaze_error():
    """Small IS the guard.

    Gaze p95 is ~164 px (GATE 1c, 3.27 deg at 504 mm). A chip comparable to
    that, jammed in the corner, is out of reach of a visitor's wandering
    gaze and trivial for the operator's mouse. Growing it to look friendlier
    would quietly hand the exit to the person in the chair.
    """
    assert T.EXIT_W <= 200 and T.EXIT_H <= 70
