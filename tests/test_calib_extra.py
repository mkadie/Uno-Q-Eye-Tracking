"""GazeMapper.save(**extra) -- diagnostics travel with the model.

Why this exists: on 2026-08-16 four calibration sittings disagreed with their
own leave-one-out estimate by 4x. The cause -- the mapping going stale between
the calibration and validation blocks -- could only be INFERRED, because the
validation block's feature vectors were never written to the .npz. A number
that decides the project's direction should be measured, not inferred, so
bin/calibrate now records vX/vy and per-point timestamps alongside the model.

These tests pin the contract that makes that safe: extra keys round-trip, they
cannot shadow the model, and load() ignores them.
"""

import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spike.calib import GazeMapper
from spike.features import FEATURE_DIM


def _fitted(seed=0):
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(12, FEATURE_DIM))
    y = rng.normal(size=(12, 2)) * 100 + 500
    return GazeMapper(ridge=1e-3).fit(X, y), X, y


def test_extra_arrays_round_trip(tmp_path):
    m, _, _ = _fitted()
    p = str(tmp_path / "cal.npz")
    vX = np.arange(6 * FEATURE_DIM, dtype=np.float64).reshape(6, FEATURE_DIM)
    vy = np.arange(12, dtype=np.float64).reshape(6, 2)

    m.save(p, vX=vX, vy=vy, t_cal=np.linspace(0, 60, 12),
           t_val=np.linspace(90, 110, 6))

    d = np.load(p)
    assert set(("W", "aX", "ay", "ridge", "vX", "vy", "t_cal", "t_val")) <= set(d)
    np.testing.assert_allclose(d["vX"], vX)
    np.testing.assert_allclose(d["vy"], vy)
    assert d["t_val"][0] > d["t_cal"][-1]      # validation comes after


def test_load_ignores_extra_and_still_predicts(tmp_path):
    """Extra keys must not disturb the model that load() reconstructs."""
    m, X, _ = _fitted()
    p = str(tmp_path / "cal.npz")
    m.save(p, vX=np.zeros((3, FEATURE_DIM)), vy=np.zeros((3, 2)),
           t_cal=np.zeros(12), t_val=np.zeros(3))

    back = GazeMapper.load(p)
    np.testing.assert_allclose(back.predict(X[0]), m.predict(X[0]))


def test_extra_cannot_shadow_model_keys(tmp_path):
    """A caller must not be able to overwrite W/aX/ay/ridge by accident."""
    m, _, _ = _fitted()
    p = str(tmp_path / "cal.npz")
    for bad in ("W", "aX", "ay", "ridge"):
        with pytest.raises(ValueError) as e:
            m.save(p, **{bad: np.zeros(3)})
        assert bad in str(e.value)


def test_save_still_works_with_no_extra(tmp_path):
    m, X, _ = _fitted()
    p = str(tmp_path / "cal.npz")
    m.save(p)
    back = GazeMapper.load(p)
    np.testing.assert_allclose(back.predict(X[0]), m.predict(X[0]))


def test_empty_validation_block_is_representable(tmp_path):
    """`q` during validation leaves no points; the file must still be valid."""
    m, _, _ = _fitted()
    p = str(tmp_path / "cal.npz")
    m.save(p, vX=np.zeros((0, FEATURE_DIM)), vy=np.zeros((0, 2)),
           t_cal=np.zeros(12), t_val=np.zeros(0))

    d = np.load(p)
    assert d["vX"].shape == (0, FEATURE_DIM)
    assert GazeMapper.load(p).fitted


def test_drift_metric_separates_shifted_from_stationary():
    """The shift/sd metric bin/calibrate reports must flag a moved block.

    Same computation as the report: |mean(val) - mean(cal)| / sd(cal).
    """
    rng = np.random.default_rng(1)
    cal = rng.normal(size=(25, FEATURE_DIM))

    same = rng.normal(size=(6, FEATURE_DIM))
    shifted = same.copy()
    shifted[:, 8] += 3.0 * cal[:, 8].std()      # t_y moves 3 sd

    def shift_sd(A, B, i):
        sd = A[:, i].std()
        return abs(B[:, i].mean() - A[:, i].mean()) / sd if sd > 1e-12 else 0.0

    assert shift_sd(cal, same, 8) < 1.0         # stationary -> not flagged
    assert shift_sd(cal, shifted, 8) >= 1.0     # drifted    -> flagged
