import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from spike import features as F

W, H = 640, 480


def synth_landmarks(iris_dx=0.0, iris_dy=0.0, eye_open=1.0, yaw=0.0):
    """Minimal synthetic 478-landmark set with controllable iris offset.

    Only the indices features.extract() reads are meaningful; the rest exist
    so the array is the right shape.
    """
    lm = np.zeros((478, 3), dtype=np.float64)
    lm[:, 0] = 0.5
    lm[:, 1] = 0.5

    ew = 0.06                      # eye half-width, normalised
    eh = 0.018 * eye_open
    shift = yaw * 0.1

    # left eye
    lm[F.L_OUT] = (0.35 + shift, 0.42, 0)
    lm[F.L_IN] = (0.35 + 2 * ew + shift, 0.42, 0)
    lm[F.L_UP] = (0.35 + ew + shift, 0.42 - eh, 0)
    lm[F.L_LO] = (0.35 + ew + shift, 0.42 + eh, 0)
    lm[F.L_IRIS] = (0.35 + ew + shift + iris_dx * 2 * ew,
                    0.42 + iris_dy * 2 * eh, 0)
    # right eye
    lm[F.R_IN] = (0.55 + shift, 0.42, 0)
    lm[F.R_OUT] = (0.55 + 2 * ew + shift, 0.42, 0)
    lm[F.R_UP] = (0.55 + ew + shift, 0.42 - eh, 0)
    lm[F.R_LO] = (0.55 + ew + shift, 0.42 + eh, 0)
    lm[F.R_IRIS] = (0.55 + ew + shift + iris_dx * 2 * ew,
                    0.42 + iris_dy * 2 * eh, 0)
    # pnp points
    lm[F.NOSE] = (0.50 + shift, 0.52, 0)
    lm[F.CHIN] = (0.50 + shift, 0.72, 0)
    lm[F.M_L] = (0.44 + shift, 0.64, 0)
    lm[F.M_R] = (0.56 + shift, 0.64, 0)
    return lm


def test_rejects_landmark_sets_without_iris():
    """468 landmarks means refine_landmarks was off. Failing loudly here beats
    silently producing a feature vector with no eye information in it."""
    with pytest.raises(ValueError, match="478"):
        F.extract(np.zeros((468, 3)), W, H)


def test_feature_vector_shape():
    feat, diag = F.extract(synth_landmarks(), W, H)
    assert feat.shape == (F.FEATURE_DIM,)
    assert len(F.FEATURE_NAMES) == F.FEATURE_DIM
    assert np.all(np.isfinite(feat))


def test_iris_offset_is_monotonic_in_x():
    xs = [F.extract(synth_landmarks(iris_dx=d), W, H)[0][0]
          for d in (-0.3, -0.1, 0.1, 0.3)]
    assert all(b > a for a, b in zip(xs, xs[1:]))


def test_iris_offset_is_monotonic_in_y():
    ys = [F.extract(synth_landmarks(iris_dy=d), W, H)[0][1]
          for d in (-0.3, -0.1, 0.1, 0.3)]
    assert all(b > a for a, b in zip(ys, ys[1:]))


def test_centred_iris_gives_near_zero_offset():
    feat, _ = F.extract(synth_landmarks(0.0, 0.0), W, H)
    assert abs(feat[0]) < 1e-9
    assert abs(feat[1]) < 1e-9


def test_iris_normalisation_is_scale_invariant():
    """Same gaze at two apparent face sizes must give the same eye features --
    otherwise the mapping breaks every time the user leans in."""
    a = synth_landmarks(iris_dx=0.25)
    b = a.copy()
    b[:, :2] = 0.5 + (b[:, :2] - 0.5) * 1.6      # scale the whole face
    fa, _ = F.extract(a, W, H)
    fb, _ = F.extract(b, W, H)
    assert abs(fa[0] - fb[0]) < 1e-6
    assert abs(fa[1] - fb[1]) < 1e-6


def test_degenerate_eye_does_not_divide_by_zero():
    lm = synth_landmarks()
    lm[F.L_OUT] = lm[F.L_IN]        # zero-width eye
    lm[F.L_UP] = lm[F.L_LO]
    feat, _ = F.extract(lm, W, H)
    assert np.all(np.isfinite(feat))


def test_blink_detection():
    _, open_d = F.extract(synth_landmarks(eye_open=1.0), W, H)
    _, shut_d = F.extract(synth_landmarks(eye_open=0.05), W, H)
    assert not F.is_blinking(open_d)
    assert F.is_blinking(shut_d)
    assert shut_d["ear"] < open_d["ear"]


def test_head_pose_responds_to_yaw():
    _, a = F.extract(synth_landmarks(yaw=0.0), W, H)
    _, b = F.extract(synth_landmarks(yaw=1.0), W, H)
    assert abs(b["yaw_deg"] - a["yaw_deg"]) > 1.0


def test_distance_is_positive_and_plausible():
    _, d = F.extract(synth_landmarks(), W, H)
    assert 50.0 < d["distance_mm"] < 5000.0
