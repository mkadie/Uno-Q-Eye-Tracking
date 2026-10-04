"""solvePnP pose from one tag. The sign traps get asserted, not assumed."""
import math
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2
from spike import calib, tagtrack

K = np.array([[1000.0, 0.0, 640.0],
              [0.0, 1000.0, 360.0],
              [0.0, 0.0, 1.0]])
ZERO = np.zeros((5, 1))


def project(yaw_deg, pitch_deg, roll_deg=0.0, tz=600.0, size=tagtrack.TAG_MM):
    """Render a tag at a known pose, so the solver can be scored against truth."""
    objp = tagtrack.tag_object_points(size)
    ry = math.radians(yaw_deg); rp = math.radians(pitch_deg); rr = math.radians(roll_deg)
    Ry = np.array([[math.cos(ry), 0, math.sin(ry)], [0, 1, 0], [-math.sin(ry), 0, math.cos(ry)]])
    Rx = np.array([[1, 0, 0], [0, math.cos(rp), -math.sin(rp)], [0, math.sin(rp), math.cos(rp)]])
    Rz = np.array([[math.cos(rr), -math.sin(rr), 0], [math.sin(rr), math.cos(rr), 0], [0, 0, 1]])
    R = Rz @ Rx @ Ry
    rvec, _ = cv2.Rodrigues(R)
    tvec = np.array([[0.0], [0.0], [float(tz)]])
    img, _ = cv2.projectPoints(objp, rvec, tvec, K, ZERO)
    return img.reshape(4, 2)


def test_recovers_a_known_yaw():
    for truth in (-25.0, -10.0, 0.0, 10.0, 25.0):
        got = tagtrack.pose_from_corners(project(truth, 0.0), K, ZERO)
        assert got is not None
        assert abs(got[0] - truth) < 1.0, (truth, got[0])


def test_recovers_a_known_pitch_WITH_THE_RIGHT_SIGN():
    """The repo's single easiest error: y-down vs y-up inverts pitch and
    still looks plausible. Assert the sign, not just the magnitude."""
    for truth in (-20.0, -8.0, 8.0, 20.0):
        got = tagtrack.pose_from_corners(project(0.0, truth), K, ZERO)
        assert got is not None
        assert abs(got[1] - truth) < 1.0, (truth, got[1])
        assert math.copysign(1, got[1]) == math.copysign(1, truth)


def test_recovers_distance():
    for tz in (450.0, 600.0, 700.0):
        got = tagtrack.pose_from_corners(project(0.0, 0.0, tz=tz), K, ZERO)
        assert abs(got[3] - tz) < 5.0, (tz, got[3])


def test_reprojection_is_tiny_on_clean_corners():
    got = tagtrack.pose_from_corners(project(12.0, -7.0), K, ZERO)
    assert got[4] < 0.5, got[4]


def test_object_points_match_what_IPPE_SQUARE_DEMANDS():
    """IPPE_SQUARE ignores the order you pass and assumes OpenCV's canonical
    square: TL, TR, BR, BL with +y UP. MEASURED: y-down points gave 2608 px
    of reprojection error -- complete garbage, not a subtle bias."""
    o = tagtrack.tag_object_points(27.0)
    assert o.shape == (4, 3)
    assert np.allclose(o[:, 2], 0.0)                 # coplanar
    assert o[0][0] < 0 and o[0][1] > 0               # top-left,  +y is UP
    assert o[1][0] > 0 and o[1][1] > 0               # top-right
    assert o[2][0] > 0 and o[2][1] < 0               # bottom-right
    assert o[3][0] < 0 and o[3][1] < 0               # bottom-left


def test_pose_mapper_is_a_swap_of_ANGLES_not_a_position():
    """The whole correction. TagAssistedMapper read a centroid; this reads
    angles, which is the same kind of quantity the face mesh supplies."""
    assert len(calib.TagPoseMapper.COLS) == len(calib.LinearMapper.COLS)
    assert calib.TagPoseMapper.COLS[:4] == calib.LinearMapper.COLS[:4]
    assert calib.TagPoseMapper.COLS[4:] == (calib.LinearMapper.TAG_YAW,
                                            calib.LinearMapper.TAG_PITCH)
    # and it must NOT be the refuted position pair
    assert calib.TagPoseMapper.COLS[4:] != (calib.LinearMapper.TAG_X,
                                            calib.LinearMapper.TAG_Y)


def test_the_two_tag_mappers_read_different_columns():
    assert calib.TagPoseMapper.COLS != calib.TagAssistedMapper.COLS


def test_a_nan_pose_never_escapes():
    """MEASURED 2026-10-04: at yaw -25 deg and 600 mm -- the normal working
    distance, where the tag is ~41 px -- IPPE_SQUARE returned ok=True with a
    nan rvec. solvePnP reporting success is not evidence of a pose. A nan
    reaching the gaze mapper puts the cursor anywhere, silently."""
    for truth in (-25.0, -24.0, -26.0, 25.0):
        got = tagtrack.pose_from_corners(project(truth, 0.0), K, ZERO)
        assert got is not None, truth          # the fallback solver caught it
        assert all(math.isfinite(v) for v in got), (truth, got)
        assert abs(got[0] - truth) < 1.5, (truth, got[0])


def test_garbage_corners_return_None_not_a_confident_pose():
    degenerate = np.array([[100.0, 100.0]] * 4)   # all four corners identical
    assert tagtrack.pose_from_corners(degenerate, K, ZERO) is None
