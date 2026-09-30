"""Head-pointing maths. No camera, no tag, no hardware."""
import json
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spike import tagtrack


def _affine(feats, A):
    X = np.hstack([np.asarray(feats, float), np.ones((len(feats), 1))])
    return X @ np.asarray(A, float).T


def test_affine_recovers_an_exact_map():
    """Six parameters, five points: the fit should be exact on clean data."""
    A = np.array([[0.004, 0.0002, -1.1], [-0.0003, 0.005, -0.8]])
    feats = [(300.0, 200.0), (250.0, 150.0), (420.0, 160.0),
             (430.0, 330.0), (240.0, 320.0)]
    tgts = _affine(feats, A)
    m = tagtrack.TagMapper()
    rms = m.fit(feats, tgts)
    assert rms < 1e-9
    for f, t in zip(feats, tgts):
        assert np.allclose(m.map(f), t, atol=1e-9)


def test_recenter_moves_the_offset_and_keeps_the_gain():
    """A chair shifts, so the OFFSET drifts. Refitting gain from one point
    would leave the pointer unable to reach the screen edges."""
    A = np.array([[0.004, 0.0, -1.0], [0.0, 0.005, -1.0]])
    m = tagtrack.TagMapper(A.copy())
    before = m.A[:, :2].copy()
    m.recenter((300.0, 240.0))
    assert np.allclose(m.A[:, :2], before)          # gain untouched
    assert np.allclose(m.map((300.0, 240.0)), (0.5, 0.5))


def test_fit_rms_is_screen_fraction_not_pixels():
    """A fixed error must read the same on any display, or two sittings on
    different resolutions cannot be compared."""
    feats = [(0.0, 0.0), (100.0, 0.0), (0.0, 100.0), (100.0, 100.0), (50.0, 50.0)]
    tgts = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0), (0.5, 0.6)]
    rms = tagtrack.TagMapper().fit(feats, tgts)
    assert 0.0 < rms < 0.2


def test_gain_reports_span_and_px_per_screen():
    feats = [(100.0, 100.0), (140.0, 100.0), (100.0, 130.0),
             (140.0, 130.0), (120.0, 115.0)]
    tgts = [(0.15, 0.15), (0.85, 0.15), (0.15, 0.85), (0.85, 0.85), (0.5, 0.5)]
    span, gain = tagtrack.gain_px_per_screen(feats, tgts)
    assert np.allclose(span, (40.0, 30.0))
    # 40 px of tag travel across 0.7 of the screen
    assert np.allclose(gain, (40 / 0.7, 30 / 0.7))


def test_save_and_load_round_trip(tmp_path):
    p = str(tmp_path / "cal.json")
    m = tagtrack.TagMapper(np.array([[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]))
    m.save(p, {"tag_id": 0, "rms": 0.01})
    back = tagtrack.TagMapper.load(p)
    assert back.fitted
    assert np.allclose(back.A, m.A)
    saved = json.load(open(p))
    assert saved["tag_id"] == 0 and "t" in saved


def test_load_of_a_missing_or_junk_file_is_unfitted_not_a_crash(tmp_path):
    """A kiosk must start with no calibration file present."""
    assert not tagtrack.TagMapper.load(str(tmp_path / "nope.json")).fitted
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert not tagtrack.TagMapper.load(str(bad)).fitted


def test_calibration_protocol_constants_match_the_spec():
    """These are a protocol, not preferences -- drifting them silently makes
    two sittings incomparable."""
    assert tagtrack.CAL_POINTS[0] == (0.5, 0.5)        # centre FIRST
    assert len(tagtrack.CAL_POINTS) == 5
    assert {p for pt in tagtrack.CAL_POINTS[1:] for p in pt} == {0.15, 0.85}
    assert tagtrack.MIN_SAMPLES == 8
    assert tagtrack.MAX_JITTER_PX == 3.0
    assert tagtrack.MIN_POINTS == 4
    # Collection is sample-driven so the protocol is the same at 17 fps as
    # at 30, and capped so an occluded tag cannot hang it.
    assert tagtrack.TARGET_SAMPLES >= 2 * tagtrack.MIN_SAMPLES
    assert tagtrack.COLLECT_MAX_S > 0


def test_one_twitch_does_not_fail_an_otherwise_still_point():
    """The measured failure mode: 5 of 5 points failed their first attempt
    at 8 samples. A std squares a lone outlier and lets it decide."""
    still = [(100.0, 200.0)] * 17 + [(140.0, 240.0)]     # 17 still, one twitch
    assert tagtrack.jitter_px(still) <= tagtrack.MAX_JITTER_PX
    assert np.asarray(still).std(axis=0).max() > tagtrack.MAX_JITTER_PX


def test_real_movement_still_fails():
    """Forgiving a twitch must not mean accepting a head that is moving."""
    drifting = [(100.0 + 3.0 * i, 200.0 + 2.0 * i) for i in range(18)]
    assert tagtrack.jitter_px(drifting) > tagtrack.MAX_JITTER_PX


def test_jitter_of_a_perfectly_still_tag_is_zero():
    assert tagtrack.jitter_px([(50.0, 60.0)] * 12) == 0.0


def test_unfitted_mapper_reports_itself():
    assert not tagtrack.TagMapper().fitted


# --- kiosk row geometry -------------------------------------------------

def _menu():
    import importlib.machinery
    import importlib.util
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    loader = importlib.machinery.SourceFileLoader("menubin",
                                                  os.path.join(root, "bin", "menu"))
    spec = importlib.util.spec_from_loader("menubin", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("n", [1, 2, 3, 4, 5, 6])
@pytest.mark.parametrize("H", [1080, 768, 720, 480])
def test_every_menu_row_fits_on_screen(n, H):
    """The row you cannot see is the row nobody can start.

    The heights were three literals repeated in the drawing code and again in
    the hit test, sized for THREE rows. A fourth put the last row at 1.005 x
    H -- off the bottom, with a hit test that still claimed it was there.
    """
    M = _menu()
    top, rh, gap = M.row_geometry(H, n)
    assert rh > 0
    assert top + n * rh + (n - 1) * gap <= H, (n, H, top, rh, gap)


def test_the_head_row_exists_and_asks_for_head_mode():
    M = _menu()
    rows = {name: cmd for name, _, cmd in M.ITEMS}
    head = [c for n, c in rows.items() if "head" in n.lower()]
    assert head, "the kiosk should offer head pointing"
    assert "--mode" in head[0] and "head" in head[0]
    assert "--dwell" in head[0], "gaze-only users cannot click"
