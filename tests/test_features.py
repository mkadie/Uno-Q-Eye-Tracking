import math
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


def _project_at(pitch_deg=0.0, yaw_deg=0.0, roll_deg=0.0, z=600.0):
    """Landmarks of the canonical model posed at a known angle."""
    import cv2
    from spike import features as F
    obj = F._MODEL_3D.astype(np.float64)
    rp, ry, rr = (math.radians(a) for a in (pitch_deg, yaw_deg, roll_deg))
    Rx = np.array([[1, 0, 0], [0, math.cos(rp), -math.sin(rp)],
                   [0, math.sin(rp), math.cos(rp)]])
    Ry = np.array([[math.cos(ry), 0, math.sin(ry)], [0, 1, 0],
                   [-math.sin(ry), 0, math.cos(ry)]])
    Rz = np.array([[math.cos(rr), -math.sin(rr), 0],
                   [math.sin(rr), math.cos(rr), 0], [0, 0, 1]])
    Rn = np.array([[1., 0, 0], [0, -1., 0], [0, 0, -1.]])
    R = Rn @ (Rz @ Ry @ Rx)
    K = np.array([[910., 0, 640.], [0, 910., 360.], [0, 0, 1.]])
    pts, _ = cv2.projectPoints(obj, cv2.Rodrigues(R)[0],
                               np.array([[0.], [0.], [z]]), K, np.zeros(5))
    return obj, pts.reshape(-1, 2), K


def _solve_angles(obj, pts, K):
    import cv2
    from spike import features as F
    ok, rvec, _ = cv2.solvePnP(obj, pts.astype(np.float64), K, np.zeros(5),
                               flags=cv2.SOLVEPNP_ITERATIVE)
    assert ok
    R, _ = cv2.Rodrigues(rvec)
    R = F._NOMINAL_T @ R
    sy = math.sqrt(R[0, 0] ** 2 + R[1, 0] ** 2)
    return (math.degrees(math.atan2(-R[2, 0], sy)),      # yaw
            math.degrees(math.atan2(R[2, 1], R[2, 2])),  # pitch
            math.degrees(math.atan2(R[1, 0], R[0, 0])))  # roll


def test_pitch_is_not_on_the_wrapping_singularity():
    """Pitch must be near ZERO for a head facing the camera, not near +/-pi.

    MEASURED 2026-09-21 on real calibration data, before this was fixed: 14
    samples near -pi, 6 near +pi, standard deviation 2.69 rad -- 154 degrees,
    for a seated head that barely moved. The canonical face model faces AWAY
    from the camera, so a head looking at the lens is ~180 deg rotated,
    R[2,2] ~ -1, and atan2(R[2,1], R[2,2]) flips sign on noise.

    A single flip is a jump of 2*pi in a feature the linear gaze mapping
    multiplies by a coefficient; measured, it threw the cursor 230 px.
    """
    yaw, pitch, roll = _solve_angles(*_project_at(pitch_deg=0.0))
    assert abs(pitch) < 1.0, "pitch %.1f deg -- back on the singularity" % pitch
    assert abs(yaw) < 1.0
    assert abs(roll) < 1.0


@pytest.mark.parametrize("true_pitch", [-20.0, -10.0, 10.0, 20.0])
def test_pitch_recovers_and_stays_continuous(true_pitch):
    """A real tilt must come back as that tilt, with the right sign."""
    yaw, pitch, roll = _solve_angles(*_project_at(pitch_deg=true_pitch))
    assert abs(pitch - true_pitch) < 1.0, (true_pitch, pitch)
    assert abs(yaw) < 1.0 and abs(roll) < 1.0


def test_pitch_has_no_jump_across_level():
    """Sweeping through level must not produce a discontinuity.

    This is the property that actually matters: the failure was not a wrong
    value, it was a 2*pi STEP between two nearly identical poses.
    """
    vals = [_solve_angles(*_project_at(pitch_deg=p))[1]
            for p in (-2.0, -1.0, 0.0, 1.0, 2.0)]
    steps = [abs(b - a) for a, b in zip(vals, vals[1:])]
    assert max(steps) < 3.0, "discontinuity in pitch: %r" % (vals,)
