"""Head pointing from a printed ArUco tag on the glasses.

WHY THIS EXISTS. Gaze does not degrade as the head turns, it stops: measured
over 2594 faire throws, the valid rate holds near 71% out to 15 degrees of
head rotation and falls to **5% beyond 20** (pitch the same, 72% -> 4%). Past
that the camera is looking at one eye and there is nothing to work with. A tag
on the glasses does not share that failure -- at 20 degrees of yaw it is still
square enough to the camera to localise, and it goes on producing a usable
pointer where the iris has already gone.

This is therefore not a better eye tracker. It is the input for the head a
visitor actually had, and the second half of the same answer.

WHAT IT IS NOT: a pose estimate. The tag's centre is a 2-D image point and
that is all this module uses. Nothing here solves for orientation, because
nothing here needs to -- the affine fit maps tag pixels to screen and absorbs
the whole geometry. `marker_board.py` is where pose lives, and it needs four
markers spanning 156 x 120 mm to do it honestly; one 27 mm tag cannot.

Conventions match the rest of the repo: features are image pixels, screen
positions are NORMALISED 0..1 so a calibration survives a resolution change.
"""

import json
import math
import os
import time

import numpy as np

try:                                                  # pragma: no cover
    import cv2
except ImportError:                                   # pragma: no cover
    cv2 = None

from . import marker_board

# DICT_4X4_50. 4.5 mm cells -> 27 mm marker on a 33.75 mm tile.
#
# DEFAULT_TAG_ID IS 2, NOT 0. head_track.md specifies id 0 and says ids 0-3
# were printed, but the tag physically on this rig's glasses is **id 2** --
# MEASURED 2026-09-30, after a tagcheck run reported 0% detection and sent
# us looking at lighting and distance. It was neither: the detector was
# asked for the wrong marker and correctly found nothing. A spec's default
# loses to the object in the room.
DICT = 0 if cv2 is None else cv2.aruco.DICT_4X4_50
DEFAULT_TAG_ID = 2

# MEASURED 2026-09-30 at 1280x720, exposure 156: side 44.4 px (p5 39.3,
# p95 46.6) = 7.4 px per cell at the working distance, 98-100% detection.
# DO NOT DROP TO 960x540 to chase frame rate: it buys 2.2 fps (19.0 -> 22.2
# camera alone) and costs a THIRD of the detections (100% -> 67%), because
# the tag falls to about 5.5 px per cell and the corners stop resolving.
MIN_USABLE_SIDE_PX = 24.0
DEFAULT_CAL = os.path.expanduser("~/.headtrack_cal.json")

# Calibration protocol. Centre FIRST: it is the only point a user with a
# limited range of motion is certain to reach, so a run that fails everything
# else still tells you the tag was found and roughly where.
CAL_POINTS = [(0.5, 0.5), (0.15, 0.15), (0.85, 0.15), (0.85, 0.85), (0.15, 0.85)]
SETTLE_S = 0.5

# COLLECT BY SAMPLE COUNT, NOT BY CLOCK. head_track.md asks for a 0.7 s
# window, which assumes 30 fps and yields ~21 samples. This board delivers
# 17, so 0.7 s yielded exactly 8 -- MIN_SAMPLES, the bare floor -- and
# MEASURED 2026-09-30 every one of the five points failed its first attempt
# with `unstable (8 samples)`. A median of 8 is a thin estimate and a single
# twitch dominates the spread. Counting samples makes the protocol behave the
# same whatever frame rate the board happens to manage.
TARGET_SAMPLES = 18
COLLECT_MAX_S = 2.5     # cap, so an occluded tag cannot hang a calibration
MIN_SAMPLES = 8
MAX_JITTER_PX = 3.0
RETRIES = 2
MIN_POINTS = 4          # 3 determine an affine fit; 4 leaves one to argue with


def jitter_px(samples):
    """Robust per-axis spread, in pixels, of a held tag.

    MAD scaled to be comparable with a standard deviation (x1.4826 for
    Gaussian data), rather than the standard deviation itself. The failure
    being fixed is a SINGLE twitch failing an otherwise still point: std
    squares that outlier and lets it decide, where MAD does not. It is no
    more forgiving of genuine movement -- a head that is actually drifting
    moves the median too.
    """
    a = np.asarray(samples, dtype=np.float64)
    med = np.median(a, axis=0)
    return float(np.max(np.median(np.abs(a - med), axis=0)) * 1.4826)


class TagTracker(object):
    """Find one tag per frame, cheaply.

    Full-frame ArUco detection costs roughly 17 ms on x86 and several times
    that on an A53, which this board cannot spare while the talker is also
    drawing. After a hit, the next search is a crop of +/-2.5 tag widths
    around the last centre -- the tag cannot leave that window between frames
    at any speed a neck produces.

    Three consecutive ROI misses before paying for a full frame: a blink of
    occlusion (a hand, a turn past the camera) should not cost the expensive
    path every time, and holding the pointer still for two frames is both
    cheaper and less alarming than having it jump.
    """

    def __init__(self, tag_id=DEFAULT_TAG_ID, roi_scale=2.5, miss_budget=3):
        self._detect = marker_board.make_detector(DICT)
        self.tag_id = int(tag_id)
        self.roi_scale = float(roi_scale)
        self.miss_budget = int(miss_budget)
        self.roi = None
        self.misses = 0
        self.last_corners = None
        self.full_frames = 0      # how often the cheap path failed us
        self.roi_frames = 0

    def find(self, gray):
        """(centre_xy, side_px) or None. `gray` is single channel."""
        if self.roi is not None:
            x0, y0, x1, y1 = self.roi
            hit = self._scan(gray[y0:y1, x0:x1], x0, y0)
            if hit is not None:
                self.roi_frames += 1
                return hit
            self.misses += 1
            if self.misses < self.miss_budget:
                return None
            self.roi = None
        self.full_frames += 1
        return self._scan(gray, 0, 0)

    def _scan(self, img, ox, oy):
        if img.size == 0:
            return None
        corners, ids, _ = self._detect(img)
        if ids is None:
            return None
        for c, i in zip(corners, np.ravel(ids)):
            if int(i) != self.tag_id:
                continue
            c = c.reshape(4, 2).astype(np.float64) + (ox, oy)
            centre = c.mean(axis=0)
            # Diagonal / sqrt(2) rather than an edge: it averages all four
            # corners, so one corner smeared by motion moves it less.
            side = float(np.linalg.norm(c[0] - c[2]) / 1.4142135623730951)
            m = int(max(8.0, side * self.roi_scale))
            h, w = img.shape[:2]
            self.roi = (max(0, int(centre[0]) - m), max(0, int(centre[1]) - m),
                        int(centre[0]) + m, int(centre[1]) + m)
            self.misses = 0
            self.last_corners = c
            return centre, side
        return None


# The tag is 27 mm of marker inside a 33.75 mm tile (head_track.md). solvePnP
# needs the MARKER, not the tile -- the quiet zone is not part of what the
# detector returns.
TAG_MM = 27.0

# A solve worse than this is not a pose, it is a failure wearing one. The
# measured garbage case reprojected at 2608 px; a good solve on a real tag
# is well under a pixel.
MAX_REPROJ_PX = 5.0


def tag_object_points(size_mm=TAG_MM):
    """The marker's four corners in its own frame, millimetres.

    Order is cv2.aruco's corner order -- top-left, top-right, bottom-right,
    bottom-left -- with **+y UP**, which is the marker's own frame and NOT
    the y-down camera convention `rig_geometry.py` uses. Those are different
    frames and both are correct in their place.

    **SOLVEPNP_IPPE_SQUARE REQUIRES EXACTLY THIS ORDERING AND SIGN.** It
    does not solve the points you hand it in the order you hand them; it
    assumes OpenCV's canonical square. MEASURED 2026-10-04: passing y-down
    points produced a pose with **2608 px of reprojection error** -- not a
    subtle bias, complete garbage, and it would have been easy to blame the
    tag, the lighting or the intrinsics instead of the argument. The
    reprojection figure is returned by `pose_from_corners` precisely so this
    class of error announces itself.
    """
    h = float(size_mm) / 2.0
    return np.array([[-h, +h, 0.0],
                     [+h, +h, 0.0],
                     [+h, -h, 0.0],
                     [-h, -h, 0.0]], dtype=np.float64)


def pose_from_corners(corners, K, dist=None, size_mm=TAG_MM):
    """6-DoF of one tag: (yaw_deg, pitch_deg, roll_deg, distance_mm, reproj_px).

    THIS IS THE POINT OF THE WHOLE MODULE, and the thing the first version
    threw away. A tag CENTROID is a position: it cannot distinguish a head
    that translated from one that rotated, and MEASURED 2026-10-04 that
    ambiguity made the gaze mapping worse, not better -- 42% of frames with
    the cursor sweeping the whole screen.

    A pose is an ANGLE, the same kind of quantity the face mesh's yaw/pitch
    are, and the gaze model wants angles. One marker of known size plus
    calibrated intrinsics is enough: four coplanar points determine it.

    `dist` must be the REAL distortion coefficients, never zeros -- at 78
    degrees diagonal the corner distortion is not small and a tag on the
    brow is nowhere near the optical centre.

    Euler extraction is copied from `marker_board.pose()` deliberately, so
    a tag pose and a board pose can be compared without an convention
    argument in between.
    """
    imgp = np.asarray(corners, dtype=np.float64).reshape(4, 2)
    objp = tag_object_points(size_mm)
    d = np.zeros((5, 1)) if dist is None else np.asarray(dist, dtype=np.float64)
    # IPPE_SQUARE is the planar-square solver and is both faster and more
    # stable here than the iterative one, which can settle into the mirrored
    # pose that any planar target admits.
    Kf = np.asarray(K, dtype=np.float64)
    # TRY IPPE_SQUARE, THEN VERIFY, THEN FALL BACK. MEASURED 2026-10-04:
    # at yaw -25 deg and 600 mm -- where the tag is only ~41 px across,
    # i.e. the normal working regime -- IPPE_SQUARE returned **ok=True with
    # a nan rvec**. It reports success and hands back garbage. A nan that
    # reaches the gaze mapper puts the cursor anywhere at all, silently, so
    # every solve is checked for finiteness and for a sane reprojection
    # before it is believed.
    best = None
    for flag in (cv2.SOLVEPNP_IPPE_SQUARE, cv2.SOLVEPNP_ITERATIVE):
        try:
            ok, rvec, tvec = cv2.solvePnP(objp, imgp, Kf, d, flags=flag)
        except cv2.error:
            continue
        if not ok or not (np.all(np.isfinite(rvec)) and np.all(np.isfinite(tvec))):
            continue
        proj, _ = cv2.projectPoints(objp, rvec, tvec, Kf, d)
        err = float(np.mean(np.linalg.norm(proj.reshape(-1, 2) - imgp, axis=1)))
        if not math.isfinite(err) or err > MAX_REPROJ_PX:
            continue
        best = (rvec, tvec, err)
        break
    if best is None:
        return None
    rvec, tvec, reproj = best
    R, _ = cv2.Rodrigues(rvec)
    if not np.all(np.isfinite(R)):
        return None
    sy = math.sqrt(R[0, 0] ** 2 + R[1, 0] ** 2)
    if sy > 1e-6:
        pitch = math.atan2(R[2, 1], R[2, 2])
        yaw = math.atan2(-R[2, 0], sy)
        roll = math.atan2(R[1, 0], R[0, 0])
    else:
        pitch = math.atan2(-R[1, 2], R[1, 1])
        yaw = math.atan2(-R[2, 0], sy)
        roll = 0.0
    t = tvec.ravel()
    out = (math.degrees(yaw), math.degrees(pitch), math.degrees(roll),
           float(t[2]), reproj)
    # Last gate: nothing non-finite leaves this function, ever.
    return out if all(math.isfinite(v) for v in out) else None


class TagMapper(object):
    """Affine tag-pixels -> normalised screen. screen = A @ [u, v, 1].

    Affine on purpose, and NOT the ridge-regularised polynomial the gaze path
    uses. Head-to-screen really is near-linear -- the tag translates across
    the image as the neck rotates -- so six parameters describe it and five
    points over-determine them. The gaze model needs its regularisation
    because 66 parameters over 9 points is how you fit noise; there is no
    such danger here, and adding curvature would only let the fit chase it.
    """

    def __init__(self, A=None):
        self.A = None if A is None else np.asarray(A, dtype=np.float64)

    @property
    def fitted(self):
        return self.A is not None

    def fit(self, feats, targets):
        """Least squares. Returns RMS error in SCREEN FRACTION, not pixels.

        Screen fraction so the number means the same thing on any display --
        0.02 is 2% of the screen whether that is 1920 or 1024 wide.
        """
        feats = np.asarray(feats, dtype=np.float64)
        targets = np.asarray(targets, dtype=np.float64)
        X = np.hstack([feats, np.ones((len(feats), 1))])
        sol, _, _, _ = np.linalg.lstsq(X, targets, rcond=None)
        self.A = sol.T
        resid = X @ sol - targets
        return float(np.sqrt((resid ** 2).sum(axis=1).mean()))

    def map(self, uv):
        u, v = float(uv[0]), float(uv[1])
        return self.A @ np.array([u, v, 1.0])

    def recenter(self, uv, target=(0.5, 0.5)):
        """One-point drift fix that keeps the gain.

        Only the translation column moves. Refitting from a single point
        would throw away the scale the 5-point run measured and leave the
        pointer unable to reach the edges -- the offset is the part that
        drifts when a chair shifts, not the gain.
        """
        self.A[:, 2] += np.asarray(target, dtype=np.float64) - self.map(uv)

    def save(self, path, meta=None):
        d = {"A": self.A.tolist(), "t": time.time()}
        d.update(meta or {})
        with open(path, "w") as fh:
            json.dump(d, fh, indent=1)

    @classmethod
    def load(cls, path):
        try:
            with open(path) as fh:
                return cls(json.load(fh)["A"])
        except Exception:
            return cls()


def gain_px_per_screen(feats, targets):
    """How much tag travel the user produced per unit of screen.

    Reported because a SMALL span is not a failure -- it means high gain for
    someone with little range of motion, which is the point of calibrating
    per person. It is also the number that says whether a run is trustworthy:
    a span of a few pixels is a fit through noise however good its RMS looks.
    """
    feats = np.asarray(feats, dtype=np.float64)
    targets = np.asarray(targets, dtype=np.float64)
    span_px = np.ptp(feats, axis=0)
    span_scr = np.ptp(targets, axis=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        g = np.where(span_scr > 0, span_px / span_scr, np.nan)
    return span_px, g
