import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spike.oneeuro import OneEuroFilter, OneEuroFilter2D

rng = np.random.default_rng(3)


def test_first_sample_passes_through():
    f = OneEuroFilter()
    assert f(42.0, 0.0) == 42.0


def test_rejects_bad_params():
    for kw in ({"min_cutoff": 0}, {"d_cutoff": 0}, {"beta": -1}):
        with pytest.raises(ValueError):
            OneEuroFilter(**kw)


def test_reduces_jitter_while_stationary():
    """The fixation case: signal is constant, noise is not. Filter should
    remove most of the noise."""
    f = OneEuroFilter(min_cutoff=0.5, beta=0.0)
    raw, out = [], []
    for i in range(400):
        x = 100.0 + rng.normal(0, 3.0)
        raw.append(x)
        out.append(f(x, i / 60.0))
    settled = slice(100, None)
    assert np.std(out[settled]) < np.std(raw[settled]) * 0.35


def test_converges_to_a_constant():
    f = OneEuroFilter(min_cutoff=1.0, beta=0.007)
    for i in range(600):
        y = f(50.0, i / 60.0)
    assert abs(y - 50.0) < 0.01


def test_beta_reduces_lag_on_fast_motion():
    """The saccade case: higher beta must track a ramp more closely. This is
    the whole reason to use 1e rather than a moving average."""
    def lag(beta):
        f = OneEuroFilter(min_cutoff=0.5, beta=beta)
        err = []
        for i in range(200):
            t = i / 60.0
            truth = 400.0 * t
            err.append(abs(f(truth, t) - truth))
        return np.mean(err[60:])
    assert lag(1.0) < lag(0.0) * 0.6


def test_survives_a_dropped_frame_gap():
    """A stalled camera must not produce a spike or a divide-by-zero."""
    f = OneEuroFilter()
    for i in range(30):
        f(10.0, i / 60.0)
    y = f(10.0, 30 / 60.0 + 3.0)     # 3 second gap
    assert np.isfinite(y)
    assert abs(y - 10.0) < 1e-6


def test_survives_duplicate_timestamps():
    f = OneEuroFilter()
    f(1.0, 5.0)
    for _ in range(10):
        y = f(2.0, 5.0)              # identical timestamps
    assert np.isfinite(y)


def test_reset_clears_state():
    f = OneEuroFilter()
    for i in range(50):
        f(999.0, i / 60.0)
    f.reset()
    assert f(7.0, 0.0) == 7.0


def test_2d_axes_are_independent():
    f = OneEuroFilter2D(min_cutoff=1.0, beta=0.0)
    for i in range(200):
        x, y = f(100.0, 900.0, i / 60.0)
    assert abs(x - 100.0) < 0.05
    assert abs(y - 900.0) < 0.05


def test_no_overshoot_on_step():
    """Overshoot on a step would show up as the cursor sailing past a target
    and coming back, which reads as unresponsive even though it is fast."""
    f = OneEuroFilter(min_cutoff=1.0, beta=0.01)
    for i in range(60):
        f(0.0, i / 60.0)
    out = [f(100.0, (60 + i) / 60.0) for i in range(120)]
    assert max(out) <= 100.0 + 1e-6
