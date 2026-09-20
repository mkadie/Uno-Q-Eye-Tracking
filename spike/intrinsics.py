"""Camera intrinsics: the real ones if they exist, a loud warning if not.

Every distance this project reports is `f * size / pixels`, so an error in `f`
is a proportional error in ALL of it -- rim distance, marker distance, and the
`t_z` feature that feeds the gaze mapping. A real C920 differs from its
spec-sheet 70.4 degrees by a few percent, and at 78 degrees diagonal the corner
distortion is not small.

Until `camera_intrinsics.json` exists, everything falls back to that assumed
FOV, which is a systematic error LARGER than the difference between any two
fiducial designs anyone might argue about. So the fallback warns, once, and
says what to run. Do not silence it -- fix the cause:

    python3 tools/calibrate_camera.py capture     # SPACE keeps a frame
    python3 tools/calibrate_camera.py solve       # -> camera_intrinsics.json
"""

import json
import math
import os

import numpy as np

DEFAULT_HFOV_DEG = 70.4          # C920 spec sheet. A guess, not a measurement.

_warned = set()


class Intrinsics(object):
    """fx, fy, cx, cy and distortion, with the resolution they were measured at.

    All four are in PIXELS and all four scale linearly with image width, so a
    set measured at 1920 is wrong by 1.5x if you infer at 1280. `for_size()`
    does that rescale; forgetting it is a silent proportional error in every
    distance, which is the same class of bug as the assumed FOV this file
    exists to remove.
    """

    def __init__(self, fx, fy, cx, cy, dist_coeffs=None, width=None,
                 height=None, rms=None, calibrated=True):
        self.fx = float(fx)
        self.fy = float(fy)
        self.cx = float(cx)
        self.cy = float(cy)
        self.dist_coeffs = (np.zeros((5, 1)) if dist_coeffs is None
                            else np.asarray(dist_coeffs,
                                            dtype=np.float64).reshape(-1, 1))
        self.width = width
        self.height = height
        self.rms = rms
        self.calibrated = bool(calibrated)

    @property
    def K(self):
        return np.array([[self.fx, 0.0, self.cx],
                         [0.0, self.fy, self.cy],
                         [0.0, 0.0, 1.0]], dtype=np.float64)

    def for_size(self, width, height):
        """Rescale to a different image size. See the class docstring."""
        if not self.width or width == self.width:
            return self
        k = float(width) / float(self.width)
        return Intrinsics(self.fx * k, self.fy * k, self.cx * k, self.cy * k,
                          self.dist_coeffs, width, height, self.rms,
                          self.calibrated)

    @property
    def fx_fy_agree(self):
        """Square pixels. If these differ by more than 2% the calibration
        capture did not tilt enough to separate focal length from distance."""
        return abs(self.fx - self.fy) / max(self.fx, self.fy) <= 0.02

    def __repr__(self):
        return ("Intrinsics(fx=%.1f, fy=%.1f, cx=%.1f, cy=%.1f, %dx%s, "
                "rms=%s, calibrated=%s)"
                % (self.fx, self.fy, self.cx, self.cy, self.width or 0,
                   self.height, self.rms, self.calibrated))


def assumed(width, height, hfov_deg=DEFAULT_HFOV_DEG):
    """Fallback intrinsics from a spec-sheet FOV. NOT a measurement."""
    f = (width / 2.0) / math.tan(math.radians(hfov_deg) / 2.0)
    return Intrinsics(f, f, width / 2.0, height / 2.0, None, width, height,
                      None, calibrated=False)


def load(path=None, width=None, height=None, hfov_deg=DEFAULT_HFOV_DEG,
         warn=True):
    """Real intrinsics, or the assumed ones with a loud warning.

    `width`/`height` are the size you are about to infer at; the result is
    already rescaled to them.
    """
    path = path or os.environ.get("GAZE_INTRINSICS", "camera_intrinsics.json")
    if os.path.exists(path):
        with open(path) as f:
            d = json.load(f)
        # tools/calibrate_camera.py writes image_width / image_height /
        # rms_reproj_px. Accept both spellings: if `width` came back None the
        # for_size() rescale would silently do nothing, which is exactly the
        # silent proportional error this module exists to prevent.
        w = d.get("width", d.get("image_width"))
        h = d.get("height", d.get("image_height"))
        rms = d.get("rms", d.get("rms_reproj_px"))
        if w is None:
            raise ValueError(
                "%s has no image width -- cannot rescale intrinsics safely. "
                "Keys present: %s" % (path, sorted(d)))
        it = Intrinsics(d["fx"], d["fy"], d["cx"], d["cy"],
                        d.get("dist_coeffs"), w, h, rms, calibrated=True)
        if width:
            it = it.for_size(width, height)
        return it

    if warn and path not in _warned:
        _warned.add(path)
        print("!! %s not found -- falling back to an ASSUMED %.1f deg FOV."
              % (path, hfov_deg))
        print("!! Every distance below is proportionally wrong by however far")
        print("!! this camera differs from its spec sheet. To fix:")
        print("!!     python3 tools/calibrate_camera.py capture")
        print("!!     python3 tools/calibrate_camera.py solve")
    return assumed(width or 1280, height or 720, hfov_deg)
