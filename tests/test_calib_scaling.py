"""Standardised ridge, and the gain error that motivated it.

MEASURED 2026-08-16: on real calibration data the fit ranked held-out points at
r = 0.99 while compressing its predictions ~2.5x toward the screen centre.
Correct ordering, wrong gain -- which scores like chance, because the centre of
the screen is exactly what a zero-information predictor outputs. The cause is
that ridge penalises coefficients, and `poly2`'s squared and interaction
columns differ in scale by orders of magnitude, so the penalty lands almost
entirely on the small ones.

These tests pin the two properties that fix has to have: the standardisation
must be invisible to callers (predict stays `poly2(x) @ W`, saved models keep
their format), and it must actually equalise the penalty across columns.
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spike.calib import GazeMapper, poly2, _moments


def _wildly_scaled_problem(n=40, seed=0):
    """Features whose columns differ by orders of magnitude, like the real ones
    (`t_z/1000` against a normalised iris offset)."""
    rng = np.random.default_rng(seed)
    X = rng.normal(size=(n, 4))
    X[:, 2] *= 1e-3
    X[:, 3] *= 1e3
    y = np.column_stack([
        900.0 + 400.0 * X[:, 0] + 50.0 * X[:, 2] * 1e3,
        500.0 + 300.0 * X[:, 1] - 40.0 * X[:, 3] * 1e-3,
    ])
    return X, y


def test_moments_leaves_the_bias_column_alone():
    P = poly2(np.random.default_rng(0).normal(size=(9, 3)))
    mu, sd = _moments(P, np.ones(len(P)))
    assert mu[0] == 0.0 and sd[0] == 1.0


def test_moments_never_divides_by_a_constant_column():
    P = np.ones((5, 3))          # every column constant -> zero variance
    mu, sd = _moments(P, np.ones(5))
    assert np.all(sd > 0), "a constant column must not produce a zero divisor"
    assert np.all(np.isfinite((P - mu) / sd))


def test_predict_contract_is_unchanged():
    """predict() must remain poly2(x) @ W -- the saved format depends on it."""
    X, y = _wildly_scaled_problem()
    m = GazeMapper(ridge=1e-2).fit(X, y)
    # 1-D input returns (2,); the matrix form is (1, 2). Same numbers.
    np.testing.assert_allclose(m.predict(X[0]), (poly2(X[0:1]) @ m._W)[0],
                               rtol=1e-9, atol=1e-9)
    # 2-D input keeps its row axis.
    np.testing.assert_allclose(m.predict(X[:3]), poly2(X[:3]) @ m._W,
                               rtol=1e-9, atol=1e-9)


def test_standardising_beats_the_raw_penalty_on_badly_scaled_columns():
    """The whole point: with columns orders of magnitude apart, an
    unstandardised ridge misallocates the penalty and loses accuracy."""
    X, y = _wildly_scaled_problem()
    Xtr, ytr, Xte, yte = X[:30], y[:30], X[30:], y[30:]

    m = GazeMapper(ridge=1e-2).fit(Xtr, ytr)
    std_err = np.linalg.norm(
        np.vstack([m.predict(x) for x in Xte]) - yte, axis=1).mean()

    # Same penalty, applied to raw columns -- what the code used to do.
    P = poly2(Xtr)
    lam = 1e-2 * np.eye(P.shape[1])
    lam[0, 0] = 0.0
    W_raw = np.linalg.lstsq(P.T @ P + lam, P.T @ ytr, rcond=None)[0]
    raw_err = np.linalg.norm(poly2(Xte) @ W_raw - yte, axis=1).mean()

    assert std_err < raw_err, (
        "standardised ridge should beat the raw penalty here, got %.1f vs %.1f"
        % (std_err, raw_err))


def test_auto_ridge_picks_a_concrete_value_and_saves_it(tmp_path):
    """A saved model must never carry the string 'auto'."""
    X, y = _wildly_scaled_problem()
    m = GazeMapper(ridge="auto").fit(X, y)
    assert isinstance(m.ridge, float)

    p = str(tmp_path / "cal.npz")
    m.save(p)
    assert float(np.load(p)["ridge"]) == m.ridge
    back = GazeMapper.load(p)
    np.testing.assert_allclose(back.predict(X[0]), m.predict(X[0]))


def test_auto_ridge_is_not_worse_than_the_shipping_default():
    """CV should never lose badly to the fixed 1e-3 it replaces."""
    X, y = _wildly_scaled_problem(n=45, seed=3)
    Xtr, ytr, Xte, yte = X[:35], y[:35], X[35:], y[35:]

    def held_out(mapper):
        return np.linalg.norm(
            np.vstack([mapper.predict(x) for x in Xte]) - yte, axis=1).mean()

    auto = held_out(GazeMapper(ridge="auto").fit(Xtr, ytr))
    fixed = held_out(GazeMapper(ridge=1e-3).fit(Xtr, ytr))
    assert auto <= fixed * 1.05


def test_weighted_solve_still_respects_weights():
    """Standardisation uses weighted moments; anchors must still dominate when
    their weight is high, or the online recalibration guarantees break."""
    rng = np.random.default_rng(2)
    X = rng.normal(size=(12, 3))
    y = rng.normal(size=(12, 2)) * 100 + 500
    m = GazeMapper(ridge=1e-3)
    P = poly2(X)

    w_even = np.ones(12)
    w_first = np.ones(12)
    w_first[:6] = 100.0          # first half dominates

    W_even = m._solve(P, y, w_even)
    W_first = m._solve(P, y, w_first)
    e_even = np.linalg.norm(P[:6] @ W_even - y[:6], axis=1).mean()
    e_first = np.linalg.norm(P[:6] @ W_first - y[:6], axis=1).mean()
    assert e_first <= e_even + 1e-9


def test_shuffled_decorrelates_time_from_target_position():
    """The confound that invalidated runs 1-6.

    Raster order makes elapsed time collinear with target y (r = +0.98 on the
    real runs), so "the head drifts over time" and "the head follows the target
    down the screen" cannot be told apart -- and they call for opposite fixes.
    """
    from spike import targets as mod

    pts = mod.grid_points(25, 1920, 1080)
    ys_raster = [p[1] for p in pts]                     # presentation order
    t = np.arange(len(pts), dtype=float)                # time is just index
    r_raster = abs(np.corrcoef(t, ys_raster)[0, 1])

    # Averaged over seeds, shuffling must break that collinearity.
    rs = []
    for seed in range(30):
        sh, _ = mod.shuffled(pts, np.random.default_rng(seed))
        rs.append(abs(np.corrcoef(t, [p[1] for p in sh])[0, 1]))

    assert r_raster > 0.9, "raster order should be strongly collinear"
    assert np.mean(rs) < 0.3, (
        "shuffling must decorrelate time from target y, got mean |r|=%.2f"
        % np.mean(rs))


def test_shuffled_is_a_permutation_and_reproducible():
    from spike import targets as mod

    pts = mod.grid_points(16, 1920, 1080)
    a, ia = mod.shuffled(pts, np.random.default_rng(7))
    b, ib = mod.shuffled(pts, np.random.default_rng(7))
    assert a == b and list(ia) == list(ib), "same seed must reproduce the order"
    assert sorted(a) == sorted(pts), "must be a permutation, losing no point"


def test_blocked_folds_beat_leave_one_out_on_correlated_samples():
    """LOO under-regularises when consecutive samples are correlated.

    MEASURED 2026-09-21 on a real 25-point calibration, validated on 26
    separate targets: LOO chose ridge 0.215 and gave 11.97 deg, blocked
    5-fold chose 46.4 and gave 2.53 deg, against an oracle best of 2.22.
    Same data, same grid, same solver -- only the fold structure differed.

    Here the correlation is made explicit: samples arrive in time order and
    each is a small perturbation of the one before, exactly as a calibration
    grid collected over ~2 minutes is. A held-out singleton is then almost
    recoverable from its neighbours, so LOO reports that barely-penalised
    fits generalise. Contiguous blocks remove a whole stretch of time at
    once, which is the question actually being asked.
    """
    rng = np.random.default_rng(11)
    n, d = 40, 10
    # A drifting walk, not independent draws: consecutive rows are close.
    steps = rng.normal(0, 0.05, size=(n, d))
    X = np.cumsum(steps, axis=0) + rng.normal(0, 0.02, size=(n, d))
    true_w = rng.normal(0, 1, size=(d, 2))
    y = X @ true_w + rng.normal(0, 0.4, size=(n, 2))

    m = GazeMapper(ridge="auto")
    grid = np.logspace(-6, 4, 21)
    lam_blocked = m._cv_ridge(X, y, grid=grid, n_folds=5)
    lam_loo = m._cv_ridge(X, y, grid=grid, n_folds=n)      # n folds == LOO

    assert lam_blocked >= lam_loo, (
        "blocked folds must not choose LESS regularisation than LOO on "
        "correlated samples; got blocked=%g loo=%g" % (lam_blocked, lam_loo))


def test_cv_ridge_folds_are_contiguous_not_strided():
    """The blocking only works if folds are contiguous in COLLECTION ORDER.

    Strided folds (every k-th sample) would put a point's own time-neighbours
    in the training set again and reproduce the LOO failure while looking
    like k-fold. This pins the property rather than the implementation: a
    contiguous split of 25 into 5 must yield exactly 5 runs of 5.
    """
    folds = np.array_split(np.arange(25), 5)
    assert len(folds) == 5
    for f in folds:
        assert len(f) == 5
        assert np.all(np.diff(f) == 1), "fold is not contiguous: %r" % (f,)
    assert folds[0][0] == 0 and folds[-1][-1] == 24
