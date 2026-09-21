"""Gaze feature vector -> screen coordinates, with online recalibration.

Model: ridge-regularised polynomial regression, degree 2 with interactions,
fitted separately for screen x and screen y. No sklearn -- it is a heavy
dependency for what is thirty lines of lstsq, and on a 2GB-class board you
care about resident set.

Why polynomial ridge and not a neural net: you have on the order of 9 to 25
calibration points. That is a data regime where a low-capacity model with a
sane prior wins outright, and where a net would simply memorise.

ONLINE RECALIBRATION -- the interesting part
---------------------------------------------
Drift is what makes cheap eye trackers unusable after twenty minutes. The
mapping is fitted once against a head position the user has since left.

A dwell-based tracker cannot cleanly fix this: the dwell IS the selection, so
every "ground truth" sample it could harvest is contaminated by the fact that
looking at the target is what caused the selection. The estimate and the label
are not independent.

A sip-n-puff gives you an independent confirmation channel. When the user
puffs to click, you learn: at time t the gaze estimate was E, and the thing
they meant to hit was at S. That (E, S) pair is clean supervision, generated
for free, continuously, during ordinary use.

So: keep the original calibration points as anchors (weighted, never evicted)
and accumulate click-derived samples in a bounded ring. Refit periodically.
The anchors stop a run of bad samples from walking the fit off a cliff; the
ring lets it track slow drift.
"""

import numpy as np

# Anchor weight relative to an online sample, BEFORE decay.
#
# Anchors were collected under a controlled procedure against a known target,
# so early on they deserve more trust than a handful of click-derived samples
# that might just be noise.
#
# But a fixed anchor weight is wrong, and the test suite caught it: with 16
# anchors at weight 4 against 24 online samples, the anchors outvote the new
# evidence 64:24 and drift correction stalls at about 40% -- the mapping stays
# pinned to a head position the user has already left.
#
# The right way to think about the anchors is as a PRIOR, and a prior should
# be overwhelmed by sufficient evidence. So anchor weight decays as consistent
# online samples accumulate, with a floor so they never vanish entirely --
# that floor is the safety net that stops a run of bad clicks from walking the
# fit off a cliff.
ANCHOR_WEIGHT = 4.0
ANCHOR_HALFLIFE = 24.0   # online samples at which anchor weight roughly halves
ANCHOR_FLOOR = 0.5       # anchors never decay below this


def anchor_weight(n_online):
    """Decaying prior strength. See the discussion above."""
    w = ANCHOR_WEIGHT / (1.0 + float(n_online) / ANCHOR_HALFLIFE)
    return max(w, ANCHOR_FLOOR)


def poly2(X):
    """Degree-2 polynomial features with interactions, plus bias.

    X: (n, d) -> (n, 1 + d + d + d*(d-1)/2)
    """
    X = np.atleast_2d(np.asarray(X, dtype=np.float64))
    n, d = X.shape
    cols = [np.ones((n, 1)), X, X ** 2]
    if d > 1:
        iu = np.triu_indices(d, k=1)
        cols.append(X[:, iu[0]] * X[:, iu[1]])
    return np.hstack(cols)


def _moments(P, w):
    """Weighted mean and sd of each design column. Bias column left alone.

    MEASURED 2026-08-16, and the reason this function exists: ridge penalises
    coefficients, and a column with a small numeric scale needs a large
    coefficient to do the same work -- so an unstandardised penalty falls
    almost entirely on the small columns. In `poly2` output the squared and
    interaction terms are orders of magnitude apart, and the result on real
    calibration data was that predictions were compressed ~2.5x toward the
    screen centre while still ranking held-out points at r = 0.99. Correct
    ordering, wrong gain -- which scores like chance, because the centre of
    the screen IS the chance prediction.
    """
    sw = w.sum()
    mu = (P * w[:, None]).sum(0) / sw
    var = (w[:, None] * (P - mu) ** 2).sum(0) / sw
    sd = np.sqrt(var)
    sd[sd < 1e-12] = 1.0          # a constant column carries no information
    mu[0], sd[0] = 0.0, 1.0       # bias stays a bias
    return mu, sd


class LinearMapper(object):
    """Ridge-regularised LINEAR map on six features. Prefer this to GazeMapper.

    MEASURED 2026-09-21, scored on 26 held-out targets, same sessions, same
    feature vectors:

        calibration points   LinearMapper (7 par)   GazeMapper poly2 (66 par)
                         9         3.49 deg                 8.37 deg
                        25         3.01 deg                 3.27 deg

    Linear wins at EVERY point count tried, including 25 where the degree-2
    model was supposed to have the data to justify itself. Dropping roll, t_x,
    t_y, t_z and every quadratic term costs nothing measurable and buys a model
    that cannot overfit a short grid -- 7 parameters against 66.

    That matters most where it is hardest to get: 9 points plus linear lands
    within half a degree of a 25-point fit, at a third of the sitting. For a
    stranger at a faire, or anyone who cannot hold still for two minutes, that
    is the difference between a usable calibration and none.

    GazeMapper is kept because online recalibration (its ring buffer and
    refit) lives there and has its own tests. This class is deliberately
    minimal: fit, predict, nothing else.
    """

    COLS = (0, 1, 2, 3, 4, 5)      # l/r iris x,y, then yaw, pitch

    def __init__(self, ridge=0.1):
        # MEASURED on real 9-point data with STANDARDISED columns:
        #   0.01 -> predicted span 1507 px against a 1459 px target
        #   0.10 -> 1490 px                                  <- chosen
        #   1.00 -> 1364 px, visibly shrinking toward the centre
        self.ridge = float(ridge)
        self._W = None
        self._mu = None
        self._sd = None

    @property
    def fitted(self):
        return self._W is not None

    def _raw(self, X):
        return np.atleast_2d(np.asarray(X, dtype=np.float64))[:, list(self.COLS)]

    def _design(self, X):
        """STANDARDISED design matrix, and this is not optional.

        The iris features are ~0.01-0.05 in magnitude, so reaching a 1920 px
        screen needs coefficients of order 100,000. Ridge penalises
        coefficients, so on RAW columns even a mild penalty crushes the fit --
        MEASURED at ridge 0.3: training error 108 px and a predicted range of
        27 px against a 243 px target. The cursor barely moved.

        Standardising makes the penalty mean the same thing for every column.
        See _moments() below; this module learned it the same way, twice.
        """
        Z = (self._raw(X) - self._mu) / self._sd
        return np.hstack([np.ones((len(Z), 1)), Z])

    def fit(self, X, y):
        R = self._raw(X)
        self._mu = R.mean(axis=0)
        sd = R.std(axis=0)
        sd[sd < 1e-9] = 1.0            # a constant column carries no signal
        self._sd = sd
        P = self._design(X)
        Y = np.asarray(y, dtype=np.float64)
        lam = self.ridge * np.eye(P.shape[1])
        lam[0, 0] = 0.0                # never penalise the bias
        self._W = np.linalg.lstsq(P.T @ P + lam, P.T @ Y, rcond=None)[0]
        return self

    def predict(self, x):
        if self._W is None:
            raise RuntimeError("LinearMapper.predict() before fit()")
        out = self._design(x) @ self._W
        return out[0] if np.ndim(x) == 1 else out


class GazeMapper:
    """Fit and apply the feature -> screen mapping."""

    def __init__(self, ridge=1e-3, ring_size=256, refit_every=12):
        # ridge="auto" picks the penalty by leave-one-out CV at fit() time and
        # then stores the chosen float, so a saved model is always concrete.
        self.ridge = ridge if ridge == "auto" else float(ridge)
        self.ring_size = int(ring_size)
        self.refit_every = int(refit_every)
        self._W = None            # (p, 2) coefficient matrix
        self._anchors_X = None
        self._anchors_y = None
        self._ring_X = []
        self._ring_y = []
        self._since_refit = 0
        self.n_online = 0

    @property
    def fitted(self):
        return self._W is not None

    # -- fitting ---------------------------------------------------------
    def _solve(self, P, y, w, ridge=None):
        """Weighted ridge on STANDARDISED columns; bias unpenalised.

        Standardising is not cosmetic -- see `_moments`. The transform is
        folded back into the returned coefficients so that `predict` stays a
        plain `poly2(x) @ W` and every saved model keeps the same format.
        """
        lam_val = self.ridge if ridge is None else float(ridge)
        mu, sd = _moments(P, w)
        Z = (P - mu) / sd
        Z[:, 0] = 1.0

        sw = np.sqrt(w)[:, None]
        Zw, yw = Z * sw, y * sw
        lam = lam_val * np.eye(Z.shape[1])
        lam[0, 0] = 0.0
        A = Zw.T @ Zw + lam
        B = Zw.T @ yw
        try:
            C = np.linalg.solve(A, B)
        except np.linalg.LinAlgError:
            C = np.linalg.lstsq(A, B, rcond=None)[0]

        # Undo the standardisation: pred = C0 + sum_j (P_j - mu_j)/sd_j * C_j
        W = C / sd[:, None]
        W[0] = C[0] - (mu / sd) @ C
        return W

    def _cv_ridge(self, X, y, grid=None, n_folds=5):
        """BLOCKED k-fold CV over the penalty. Used when ridge="auto".

        A fixed penalty cannot be right across calibration grids of different
        size and spread -- 9 points and 25 points against 66 parameters are
        very different problems -- and the cost of getting it wrong is the
        gain error above, which is invisible in the training error.

        THE FOLDS ARE CONTIGUOUS IN COLLECTION ORDER, and that is the whole
        point. `X` arrives in presentation order, so consecutive rows are
        seconds apart in time and share a head pose, a blink state and a tear
        film. Leave-one-out leaves those near-duplicates in the training set,
        so a held-out point is predicted partly from itself: CV then
        underestimates generalisation error and systematically chooses too
        little regularisation.

        MEASURED 2026-09-21 on a real 25-point run (validation on 26 separate
        held-out targets, so these numbers are honest):

            LOO           -> ridge 0.215  ->  11.97 deg
            blocked 5-fold-> ridge 46.4   ->   2.53 deg
            oracle best                        2.22 deg

        Same data, same grid, same solver; only the fold structure differs.
        LOO was not slightly off, it was off by four orders of magnitude in
        the penalty and by 9.4 deg in the result -- and it did it while
        reporting a training error of 0.40 deg, which is what overfitting
        looks like from the inside.

        Blocking is the standard remedy for correlated samples and was chosen
        for that reason, not fitted to these runs.
        """
        if grid is None:
            grid = np.logspace(-6, 4, 21)
        P = poly2(X)
        n = P.shape[0]
        if n < 3:
            return float(grid[len(grid) // 2])

        k = int(max(2, min(n_folds, n // 2)))
        folds = np.array_split(np.arange(n), k)

        best, best_err = None, np.inf
        for lam in grid:
            err = 0.0
            for te in folds:
                m = np.ones(n, dtype=bool)
                m[te] = False
                if int(m.sum()) < 3:
                    continue
                W = self._solve(P[m], y[m], np.ones(int(m.sum())), ridge=lam)
                err += float(np.linalg.norm(P[te] @ W - y[te], axis=1).sum())
            if err < best_err:
                best_err, best = err, float(lam)
        return best

    def fit(self, X, y):
        """Initial calibration. X: (n, d) features. y: (n, 2) screen px."""
        X = np.atleast_2d(np.asarray(X, dtype=np.float64))
        y = np.atleast_2d(np.asarray(y, dtype=np.float64))
        if X.shape[0] != y.shape[0]:
            raise ValueError("X and y must have the same number of rows")
        P = poly2(X)
        if X.shape[0] < P.shape[1]:
            # Under-determined. Ridge still yields a solution, but the user
            # should know their calibration grid is too sparse for degree 2.
            pass
        if self.ridge == "auto":
            self.ridge = self._cv_ridge(X, y)
        self._anchors_X, self._anchors_y = X, y
        self._ring_X, self._ring_y = [], []
        self.n_online = 0
        self._W = self._solve(P, y, np.ones(X.shape[0]) * ANCHOR_WEIGHT)
        return self

    def anchor_influence(self):
        """Current anchor weight. Useful for logging how far the online
        samples have been allowed to move the fit."""
        return anchor_weight(len(self._ring_X))

    def predict(self, x):
        if self._W is None:
            raise RuntimeError("GazeMapper is not calibrated yet")
        P = poly2(np.atleast_2d(x))
        out = P @ self._W
        return out[0] if np.ndim(x) == 1 else out

    # -- online ----------------------------------------------------------
    def observe_click(self, feature, target_xy):
        """Record a confirmed click: gaze features + where they actually meant.

        Call this at the moment the breath click fires, with the feature
        vector from the frame the click landed on and the centre of whatever
        UI element was activated. Returns True if a refit happened.
        """
        self._ring_X.append(np.asarray(feature, dtype=np.float64).ravel())
        self._ring_y.append(np.asarray(target_xy, dtype=np.float64).ravel())
        if len(self._ring_X) > self.ring_size:
            self._ring_X.pop(0)
            self._ring_y.pop(0)
        self.n_online += 1
        self._since_refit += 1
        if self._since_refit >= self.refit_every:
            self._refit()
            return True
        return False

    def _refit(self):
        self._since_refit = 0
        if self._anchors_X is None or not self._ring_X:
            return
        X = np.vstack([self._anchors_X, np.vstack(self._ring_X)])
        y = np.vstack([self._anchors_y, np.vstack(self._ring_y)])
        w = np.concatenate([
            np.full(len(self._anchors_X), anchor_weight(len(self._ring_X))),
            np.ones(len(self._ring_X)),
        ])
        self._W = self._solve(poly2(X), y, w)

    # -- persistence -----------------------------------------------------
    # Model keys. Callers may attach diagnostics alongside them but must not
    # shadow them, or load() would silently read someone else's array.
    _RESERVED = ("W", "aX", "ay", "ridge")

    def save(self, path, **extra):
        """Save the model, plus any extra diagnostic arrays.

        `extra` exists because the model alone cannot explain a bad run. On
        2026-08-16 four calibration sittings disagreed with their own
        leave-one-out estimate by 4x, and the cause -- the mapping going stale
        between the calibration and validation blocks -- could only be INFERRED,
        because the validation block's features were never written down. Extra
        keys are ignored by load(), so recording them costs nothing.
        """
        if self._W is None:
            raise RuntimeError("nothing to save")
        clash = sorted(set(extra) & set(self._RESERVED))
        if clash:
            raise ValueError("extra keys would shadow model keys: %s"
                             % ", ".join(clash))
        np.savez(path, W=self._W, aX=self._anchors_X, ay=self._anchors_y,
                 ridge=self.ridge, **extra)

    @classmethod
    def load(cls, path):
        d = np.load(path)
        m = cls(ridge=float(d["ridge"]))
        m._W, m._anchors_X, m._anchors_y = d["W"], d["aX"], d["ay"]
        return m


def angular_error_deg(pred_px, true_px, px_per_mm, viewing_distance_mm):
    """Convert screen-space error to degrees of visual angle.

    Degrees are the only unit in which a gaze accuracy number is comparable
    to anything else. Pixels are meaningless without screen size and distance,
    and "percent of screen" is worse. Commercial remote trackers claim 0.5-1.0
    deg; a good webcam pipeline lands around 1.5-3 deg.
    """
    pred = np.atleast_2d(np.asarray(pred_px, dtype=np.float64))
    true = np.atleast_2d(np.asarray(true_px, dtype=np.float64))
    err_mm = np.linalg.norm(pred - true, axis=1) / float(px_per_mm)
    return np.degrees(np.arctan2(err_mm, float(viewing_distance_mm)))
