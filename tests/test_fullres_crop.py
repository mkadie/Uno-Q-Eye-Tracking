"""Full-res ROI crop: detect small, crop big, return coordinates unchanged.

MEASURED 2026-08-16: iris radius is 8.3 px at 1280x720 against 13.2 px at
1920x1080, and Gate 1c's vertical gaze signal is nearly absent (r_y = 0.22) --
which is what too-few iris pixels looks like. Both models have FIXED input
sizes (128 detector, 256 landmark), so filling the landmark crop from a
full-resolution frame costs no inference time.

The risk in this change is silent: a wrong scale factor still yields 478
landmarks in a face-like arrangement, just mis-placed -- exactly the failure
mode `bin/facecheck`'s geometry assertions exist to catch. These tests pin the
coordinate contract without hardware, using the pure geometry helpers.
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

cv2 = __import__("cv2")

from spike.backends.litert_backend import LiteRTBackend


class _Geom(LiteRTBackend):
    """Just the geometry helpers -- no interpreters, no model files."""

    def __init__(self, lm_size=256):
        self.lm_size = lm_size


def _round_trip(src, centre, side, angle, k):
    """Crop with the scale applied, then map a crop point back to `rgb` space.

    Mirrors exactly what detect() does: crop from `src` at centre*k / side*k,
    then divide the inverse-mapped point by k.
    """
    g = _Geom()
    crop, M = g._crop_from(src, (centre[0] * k, centre[1] * k), side * k, angle)
    Minv = np.linalg.inv(np.vstack([M, [0, 0, 1]]))

    def back(pt):
        v = Minv @ np.array([pt[0], pt[1], 1.0])
        return v[:2] / k

    return crop, back


def test_scale_k_leaves_coordinates_unchanged():
    """The whole contract: cropping from a 2x frame must return the SAME
    coordinates in detection space, or every downstream feature shifts."""
    small = np.zeros((360, 640, 3), np.uint8)
    big = np.zeros((720, 1280, 3), np.uint8)

    centre, side, angle = (320.0, 180.0), 200.0, 0.0

    _, back1 = _round_trip(small, centre, side, angle, 1.0)
    _, back2 = _round_trip(big, centre, side, angle, 2.0)

    for pt in [(128.0, 128.0), (0.0, 0.0), (255.0, 60.0), (10.0, 200.0)]:
        np.testing.assert_allclose(back1(pt), back2(pt), rtol=1e-9, atol=1e-6)


def test_scale_k_holds_under_rotation():
    """Roll is applied inside the crop; the scale must not interact with it."""
    small = np.zeros((360, 640, 3), np.uint8)
    big = np.zeros((1080, 1920, 3), np.uint8)
    centre, side = (300.0, 200.0), 180.0

    for angle in (-25.0, -5.0, 12.5, 40.0):
        _, b1 = _round_trip(small, centre, side, angle, 1.0)
        _, b3 = _round_trip(big, centre, side, angle, 3.0)
        for pt in [(30.0, 200.0), (128.0, 128.0), (240.0, 15.0)]:
            np.testing.assert_allclose(b1(pt), b3(pt), rtol=1e-9, atol=1e-6)


def test_crop_is_always_the_landmark_input_size():
    """Whatever the source resolution, the model input shape is fixed."""
    g = _Geom()
    for src in (np.zeros((360, 640, 3), np.uint8),
                np.zeros((1080, 1920, 3), np.uint8)):
        crop, _ = g._crop_from(src, (300.0, 200.0), 150.0, 10.0)
        assert crop.shape == (g.lm_size, g.lm_size, 3)


def test_full_res_crop_actually_carries_more_detail():
    """The point of the change: the crop must resolve structure that the
    downscaled path cannot. Uses a fine grating, which is exactly the kind of
    high-frequency detail an iris edge is made of."""
    big = np.zeros((720, 1280, 3), np.uint8)
    big[:, ::4] = 255                      # 4 px period in full-res pixels
    small = cv2.resize(big, (640, 360), interpolation=cv2.INTER_AREA)

    g = _Geom()
    centre, side = (320.0, 180.0), 200.0
    crop_small, _ = g._crop_from(small, centre, side, 0.0)
    crop_full, _ = g._crop_from(big, (centre[0] * 2, centre[1] * 2),
                                side * 2, 0.0)

    # Variance of the Laplacian -- the same sharpness metric bin/facecheck uses.
    def sharp(img):
        return cv2.Laplacian(cv2.cvtColor(img, cv2.COLOR_RGB2GRAY),
                             cv2.CV_64F).var()

    assert sharp(crop_full) > sharp(crop_small), (
        "full-res crop should retain more high-frequency detail: %.1f vs %.1f"
        % (sharp(crop_full), sharp(crop_small)))


def test_k_of_one_is_the_old_behaviour_exactly():
    """No `full` supplied must be byte-identical to before the change."""
    src = np.random.default_rng(0).integers(0, 255, (360, 640, 3), dtype=np.uint8)
    g = _Geom()
    a, Ma = g._crop_from(src, (300.0, 200.0), 150.0, 8.0)
    b, Mb = g._crop_from(src, (300.0 * 1.0, 200.0 * 1.0), 150.0 * 1.0, 8.0)
    np.testing.assert_array_equal(a, b)
    np.testing.assert_allclose(Ma, Mb)
