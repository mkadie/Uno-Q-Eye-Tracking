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
