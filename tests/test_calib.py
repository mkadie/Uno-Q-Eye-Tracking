import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spike.calib import (ANCHOR_FLOOR, ANCHOR_WEIGHT, GazeMapper,
                         anchor_weight, angular_error_deg, poly2)

rng = np.random.default_rng(7)

W, H = 1920, 1080
PPMM = W / 527.0
DIST = 600.0


def synth_mapping(feat, drift=(0.0, 0.0)):
    """A plausible nonlinear feature -> screen map, for testing the fit."""
    lx, ly = feat[..., 0], feat[..., 1]
    x = 960 + 5200 * lx + 900 * lx * ly + 400 * lx ** 2 + drift[0]
    y = 540 + 5600 * ly - 700 * ly ** 2 + drift[1]
    return np.stack([x, y], axis=-1)


def make_grid(n=9, noise=0.0):
    side = int(np.sqrt(n))
    a = np.linspace(-0.09, 0.09, side)
    F = np.array([[x, y] for y in a for x in a])
    feats = np.zeros((len(F), 10))
    feats[:, 0] = F[:, 0]
    feats[:, 1] = F[:, 1]
    feats[:, 2] = F[:, 0] * 0.98
    feats[:, 3] = F[:, 1] * 1.02
    if noise:
        feats[:, :4] += rng.normal(0, noise, (len(F), 4))
    return feats, synth_mapping(feats)


def test_poly2_shape_and_bias():
    X = rng.normal(size=(5, 4))
    P = poly2(X)
    assert P.shape == (5, 1 + 4 + 4 + 6)
    assert np.allclose(P[:, 0], 1.0)


def test_fit_recovers_clean_mapping():
    X, y = make_grid(16)
    m = GazeMapper(ridge=1e-6).fit(X, y)
    pred = np.vstack([m.predict(x) for x in X])
    err = angular_error_deg(pred, y, PPMM, DIST)
    assert err.mean() < 0.25, "clean fit should be near-exact, got %.3f deg" % err.mean()


def test_predict_before_fit_raises():
    with pytest.raises(RuntimeError):
        GazeMapper().predict(np.zeros(10))


def test_fit_rejects_mismatched_rows():
    with pytest.raises(ValueError):
        GazeMapper().fit(np.zeros((4, 10)), np.zeros((3, 2)))


def test_ridge_limits_blowup_on_noisy_sparse_grid():
    """With 9 points and 10 features, degree-2 is under-determined. Ridge is
    what stops the fit from exploding; verify it actually does."""
    X, y = make_grid(9, noise=0.004)
    loose = GazeMapper(ridge=1e-9).fit(X, y)
    tight = GazeMapper(ridge=1e-2).fit(X, y)
    probe = np.zeros((1, 10))
    probe[0, :4] = [0.12, 0.12, 0.118, 0.122]   # outside the grid
    assert (np.linalg.norm(tight.predict(probe[0]))
            < np.linalg.norm(loose.predict(probe[0])) * 3)


# -- the online recalibration claim -----------------------------------

def test_online_recalibration_corrects_drift():
    """The core claim of this project, tested.

    Fit a mapping, then simulate the user's head shifting so the true mapping
    acquires an offset. Feed in click-derived (features, true target) pairs of
    exactly the kind a puff-click generates, and confirm the error actually
    comes down. If this fails, the headline idea does not work.
    """
    X, y = make_grid(16)
    m = GazeMapper(ridge=1e-4, refit_every=8).fit(X, y)

    DRIFT = (140.0, -90.0)
    probes = rng.uniform(-0.08, 0.08, (40, 2))
    feats = np.zeros((40, 10))
    feats[:, 0], feats[:, 1] = probes[:, 0], probes[:, 1]
    feats[:, 2], feats[:, 3] = probes[:, 0] * 0.98, probes[:, 1] * 1.02
    truth = synth_mapping(feats, drift=DRIFT)

    before = angular_error_deg(
        np.vstack([m.predict(f) for f in feats]), truth, PPMM, DIST).mean()

    for f, t in zip(feats[:24], truth[:24]):
        m.observe_click(f, t)

    after = angular_error_deg(
        np.vstack([m.predict(f) for f in feats[24:]]),
        truth[24:], PPMM, DIST).mean()

    assert after < before * 0.5, (
        "online recalibration failed to halve drift error: %.2f -> %.2f deg"
        % (before, after))
    # Observed on the reference run: 4.35 deg -> 1.94 deg after 24 clicks.


def test_anchors_resist_a_burst_of_bad_samples():
    """Anchors exist so a run of mislabelled clicks cannot walk the fit off a
    cliff. Poison the ring and confirm the mapping stays broadly sane."""
    X, y = make_grid(16)
    m = GazeMapper(ridge=1e-4, refit_every=4).fit(X, y)
    good = angular_error_deg(
        np.vstack([m.predict(x) for x in X]), y, PPMM, DIST).mean()

    for _ in range(20):
        f = np.zeros(10)
        f[:4] = rng.normal(0, 0.05, 4)
        m.observe_click(f, [rng.uniform(0, W), rng.uniform(0, H)])

    after = angular_error_deg(
        np.vstack([m.predict(x) for x in X]), y, PPMM, DIST).mean()
    assert after < good + 6.0, (
        "garbage samples moved the anchored fit by %.1f deg" % (after - good))


def test_anchor_weight_decays_monotonically_to_a_floor():
    """Anchors are a prior, and a prior must be overwhelmable by evidence.

    A fixed anchor weight stalls drift correction at roughly 40% -- the
    original version of this code did exactly that, and the drift test above
    is what exposed it.
    """
    ws = [anchor_weight(n) for n in (0, 8, 16, 24, 48, 96, 200, 1000)]
    assert ws[0] == ANCHOR_WEIGHT
    assert all(b <= a for a, b in zip(ws, ws[1:])), "must be non-increasing"
    assert ws[-1] == ANCHOR_FLOOR, "must not decay to zero -- floor is the "\
                                   "safety net against a run of bad clicks"
    assert anchor_weight(24) < ANCHOR_WEIGHT / 1.9


def test_drift_correction_improves_with_more_clicks():
    """More evidence must mean less error, monotonically. If this ever goes
    non-monotonic, the decay schedule is fighting the fit."""
    X, y = make_grid(16)
    m = GazeMapper(ridge=1e-4, refit_every=8).fit(X, y)
    probes = rng.uniform(-0.08, 0.08, (48, 2))
    feats = np.zeros((48, 10))
    feats[:, 0], feats[:, 1] = probes[:, 0], probes[:, 1]
    feats[:, 2], feats[:, 3] = probes[:, 0] * 0.98, probes[:, 1] * 1.02
    truth = synth_mapping(feats, drift=(140.0, -90.0))

    hold_f, hold_t = feats[32:], truth[32:]
    errs = []
    for i in range(32):
        m.observe_click(feats[i], truth[i])
        if (i + 1) % 8 == 0:
            errs.append(angular_error_deg(
                np.vstack([m.predict(f) for f in hold_f]),
                hold_t, PPMM, DIST).mean())
    assert all(b < a for a, b in zip(errs, errs[1:])), \
        "error did not fall monotonically: %s" % [round(e, 2) for e in errs]


def test_ring_is_bounded():
    X, y = make_grid(9)
    m = GazeMapper(ring_size=10, refit_every=1000).fit(X, y)
    for i in range(50):
        m.observe_click(np.zeros(10), [i, i])
    assert len(m._ring_X) == 10
    assert m.n_online == 50


# -- angular error -----------------------------------------------------

def test_angular_error_matches_hand_calculation():
    # 10.47mm at 600mm subtends 1 degree.
    mm = np.tan(np.radians(1.0)) * DIST
    err = angular_error_deg([[0, 0]], [[mm * PPMM, 0]], PPMM, DIST)
    assert abs(err[0] - 1.0) < 1e-6


def test_angular_error_zero_for_perfect_prediction():
    assert angular_error_deg([[100, 200]], [[100, 200]], PPMM, DIST)[0] == 0.0


def test_save_load_roundtrip(tmp_path):
    X, y = make_grid(16)
    m = GazeMapper(ridge=1e-4).fit(X, y)
    p = str(tmp_path / "c.npz")
    m.save(p)
    m2 = GazeMapper.load(p)
    assert np.allclose(m.predict(X[3]), m2.predict(X[3]))
