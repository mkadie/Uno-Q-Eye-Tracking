"""One Euro filter -- adaptive low-pass for interactive pointing.

Why this and not a moving average: a fixed-window average trades jitter for
lag, and for pointing, lag is the worse problem. The 1e filter raises its
cutoff frequency with signal velocity, so it is heavily smoothed while the
user fixates (where jitter is visible and motion is nil) and barely filtered
during a saccade (where lag is visible and jitter is masked).

Casiez, Roussel & Vogel, CHI 2012.

Tuning, in order:
  1. Set beta = 0 and lower min_cutoff until slow-fixation jitter is acceptable.
  2. Raise beta until fast movement no longer feels laggy.
Do not touch d_cutoff.
"""

import math


class _LowPass:
    __slots__ = ("_y", "_a", "initialised")

    def __init__(self):
        self._y = None
        self.initialised = False

    def __call__(self, x, alpha):
        if not self.initialised:
            self._y = x
            self.initialised = True
        else:
            self._y = alpha * x + (1.0 - alpha) * self._y
        return self._y

    @property
    def last(self):
        return self._y

    def reset(self):
        self._y = None
        self.initialised = False


def _alpha(cutoff, dt):
    tau = 1.0 / (2.0 * math.pi * cutoff)
    return 1.0 / (1.0 + tau / dt)


class OneEuroFilter:
    """Scalar 1e filter.

    min_cutoff: Hz. Lower = smoother at rest, more lag. Start 1.0.
    beta:       velocity coefficient. Higher = more responsive when moving.
    d_cutoff:   Hz, cutoff for the derivative estimate. 1.0 is near-universal.
    """

    def __init__(self, min_cutoff=1.0, beta=0.007, d_cutoff=1.0):
        if min_cutoff <= 0:
            raise ValueError("min_cutoff must be > 0")
        if d_cutoff <= 0:
            raise ValueError("d_cutoff must be > 0")
        if beta < 0:
            raise ValueError("beta must be >= 0")
        self.min_cutoff = float(min_cutoff)
        self.beta = float(beta)
        self.d_cutoff = float(d_cutoff)
        self._x = _LowPass()
        self._dx = _LowPass()
        self._t_prev = None

    def reset(self):
        self._x.reset()
        self._dx.reset()
        self._t_prev = None

    def __call__(self, x, t):
        """Filter sample x observed at monotonic timestamp t (seconds)."""
        x = float(x)
        if self._t_prev is None:
            self._t_prev = t
            self._dx(0.0, 1.0)
            return self._x(x, 1.0)

        dt = t - self._t_prev
        # A dropped frame or a stalled camera must not produce a divide-by-zero
        # or a spike in the derivative estimate. Clamp to a sane frame interval.
        if dt <= 1e-6:
            dt = 1e-3
        elif dt > 0.5:
            # Long gap: the velocity estimate is meaningless. Restart cleanly
            # rather than letting a huge dx blow the cutoff wide open.
            self._t_prev = t
            self._dx(0.0, 1.0)
            return self._x(x, 1.0)
        self._t_prev = t

        dx = (x - self._x.last) / dt
        edx = self._dx(dx, _alpha(self.d_cutoff, dt))
        cutoff = self.min_cutoff + self.beta * abs(edx)
        return self._x(x, _alpha(cutoff, dt))


class OneEuroFilter2D:
    """Two independent 1e filters sharing tuning. Screen-space convenience."""

    def __init__(self, min_cutoff=1.0, beta=0.007, d_cutoff=1.0):
        self.fx = OneEuroFilter(min_cutoff, beta, d_cutoff)
        self.fy = OneEuroFilter(min_cutoff, beta, d_cutoff)

    def reset(self):
        self.fx.reset()
        self.fy.reset()

    def __call__(self, x, y, t):
        return self.fx(x, t), self.fy(y, t)
