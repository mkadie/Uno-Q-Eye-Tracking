import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spike import config


def base(**over):
    cfg = config._merge(config.DEFAULTS, {})
    cfg["device"] = {"name": "left", "usb_label": "Gaze Mouse L"}
    cfg["cursor"] = [
        {"name": "left", "match": "Gaze Mouse L", "glyph": "cursor_l.bmp"},
        {"name": "right", "match": "Gaze Mouse R", "glyph": "cursor_r.bmp"},
    ]
    cfg.update(over)
    return cfg


def test_single_unit_needs_no_cursor_table():
    cfg = config._merge(config.DEFAULTS, {})
    assert config.validate_cursors(cfg) is cfg


def test_valid_two_unit_table_passes():
    config.validate_cursors(base())


def test_accents_assigned_from_validated_palette_in_order():
    cfg = base()
    config.validate_cursors(cfg)
    assert cfg["cursor"][0]["accent"] == config.DEFAULT_ACCENTS[0]
    assert cfg["cursor"][1]["accent"] == config.DEFAULT_ACCENTS[1]


def test_explicit_accent_is_respected():
    cfg = base()
    cfg["cursor"][0]["accent"] = "#123456"
    config.validate_cursors(cfg)
    assert cfg["cursor"][0]["accent"] == "#123456"


@pytest.mark.parametrize("missing", ["name", "match", "glyph"])
def test_missing_required_key_is_rejected(missing):
    cfg = base()
    del cfg["cursor"][1][missing]
    with pytest.raises(ValueError, match=missing):
        config.validate_cursors(cfg)


def test_duplicate_match_string_is_rejected():
    """Identical product strings are the exact bug this table exists to stop:
    the host cannot tell the units apart and cursors swap on reboot."""
    cfg = base()
    cfg["cursor"][1]["match"] = "Gaze Mouse L"
    with pytest.raises(ValueError, match="match"):
        config.validate_cursors(cfg)


def test_duplicate_glyph_is_rejected_even_with_distinct_colours():
    """The accessibility rule, enforced.

    Two cursors sharing a glyph are distinguishable by colour alone, which
    fails for a colourblind user. On an assistive device that is not a
    defensible default, so distinct accents do NOT excuse a duplicate glyph.
    """
    cfg = base()
    cfg["cursor"][1]["glyph"] = "cursor_l.bmp"
    cfg["cursor"][0]["accent"] = "#2a78d6"
    cfg["cursor"][1]["accent"] = "#eb6834"
    with pytest.raises(ValueError, match="colourblind"):
        config.validate_cursors(cfg)


def test_duplicate_name_is_rejected():
    cfg = base()
    cfg["cursor"][1]["name"] = "left"
    with pytest.raises(ValueError, match="name"):
        config.validate_cursors(cfg)


def test_unit_label_absent_from_table_is_rejected():
    """A unit whose label matches no entry enumerates on the host and binds to
    nothing -- it silently has no cursor, which is hard to debug from the
    outside."""
    cfg = base()
    cfg["device"]["usb_label"] = "Gaze Mouse Q"
    with pytest.raises(ValueError, match="matches no"):
        config.validate_cursors(cfg)


def test_single_cursor_entry_skips_the_membership_check():
    cfg = base()
    cfg["cursor"] = [cfg["cursor"][0]]
    cfg["device"]["usb_label"] = "anything"
    config.validate_cursors(cfg)


# -- lookup and codegen -----------------------------------------------

def test_cursor_for_resolves_by_product_string():
    cfg = base()
    config.validate_cursors(cfg)
    assert config.cursor_for(cfg, "Gaze Mouse R")["name"] == "right"
    assert config.cursor_for(cfg, "Unknown Device") is None


def test_settings_toml_renders_this_units_identity():
    out = config.settings_toml(base())
    assert 'GAZE_UNIT_NAME = "left"' in out
    assert 'GAZE_USB_LABEL = "Gaze Mouse L"' in out


def test_shipped_config_is_valid_and_binds_both_cursors():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = config.load(os.path.join(root, "config.toml"))
    assert len(cfg["cursor"]) == 2
    glyphs = {c["glyph"] for c in cfg["cursor"]}
    assert len(glyphs) == 2, "shipped config must not rely on colour alone"
    assert config.cursor_for(cfg, cfg["device"]["usb_label"]) is not None
