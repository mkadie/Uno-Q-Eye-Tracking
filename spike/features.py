"""MediaPipe face landmarks -> gaze feature vector.

The feature vector deliberately carries BOTH eye-in-head and head-in-world
information, because a screen-mounted camera needs both to resolve gaze:

  eye-in-head : iris centre position normalised inside the eye socket
  head-in-world: rotation and translation from solvePnP

A near-eye camera would only give you the first, which is exactly why a
chair-mounted gooseneck drifts -- it measures where the eye points relative
to the skull, and has no idea where the skull is pointing.

MediaPipe FaceMesh indices used (refine_landmarks=True gives 478 points):
  468       left iris centre        473       right iris centre
  33, 133   left eye outer/inner    362, 263  right eye inner/outer
  159, 145  left eye upper/lower    386, 374  right eye upper/lower
  1 nose tip, 152 chin, 61/291 mouth corners
"""

import numpy as np

L_IRIS, R_IRIS = 468, 473
L_OUT, L_IN = 33, 133
R_IN, R_OUT = 362, 263
L_UP, L_LO = 159, 145
R_UP, R_LO = 386, 374
NOSE, CHIN = 1, 152
M_L, M_R = 61, 291

FEATURE_NAMES = (
    "l_iris_x", "l_iris_y", "r_iris_x", "r_iris_y",
    "yaw", "pitch", "roll", "t_x", "t_y", "t_z",
)
FEATURE_DIM = len(FEATURE_NAMES)

# Canonical 3D face model in millimetres, ordered to match _PNP_IDX below.
# Approximate anthropometric means; solvePnP tolerates the error because we
# only need pose consistency across frames, not absolute metric truth.

# Logitech C920 at 16:9: 78 deg diagonal -> 70.4 deg horizontal. Used to build
# the pinhole camera matrix for solvePnP. Override per-camera via focal_px if
# you fit real intrinsics with a checkerboard; this is the honest default, and
# it is 1.41x better than f = frame_w.
DEFAULT_HFOV_DEG = 70.42

_PNP_IDX = (NOSE, CHIN, L_OUT, R_OUT, M_L, M_R)
_MODEL_3D = np.array([
    (0.0,    0.0,    0.0),      # nose tip
    (0.0,  -63.6,  -12.5),      # chin
    (-43.3, 32.7,  -26.0),      # left eye outer corner
    (43.3,  32.7,  -26.0),      # right eye outer corner
    (-28.9,-28.9,  -24.1),      # left mouth corner
    (28.9, -28.9,  -24.1),      # right mouth corner
], dtype=np.float64)


def eye_aspect_ratio(lm, up, lo, out, inn):
    """Vertical/horizontal eye extent. Drops toward 0 during a blink."""
    v = np.linalg.norm(lm[up][:2] - lm[lo][:2])
    h = np.linalg.norm(lm[out][:2] - lm[inn][:2])
    return float(v / h) if h > 1e-9 else 0.0


def _normalised_iris(lm, iris, out, inn, up, lo):
    """Iris centre in eye-socket coordinates.

    Normalising by socket width and height makes this invariant to how far
    the user is sitting from the camera, which matters a great deal when the
    camera is on the screen and they lean in and out all day.
    """
    corner_mid = (lm[out][:2] + lm[inn][:2]) * 0.5
    w = np.linalg.norm(lm[out][:2] - lm[inn][:2])
    h = np.linalg.norm(lm[up][:2] - lm[lo][:2])
    if w < 1e-9 or h < 1e-9:
        return 0.0, 0.0
    d = lm[iris][:2] - corner_mid
    return float(d[0] / w), float(d[1] / h)


# 180 degrees about x: the canonical face model faces away from the camera, so
# this is the rotation of a head looking straight at it. Euler angles are taken
# relative to this, which moves pitch off the wrapping singularity -- see the
# comment block in head_pose().
_NOMINAL_T = np.array([[1.0, 0.0, 0.0],
                       [0.0, -1.0, 0.0],
                       [0.0, 0.0, -1.0]], dtype=np.float64).T


def head_pose(lm, frame_w, frame_h, focal_px=None, intr=None):
    """solvePnP head pose. Returns (yaw, pitch, roll in rad, tvec in mm).

    `intr` is a spike.intrinsics.Intrinsics. When neither it nor `focal_px` is
    given, the calibrated file is loaded if present and the assumed FOV used
    (with a warning) if not.
    """
    import cv2
    pts2d = np.array([lm[i][:2] for i in _PNP_IDX], dtype=np.float64)
    pts2d[:, 0] *= frame_w
    pts2d[:, 1] *= frame_h
    # Focal length in pixels. f = frame_w is a common rule of thumb and it
    # encodes a 53 deg horizontal FOV; the C920 at 16:9 is 70.4 deg (78 deg
    # diagonal), so that rule overestimates f by 1.41x and every solvePnP
    # distance with it. Measured effect: a subject at 584 mm reported as
    # 995 mm. The translation vector feeds the calibration feature vector, so
    # the error is not merely cosmetic.
    # CALIBRATED intrinsics when they exist, the assumed FOV (loudly) when
    # they do not. `intr` overrides both, for callers that already hold a set.
    if intr is None and focal_px is None:
        from spike import intrinsics as _intr
        intr = _intr.load(width=frame_w, height=frame_h)
    if intr is not None:
        K, dist = intr.K, intr.dist_coeffs
    else:
        f = focal_px
        K = np.array([[f, 0, frame_w / 2.0],
                      [0, f, frame_h / 2.0],
                      [0, 0, 1.0]], dtype=np.float64)
        dist = np.zeros((5, 1))
    # Real distortion coefficients, not zeros. At 78 deg diagonal the corner
    # distortion is not small, and the eye landmarks are not near the centre.
    ok, rvec, tvec = cv2.solvePnP(
        _MODEL_3D, pts2d, K, dist,
        flags=cv2.SOLVEPNP_ITERATIVE)
    if not ok:
        return 0.0, 0.0, 0.0, np.zeros(3)
    R, _ = cv2.Rodrigues(rvec)

    # MEASURED 2026-09-21: extracting Euler angles from R DIRECTLY puts PITCH
    # exactly on the +/-pi wrapping singularity, because the canonical face
    # model faces AWAY from the camera. A head looking at the lens is
    # therefore ~180 deg rotated, R[2,2] ~ -1, and atan2(R[2,1], R[2,2])
    # returns values that flip between +3.12 and -3.12 on noise. Real
    # calibration data shows it: 14 samples near -pi, 6 near +pi, and a
    # standard deviation of 2.69 rad -- 154 degrees, for a seated head that
    # barely moved.
    #
    # A single flip is a jump of 2*pi in a feature the linear model multiplies
    # by a coefficient; measured, that threw the cursor 230 px.
    #
    # The fix is to measure rotation RELATIVE to the nominal
    # facing-the-camera pose rather than to the model's own frame. Euler
    # angles of the relative rotation sit near zero, far from any
    # singularity, and a small physical tilt becomes a small number.
    R = _NOMINAL_T @ R

    sy = float(np.sqrt(R[0, 0] ** 2 + R[1, 0] ** 2))
    if sy > 1e-6:
        pitch = float(np.arctan2(R[2, 1], R[2, 2]))
        yaw = float(np.arctan2(-R[2, 0], sy))
        roll = float(np.arctan2(R[1, 0], R[0, 0]))
    else:
        pitch = float(np.arctan2(-R[1, 2], R[1, 1]))
        yaw = float(np.arctan2(-R[2, 0], sy))
        roll = 0.0
    return yaw, pitch, roll, tvec.ravel()


def extract(landmarks, frame_w, frame_h, focal_px=None, intr=None):
    """Landmarks (N,3 normalised) -> (feature vector, diagnostics dict)."""
    lm = np.asarray(landmarks, dtype=np.float64)
    if lm.shape[0] < 478:
        raise ValueError(
            "need 478 landmarks (refine_landmarks / iris enabled); got %d"
            % lm.shape[0])

    lx, ly = _normalised_iris(lm, L_IRIS, L_OUT, L_IN, L_UP, L_LO)
    rx, ry = _normalised_iris(lm, R_IRIS, R_IN, R_OUT, R_UP, R_LO)
    yaw, pitch, roll, t = head_pose(lm, frame_w, frame_h, focal_px, intr)

    # t_z is in the hundreds of mm while the angles are order 0.1 rad. Left
    # unscaled, the polynomial fit would be dominated by translation terms and
    # the ridge penalty would fall almost entirely on the eye terms. Scale to
    # put every feature in roughly the same range.
    feat = np.array([lx, ly, rx, ry, yaw, pitch, roll,
                     t[0] / 100.0, t[1] / 100.0, t[2] / 1000.0],
                    dtype=np.float64)

    ear_l = eye_aspect_ratio(lm, L_UP, L_LO, L_OUT, L_IN)
    ear_r = eye_aspect_ratio(lm, R_UP, R_LO, R_IN, R_OUT)
    diag = {
        "ear_left": ear_l,
        "ear_right": ear_r,
        "ear": (ear_l + ear_r) * 0.5,
        "yaw_deg": np.degrees(yaw),
        "pitch_deg": np.degrees(pitch),
        "roll_deg": np.degrees(roll),
        "distance_mm": float(abs(t[2])),
    }
    return feat, diag


def is_blinking(diag, threshold=0.15):
    """Suppress gaze output during blinks -- the iris landmarks are garbage
    while the lid is down, and letting them through makes the cursor jump."""
    return diag["ear"] < threshold
