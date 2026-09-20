"""ArUco board pose for the printed marker rig.

The rig is the ground-truth instrument, not the product. Its job is to give a
pose you trust so you can judge how well the cheap methods -- glasses rims,
bare face mesh -- agree with it on real images in real light.

WHY A BOARD AND NOT FOUR SINGLE MARKERS
---------------------------------------
solvePnP over all sixteen corners jointly is far more stable than averaging
four independent per-marker poses. A single 30 mm marker has only 30 mm of
internal baseline; the board has 156 x 120 mm of corner spread, and rotation
accuracy scales with baseline. Per-marker pose also reintroduces the planar
two-fold ambiguity that the board's spread removes.

WHY FOUR MARKERS IN A RECTANGLE
--------------------------------
The glasses rims cannot resolve the SIGN of pitch, because both rim centres
lie ON the axis pitch rotates about. The board's markers are not collinear --
90 mm of vertical spread between the top and bottom rows -- so pitch is
directly observable with no hint and no gate. That is the whole reason the
rig exists in this form.
"""

import math

import numpy as np

try:
    import cv2
except ImportError:                                   # pragma: no cover
    cv2 = None


def make_detector(dictionary_id):
    """OpenCV moved ArUco to an object API in 4.7 and removed the free
    function in 4.13. The UNO Q's OpenCV may be either, so bind at runtime
    rather than assuming."""
    d = cv2.aruco.getPredefinedDictionary(dictionary_id)
    if hasattr(cv2.aruco, "ArucoDetector"):
        params = cv2.aruco.DetectorParameters()
        # Sub-pixel corner refinement is where board accuracy comes from.
        # Without it you are localising corners to whole pixels and throwing
        # away most of the precision the rig was built to provide.
        params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
        det = cv2.aruco.ArucoDetector(d, params)
        return lambda img: det.detectMarkers(img)
    params = cv2.aruco.DetectorParameters_create()
    params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    return lambda img: cv2.aruco.detectMarkers(img, d, parameters=params)


class MarkerBoard(object):
    """Pose of the printed rig from one frame.

    obj_points : (N, 4, 3) marker corners in mm, OpenCV convention
                 (+x right, +y DOWN, +z away from camera)
    ids        : marker ids matching obj_points row order
    """

    def __init__(self, obj_points, ids, dictionary_id, K, dist=None,
                 min_markers=3):
        self.obj = np.asarray(obj_points, dtype=np.float32)
        self.ids = [int(i) for i in ids]
        self.K = np.asarray(K, dtype=np.float64)
        self.dist = (np.zeros(5) if dist is None
                     else np.asarray(dist, dtype=np.float64))
        self.min_markers = int(min_markers)
        self._detect = make_detector(dictionary_id)
        self._last_rvec = None
        self._last_tvec = None

    def detect(self, gray):
        """Returns a pose dict, or None if the rig is not visible enough."""
        corners, ids, _ = self._detect(gray)
        if ids is None:
            return None
        seen = {int(i): c[0] for c, i in zip(corners, ids.ravel())}
        objp, imgp, used = [], [], []
        for row, mid in zip(self.obj, self.ids):
            if mid in seen:
                objp.extend(row)
                imgp.extend(seen[mid])
                used.append(mid)
        if len(used) < self.min_markers:
            return None

        objp = np.array(objp, dtype=np.float32)
        imgp = np.array(imgp, dtype=np.float32)

        # Seed from the previous frame when we have one: IPPE converges
        # faster and more stably on a planar target than a cold iterative
        # solve, and head pose barely moves between frames.
        guess = self._last_rvec is not None
        ok, rvec, tvec = cv2.solvePnP(
            objp, imgp, self.K, self.dist,
            self._last_rvec.copy() if guess else None,
            self._last_tvec.copy() if guess else None,
            useExtrinsicGuess=guess,
            flags=cv2.SOLVEPNP_ITERATIVE)
        if not ok:
            return None
        self._last_rvec, self._last_tvec = rvec.copy(), tvec.copy()

        R, _ = cv2.Rodrigues(rvec)
        sy = math.sqrt(R[0, 0] ** 2 + R[1, 0] ** 2)
        if sy > 1e-6:
            pitch = math.atan2(R[2, 1], R[2, 2])
            yaw = math.atan2(-R[2, 0], sy)
            roll = math.atan2(R[1, 0], R[0, 0])
        else:
            pitch = math.atan2(-R[1, 2], R[1, 1])
            yaw = math.atan2(-R[2, 0], sy)
            roll = 0.0

        proj, _ = cv2.projectPoints(objp, rvec, tvec, self.K, self.dist)
        reproj = float(np.mean(np.linalg.norm(
            proj.reshape(-1, 2) - imgp, axis=1)))

        t = tvec.ravel()
        return {
            "t_mm": t,
            "distance_mm": float(t[2]),
            "yaw_deg": math.degrees(yaw),
            "pitch_deg": math.degrees(pitch),
            "roll_deg": math.degrees(roll),
            "R": R,
            "n_markers": len(used),
            "ids_seen": used,
            # Reproject the solution and measure how far it lands from the
            # detected corners. This is the single most useful diagnostic:
            # above about 1 px, either the rig geometry is wrong or the
            # camera intrinsics are.
            "reproj_px": reproj,
        }

    def reset(self):
        self._last_rvec = self._last_tvec = None


def load_intrinsics(path):
    """Read camera_intrinsics.json from calibrate_camera.py."""
    import json
    with open(path) as f:
        d = json.load(f)
    K = np.array([[d["fx"], 0, d["cx"]],
                  [0, d["fy"], d["cy"]],
                  [0, 0, 1]], dtype=np.float64)
    return K, np.array(d["dist_coeffs"], dtype=np.float64), d
