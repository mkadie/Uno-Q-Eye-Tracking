"""Menu reader tests. No hardware, no talker checkout needed."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from spike import menu as M

BASE_3x2 = """
# a comment, and a blank line follows

[menu]
name = Base Menu
type = grid
columns = 3
rows = 2

[yes]
label = Yes
text_description = Yes
sound = /button_sounds/yes.mp3
position = 1

[no]
label = No
position = 2

[fooddrink]
label = Food/Drink
submenu = food_fruitjam.menu
position = 6
"""


def test_parses_the_real_3x2_shape():
    m = M.parse(BASE_3x2)
    assert (m.columns, m.rows) == (3, 2)
    assert m.capacity == 6
    assert [p.label for p in m.presses] == ["Yes", "No", "Food/Drink"]


def test_position_is_one_based_row_major():
    m = M.parse(BASE_3x2)
    assert m.at(0, 0).label == "Yes"        # position 1
    assert m.at(1, 0).label == "No"         # position 2
    assert m.at(2, 1).label == "Food/Drink"  # position 6
    assert m.at(2, 0) is None                # position 3 is empty
    assert m.at(0, 1) is None                # position 4 is empty


def test_a_press_without_position_does_not_stack_on_cell_one():
    """Silently stacking every press on cell 1 looks like a rendering bug."""
    m = M.parse("""
[menu]
columns = 3
rows = 2
[a]
label = A
[b]
label = B
""")
    assert [p.position for p in m.presses] == [1, 2]
    assert m.at(0, 0).label == "A"
    assert m.at(1, 0).label == "B"


def test_submenu_and_sound_are_distinguished():
    m = M.parse(BASE_3x2)
    by = {p.label: p for p in m.presses}
    assert by["Food/Drink"].is_submenu
    assert by["Food/Drink"].sound is None
    assert not by["Yes"].is_submenu
    assert by["Yes"].sound.endswith("yes.mp3")


def test_text_description_falls_back_to_label():
    m = M.parse(BASE_3x2)
    by = {p.label: p for p in m.presses}
    assert by["Yes"].text == "Yes"
    assert by["No"].text == "No"          # no text_description given


def test_unknown_keys_are_kept_not_rejected():
    """The real device will grow keys this reader has never heard of, and a
    gaze demo must not be why a teacher's menu file stops loading."""
    m = M.parse("""
[menu]
columns = 3
rows = 2
[x]
label = X
some_future_key = 42
position = 1
""")
    assert m.presses[0].fields["some_future_key"] == "42"


def test_resolve_submenu_path():
    assert M.resolve("food.menu", "/m") == "/m/food.menu"
    assert M.resolve("/abs/food.menu", "/m") == "/abs/food.menu"
    assert M.resolve(None, "/m") is None


@pytest.mark.skipif(not os.path.isdir("/home/trex/claude/coder/talker_v3/menus"),
                    reason="talker_v3 checkout not present")
def test_reads_the_real_fruitjam_menu():
    """The demo must speak the device's actual vocabulary, not an invented one."""
    m = M.load("/home/trex/claude/coder/talker_v3/menus/base_fruitjam.menu")
    assert (m.columns, m.rows) == (3, 2)
    assert len(m.presses) == 6
    assert m.at(0, 0).label == "Yes"
    assert m.at(2, 1).is_submenu


def test_audit_clips_finds_a_silent_submenu(tmp_path):
    """The Food & Drink submenu was silent and nothing said so.

    MEASURED 2026-09-24: its clips live under menus/sounds/ while only
    button_sounds/ had been copied to the board. The cell highlighted, the
    press registered, no sound came out. An AAC board that silently fails to
    speak is worse than one that refuses to start.
    """
    (tmp_path / "base.menu").write_text("""
[menu]
name = Base
columns = 3
rows = 2
[yes]
label = Yes
sound = /button_sounds/yes.mp3
position = 1
[food]
label = Food
submenu = food.menu
position = 2
""")
    (tmp_path / "food.menu").write_text("""
[menu]
name = Food
columns = 3
rows = 2
[water]
label = Water
sound = sounds/food/water.mp3
position = 1
[back]
label = Back
position = 2
""")
    # Only button_sounds resolves -- exactly the board's state that evening.
    def has_clip(p):
        return p.sound if p.sound and "button_sounds" in p.sound else None

    ok, bad = M.audit_clips(str(tmp_path / "base.menu"), has_clip)
    assert ok == ["Yes"]
    labels = {b[1] for b in bad}
    assert "Water" in labels, bad
    assert "Back" in labels, "a press with no sound= line cannot speak either"
    assert any("sounds/food/water.mp3" in str(b[2]) for b in bad)


def test_audit_clips_is_clean_when_everything_resolves(tmp_path):
    (tmp_path / "m.menu").write_text("""
[menu]
name = M
columns = 3
rows = 2
[a]
label = A
sound = /s/a.mp3
position = 1
""")
    ok, bad = M.audit_clips(str(tmp_path / "m.menu"), lambda p: p.sound)
    assert ok == ["A"] and bad == []


def test_audit_clips_survives_a_submenu_loop(tmp_path):
    """A menu that points at itself must not hang the startup check."""
    (tmp_path / "loop.menu").write_text("""
[menu]
name = Loop
columns = 3
rows = 2
[again]
label = Again
submenu = loop.menu
position = 1
""")
    ok, bad = M.audit_clips(str(tmp_path / "loop.menu"), lambda p: None)
    assert ok == [] and bad == []
