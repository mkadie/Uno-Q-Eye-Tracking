"""The tag-assisted gaze mapper: a SWAP of head signal, not extra capacity."""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spike import calib


def _rows(n, rng, tag_is_truth):
    """Synthetic calibration rows, 12 columns wide.

    Screen position is generated from the iris plus ONE head signal. Whichever
    signal is not the truth is filled with noise, so a mapper reading the
    wrong columns cannot succeed by accident.
    """
    X = rng.normal(size=(n, 12))
    head = X[:, 10] if tag_is_truth else X[:, 4]
    head2 = X[:, 11] if tag_is_truth else X[:, 5]
    y = np.column_stack([
        900 + 400 * X[:, 0] + 300 * X[:, 2] + 500 * head,
        500 + 250 * X[:, 1] + 200 * X[:, 3] + 350 * head2,
    ])
    return X, y


def _rms(m, X, y):
    p = np.asarray([m.predict(r) for r in X], dtype=float)
    return float(np.sqrt(((p - y) ** 2).sum(axis=1).mean()))


def test_the_swap_does_not_add_capacity():
    """The whole experiment rests on this.

    If the tag mapper read MORE columns than the linear one, a win would be
    explained by capacity rather than by the tag being a better head signal,
    and the measurement would be worthless.
    """
    assert len(calib.TagAssistedMapper.COLS) == len(calib.LinearMapper.COLS)
    assert calib.TagAssistedMapper.COLS[:4] == calib.LinearMapper.COLS[:4]
    # ...and the difference is exactly the head-pose pair.
    assert calib.TagAssistedMapper.COLS[4:] == (calib.LinearMapper.TAG_X,
                                                calib.LinearMapper.TAG_Y)


def test_tag_mapper_wins_when_the_tag_carries_the_truth():
    rng = np.random.default_rng(7)
    X, y = _rows(200, rng, tag_is_truth=True)
    tag = calib.TagAssistedMapper(ridge=0.01).fit(X, y)
    eye = calib.LinearMapper(ridge=0.01).fit(X, y)
    assert _rms(tag, X, y) < _rms(eye, X, y) / 5


def test_linear_mapper_wins_when_the_FACE_MESH_carries_the_truth():
    """The mirror case. Without it, the test above could pass for a mapper
    that simply ignores its head columns."""
    rng = np.random.default_rng(8)
    X, y = _rows(200, rng, tag_is_truth=False)
    tag = calib.TagAssistedMapper(ridge=0.01).fit(X, y)
    eye = calib.LinearMapper(ridge=0.01).fit(X, y)
    assert _rms(eye, X, y) < _rms(tag, X, y) / 5


def test_tag_mapper_needs_the_extra_columns_and_says_so():
    """A 10-column vector has no tag. Better a clear failure than a silent
    prediction from whatever happens to be in memory."""
    rng = np.random.default_rng(9)
    X, y = _rows(40, rng, tag_is_truth=True)
    m = calib.TagAssistedMapper().fit(X, y)
    with pytest.raises(IndexError):
        m.predict(np.zeros(10))


def test_it_is_a_linear_mapper_so_it_inherits_the_standardising():
    """Ridge on RAW columns crushes this fit -- iris features are ~0.01 while
    the screen is ~1900 px. Inheriting LinearMapper is what keeps that fix."""
    assert issubclass(calib.TagAssistedMapper, calib.LinearMapper)
