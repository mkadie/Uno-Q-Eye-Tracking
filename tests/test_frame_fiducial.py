"""Glasses-rim fiducial, checked against synthetic ground truth.

Every test here projects a rig of KNOWN dimensions through a KNOWN camera at a
KNOWN pose, fits the ellipses with the same cv2.fitEllipse the production path
uses, and checks what comes back. That closes the loop on the whole chain --
projection, fitting, and inversion -- rather than on the inversion alone, which
is where the interesting mistakes live (see trap (a): an ellipse adapter that
transposes the axes produces a plausible pose, not an exception).

Camera is C920-class: 1920x1080, 70.4 deg horizontal FOV.
"""

import json
import math
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2

from spike import frame_fiducial as ff
from spike.frame_fiducial import (YAW_MIN_FOR_PITCH_SIGN_DEG, Ellipse, RigSpec,
                                  eye_roi, plausible, pose_from_rims)

W, H = 1920, 1080
FOV_DEG = 70.4
FX = FY = (W / 2.0) / math.tan(math.radians(FOV_DEG / 2.0))
CX, CY = W / 2.0, H / 2.0

RIG = RigSpec(radius_mm=24.0, separation_mm=65.0, measured_n=5)


def _R(yaw_deg, pitch_deg, roll_deg):
    """R = Rz(roll) @ Ry(yaw) @ Rx(pitch), matching the module's convention."""
    y, p, r = (math.radians(v) for v in (yaw_deg, pitch_deg, roll_deg))
    Rx = np.array([[1, 0, 0],
                   [0, math.cos(p), -math.sin(p)],
                   [0, math.sin(p), math.cos(p)]])
    Ry = np.array([[math.cos(y), 0, math.sin(y)],
                   [0, 1, 0],
                   [-math.sin(y), 0, math.cos(y)]])
    Rz = np.array([[math.cos(r), -math.sin(r), 0],
                   [math.sin(r), math.cos(r), 0],
                   [0, 0, 1]])
    return Rz @ Ry @ Rx


def project_rig(distance_mm=600.0, yaw_deg=0.0, pitch_deg=0.0, roll_deg=0.0,
                n_pts=360, noise_px=0.0, seed=0, rig=RIG):
    """Project both rims and fit ellipses to the projected outlines."""
    rng = np.random.default_rng(seed)
    R = _R(yaw_deg, pitch_deg, roll_deg)
    t = np.array([0.0, 0.0, float(distance_mm)])

    out = []
    for sx in (-1.0, +1.0):                     # left rim, then right rim
        centre = np.array([sx * rig.separation_mm / 2.0, 0.0, 0.0])
        ang = np.linspace(0, 2 * math.pi, n_pts, endpoint=False)
        local = np.stack([centre[0] + rig.radius_mm * np.cos(ang),
                          centre[1] + rig.radius_mm * np.sin(ang),
                          np.zeros_like(ang)], axis=1)
        cam = (R @ local.T).T + t
        u = FX * cam[:, 0] / cam[:, 2] + CX
        v = FY * cam[:, 1] / cam[:, 2] + CY
        if noise_px:
            u = u + rng.normal(0, noise_px, u.shape)
            v = v + rng.normal(0, noise_px, v.shape)
        pts = np.stack([u, v], axis=1).astype(np.float32)
        out.append(Ellipse.from_cv(cv2.fitEllipse(pts)))

    left, right = out
    if left.cx > right.cx:                      # keep "left" leftmost in image
        left, right = right, left
    return left, right


def recover(hint=None, **kw):
    left, right = project_rig(**kw)
    return pose_from_rims(left, right, kw.get("rig", RIG), FX, FY, CX, CY,
                          pitch_hint_deg=hint)


# -- the accuracy sweep ------------------------------------------------------

SWEEP = [(y, p) for y in (-20, -10, 0, 10, 20)
         for p in (-20, -10, 0, 10, 20)]
DISTANCES = (450.0, 600.0, 900.0)


def _sweep_errors():
    """75 poses: 5 yaw x 5 pitch x 3 distances. Noise-free, hint supplied."""
    errs = {"distance": [], "yaw": [], "pitch": [], "roll": []}
    for dist in DISTANCES:
        for yaw, pitch in SWEEP:
            roll = 0.0
            got = recover(distance_mm=dist, yaw_deg=yaw, pitch_deg=pitch,
                          roll_deg=roll, hint=pitch)
            errs["distance"].append(abs(got["distance_mm"] - dist))
            errs["yaw"].append(abs(got["yaw_deg"] - yaw))
            errs["pitch"].append(abs(got["pitch_deg"] - pitch))
            errs["roll"].append(abs(got["roll_deg"] - roll))
    return {k: np.array(v) for k, v in errs.items()}


def test_distance_within_2mm_across_the_sweep():
    e = _sweep_errors()["distance"]
    assert e.max() < 2.0, "distance max error %.3f mm (mean %.3f)" % (e.max(),
                                                                     e.mean())


def test_yaw_within_half_a_degree():
    """Pins trap (c). A regression to the eccentricity path fails this."""
    e = _sweep_errors()["yaw"]
    assert e.max() < 0.5, "yaw max error %.3f deg (mean %.3f)" % (e.max(),
                                                                  e.mean())


def test_pitch_within_3_degrees():
    e = _sweep_errors()["pitch"]
    assert e.max() < 3.0, "pitch max error %.3f deg (mean %.3f)" % (e.max(),
                                                                    e.mean())


def test_roll_within_1_degree():
    e = _sweep_errors()["roll"]
    assert e.max() < 1.0, "roll max error %.3f deg (mean %.3f)" % (e.max(),
                                                                   e.mean())


def test_roll_is_recovered_when_actually_rolled():
    for roll in (-20.0, -5.0, 5.0, 20.0):
        got = recover(distance_mm=600.0, yaw_deg=10.0, pitch_deg=5.0,
                      roll_deg=roll, hint=5.0)
        assert abs(got["roll_deg"] - roll) < 1.0, \
            "roll %.1f -> %.2f" % (roll, got["roll_deg"])


# -- the behavioural guarantees ---------------------------------------------

def test_pitch_sign_is_flagged_ambiguous_at_zero_yaw():
    """Magnitude still correct; the SIGN is simply not in the image."""
    got = recover(distance_mm=600.0, yaw_deg=0.0, pitch_deg=12.0, hint=None)
    assert got["pitch_ambiguous"] is True
    assert abs(abs(got["pitch_deg"]) - 12.0) < 3.0


def test_no_pose_is_ever_silently_wrong_in_pitch():
    """Every pose must be either accurate OR flagged. Never confidently wrong.

    This is the property that matters in the field: a wrong-but-confident
    pitch steers the cursor the wrong way with no indication anything is off.
    """
    bad = []
    for yaw in (-15, -8, -4, -3, -2, -1, 0, 1, 2, 3, 4, 8, 15):
        for pitch in (-15, -8, -3, 3, 8, 15):
            got = recover(distance_mm=600.0, yaw_deg=yaw, pitch_deg=pitch,
                          hint=None)
            accurate = abs(got["pitch_deg"] - pitch) < 3.0
            if not (accurate or got["pitch_ambiguous"]):
                bad.append((yaw, pitch, got["pitch_deg"]))
    assert not bad, "confidently wrong pitch at (yaw, true, got): %r" % (bad,)


def test_the_inverted_sign_danger_zone_is_gated():
    """Regression guard for trap (d).

    Between roughly 1 and 3 degrees of yaw the two candidate normals separate
    cleanly AND the winner is systematically the wrong one. Anything that
    gates on candidate separation instead of on measured yaw passes its own
    confidence check and fails here.
    """
    for yaw in (1.0, 2.0, 3.0):
        for pitch in (-10.0, 10.0):
            got = recover(distance_mm=600.0, yaw_deg=yaw, pitch_deg=pitch,
                          hint=None)
            assert got["pitch_ambiguous"] is True, \
                "yaw %.1f pitch %.1f was NOT flagged" % (yaw, pitch)


def test_hint_only_supplies_the_sign_never_the_magnitude():
    a = recover(distance_mm=600.0, yaw_deg=0.0, pitch_deg=10.0, hint=90.0)
    b = recover(distance_mm=600.0, yaw_deg=0.0, pitch_deg=10.0, hint=18.0)
    assert a["pitch_deg"] == b["pitch_deg"]
    assert a["pitch_sign_from_hint"] and b["pitch_sign_from_hint"]


def test_hint_is_ignored_once_yaw_is_large_enough():
    """Past the gate the geometry decides, and a wrong hint must not win."""
    got = recover(distance_mm=600.0, yaw_deg=15.0, pitch_deg=10.0, hint=-99.0)
    assert got["pitch_sign_from_hint"] is False
    assert got["pitch_deg"] > 0.0


# -- the rig spec -----------------------------------------------------------

def test_rig_spec_rejects_overlapping_rims():
    with pytest.raises(ValueError) as e:
        RigSpec(radius_mm=24.0, separation_mm=40.0)
    assert "centre" in str(e.value).lower()


def test_rig_spec_rejects_nonsense_dimensions():
    for kw in ({"radius_mm": 0.0}, {"radius_mm": -1.0},
               {"separation_mm": 0.0}, {"separation_mm": -5.0}):
        with pytest.raises(ValueError):
            RigSpec(**kw)


def test_untrusted_rig_is_flagged_until_measured():
    assert RigSpec(measured_n=0).trusted is False
    assert RigSpec(measured_n=4).trusted is False
    assert RigSpec(measured_n=5).trusted is True


# -- consistency checks -----------------------------------------------------

def test_mismatched_pair_is_rejected_by_the_span_check():
    """Two unrelated circles must not yield a confident pose.

    The known separation is a measurement the pose never used to derive
    itself, so it is free evidence.
    """
    left, right = project_rig(distance_mm=600.0)
    stray = Ellipse(right.cx + 400.0, right.cy, right.a, right.b, right.theta)
    pose = pose_from_rims(left, stray, RIG, FX, FY, CX, CY)
    assert pose["span_residual_mm"] > 8.0
    assert plausible(pose, RIG) is False


def test_a_real_pair_is_plausible():
    left, right = project_rig(distance_mm=600.0, yaw_deg=10.0, pitch_deg=5.0)
    pose = pose_from_rims(left, right, RIG, FX, FY, CX, CY, pitch_hint_deg=5.0)
    assert plausible(pose, RIG) is True
    assert pose["span_residual_mm"] < 2.0


def test_distance_is_immune_to_rotation():
    """Trap (b)'s payoff: the major axis is the tilt axis, so it does not
    foreshorten and distance does not wobble with head pose."""
    got = [recover(distance_mm=700.0, yaw_deg=y, pitch_deg=p, hint=p)
           ["distance_mm"] for y, p in ((0, 0), (20, 0), (0, 20), (15, 15))]
    assert max(got) - min(got) < 2.0, "distance varies with pose: %r" % (got,)


def test_survives_subpixel_fitting_noise():
    errs = []
    for seed in range(5):
        got = recover(distance_mm=600.0, yaw_deg=12.0, pitch_deg=8.0,
                      noise_px=0.5, seed=seed, hint=8.0)
        errs.append(abs(got["yaw_deg"] - 12.0))
    assert max(errs) < 2.0, "yaw errors under 0.5 px noise: %r" % (errs,)


# -- the ellipse adapter, i.e. trap (a) -------------------------------------

def test_from_cv_puts_the_major_axis_first_either_way():
    tall = Ellipse.from_cv(((100.0, 200.0), (40.0, 90.0), 0.0))
    wide = Ellipse.from_cv(((100.0, 200.0), (90.0, 40.0), 0.0))
    assert tall.a == pytest.approx(45.0) and tall.b == pytest.approx(20.0)
    assert wide.a == pytest.approx(45.0) and wide.b == pytest.approx(20.0)
    # Same physical ellipse rotated by 90 deg: the major axes must be
    # perpendicular, which is exactly what trap (a) gets wrong.
    d = abs(tall.theta - wide.theta) % math.pi
    assert abs(d - math.pi / 2) < 1e-6


def test_from_cv_rejects_nothing_it_should_accept():
    e = Ellipse.from_cv(((0.0, 0.0), (50.0, 50.0), 33.0))
    assert e.axis_ratio == pytest.approx(1.0)


# -- the crop ---------------------------------------------------------------

def test_eye_roi_is_a_small_fraction_of_the_frame():
    left, right = project_rig(distance_mm=600.0)
    pose = pose_from_rims(left, right, RIG, FX, FY, CX, CY)
    x, y, w, h = eye_roi(pose, left, right)
    assert w > 0 and h > 0
    frac = (w * h) / float(W * H)
    assert frac < 0.12, "eye ROI is %.1f%% of the frame" % (100 * frac)


def test_eye_roi_contains_both_rims():
    left, right = project_rig(distance_mm=600.0, yaw_deg=10.0)
    pose = pose_from_rims(left, right, RIG, FX, FY, CX, CY, pitch_hint_deg=0.0)
    x, y, w, h = eye_roi(pose, left, right)
    for e in (left, right):
        assert x <= e.cx - e.b and e.cx + e.b <= x + w
        assert y <= e.cy - e.b and e.cy + e.b <= y + h


def test_eye_roi_grows_as_the_subject_approaches():
    near = eye_roi(*_pose_and_rims(400.0))
    far = eye_roi(*_pose_and_rims(900.0))
    assert near[2] * near[3] > far[2] * far[3]


def _pose_and_rims(dist):
    left, right = project_rig(distance_mm=dist)
    pose = pose_from_rims(left, right, RIG, FX, FY, CX, CY)
    return pose, left, right


# -- arc rejection, i.e. what the real glasses taught us --------------------

def test_arc_quality_separates_a_whole_rim_from_an_arc():
    """MEASURED 2026-09-16: cv2.fitEllipse fits a confident ellipse to a 90
    degree arc. On a real face the rim breaks into fragments, and the
    unfiltered detector reported 100% detection with a 17 mm radius on a
    23.5 mm rim. Coverage is what tells them apart."""
    from spike.frame_fiducial import arc_quality

    ang = np.linspace(0, 2 * math.pi, 360, endpoint=False)
    whole = np.stack([300 + 50 * np.cos(ang), 200 + 50 * np.sin(ang)], axis=1)
    e = Ellipse.from_cv(cv2.fitEllipse(whole.astype(np.float32)))

    cov_whole, res_whole = arc_quality(whole, e)
    assert cov_whole > 0.95, "a whole circle should cover nearly every bin"
    assert res_whole < 0.02

    quarter = whole[:90]
    e_arc = Ellipse.from_cv(cv2.fitEllipse(quarter.astype(np.float32)))
    cov_arc, _ = arc_quality(quarter, e_arc)
    assert cov_arc < 0.35, "a quarter arc must not look like a whole rim"


def test_find_rims_rejects_a_frame_of_arcs():
    """A field of broken arcs -- what a real rim looks like after Canny --
    must yield None, not a confident pair."""
    from spike.frame_fiducial import find_rims

    img = np.zeros((720, 1280), np.uint8)
    fx = 907.3
    expect_a = fx * RIG.radius_mm / 584.0
    for cx_ in (500, 700):
        ang = np.linspace(0.2, 1.6, 60)          # ~80 degrees only
        for t in ang:
            x = int(cx_ + expect_a * math.cos(t))
            y = int(360 + expect_a * math.sin(t))
            cv2.circle(img, (x, y), 1, 255, -1)
    assert find_rims(img, RIG, fx, expected_distance_mm=584.0) is None


def test_find_rims_still_finds_whole_rims():
    """The filter must not be so strict that a good pair is rejected."""
    from spike.frame_fiducial import find_rims

    img = np.zeros((720, 1280), np.uint8)
    fx = 907.3
    a = fx * RIG.radius_mm / 584.0
    sep = fx * RIG.separation_mm / 584.0
    for cx_ in (640 - sep / 2, 640 + sep / 2):
        cv2.circle(img, (int(cx_), 360), int(round(a)), 255, 2)
    found = find_rims(img, RIG, fx, expected_distance_mm=584.0)
    assert found is not None, "two clean circles must still be found"
    left, right = found
    assert left.cx < right.cx
    assert abs(left.a - a) / a < 0.15


def test_find_rims_rejects_a_pair_with_the_wrong_separation_to_radius_ratio():
    """The scale-invariant check. MEASURED 2026-09-16: eyebrow and eyelid
    fragments paired at sep/radius ~5.0 against the rig's true 2.67, and every
    resulting pose was confident and fictional. This ratio is fixed by the rig
    at ANY distance, so it catches them without needing to know the distance."""
    from spike.frame_fiducial import find_rims

    img = np.zeros((720, 1280), np.uint8)
    fx = 907.3
    a = fx * RIG.radius_mm / 584.0
    # Two correctly-sized circles, but far too far apart for this rig.
    bad_sep = fx * RIG.separation_mm / 584.0 * 2.2
    for cx_ in (640 - bad_sep / 2, 640 + bad_sep / 2):
        cv2.circle(img, (int(cx_), 360), int(round(a)), 255, 2)
    assert find_rims(img, RIG, fx, expected_distance_mm=584.0) is None


# -- the annulus: two concentric edges per lens ----------------------------

def test_ring_ratio_accepts_a_lens_and_rejects_the_impostors():
    """CALIPERED 2026-09-19: outer 50.0 mm over inner 44.0 mm = 1.1364.
    That ratio is the strongest false-positive filter available here."""
    from spike.frame_fiducial import ring_pair

    rig = RigSpec(radius_mm=25.0, inner_radius_mm=22.0, separation_mm=71.0)
    assert abs(rig.ring_ratio - 1.1364) < 1e-3

    def E(a, cx=100.0):
        return Ellipse(cx, 100.0, a, a * 0.95, 0.0)

    assert ring_pair([E(50), E(44)], rig) is not None      # a lens rim
    assert ring_pair([E(53), E(50)], rig) is None          # coffee lid  1.060
    assert ring_pair([E(54), E(40)], rig) is None          # grommet     1.350
    assert ring_pair([E(80), E(10)], rig) is None          # CD          8.000


def test_ring_pair_rejects_two_fits_of_the_same_edge():
    """Below ~4 px of radial separation the rim's two edges have merged.

    Accepting a merged pair fabricates confidence in a radius that is really
    the rim midline. MEASURED: bin/rimcheck at detect_width 1280 reported an
    implied radius of 23.71 mm when the mid-rim radius is 23.50 -- it had been
    fitting the midline all along, a 6% distance error nothing could see.
    """
    from spike.frame_fiducial import ring_pair, MIN_RING_SEPARATION_PX

    rig = RigSpec(radius_mm=25.0, inner_radius_mm=22.0, separation_mm=71.0)

    def E(a):
        return Ellipse(100.0, 100.0, a, a * 0.95, 0.0)

    # Right ratio, but the two fits are closer than the resolving limit.
    tight = 50.0
    assert ring_pair([E(tight), E(tight - MIN_RING_SEPARATION_PX * 0.5)],
                     rig) is None
    # Comfortably resolved -- what 1920 gives at 600 mm.
    assert ring_pair([E(50.0), E(44.0)], rig) is not None


def test_ring_pair_requires_concentricity():
    """Right ratio, wrong place: two unrelated circles that happen to nest."""
    from spike.frame_fiducial import ring_pair

    rig = RigSpec(radius_mm=25.0, inner_radius_mm=22.0, separation_mm=71.0)
    outer = Ellipse(100.0, 100.0, 50.0, 47.0, 0.0)
    inner_off = Ellipse(140.0, 100.0, 44.0, 42.0, 0.0)
    assert ring_pair([outer, inner_off], rig) is None


def test_ring_pair_identifies_which_edge_is_outer():
    """The whole point. Mistaking inner for outer is a 13.6% scale error --
    82 mm at 600 mm -- and a single ellipse cannot tell you which it has."""
    from spike.frame_fiducial import ring_pair

    rig = RigSpec(radius_mm=25.0, inner_radius_mm=22.0, separation_mm=71.0)
    a = Ellipse(100.0, 100.0, 50.0, 48.0, 0.0)
    b = Ellipse(100.0, 100.0, 44.0, 42.0, 0.0)
    for order in ([a, b], [b, a]):
        outer, inner = ring_pair(order, rig)
        assert outer.a == 50.0 and inner.a == 44.0


def test_rig_spec_rejects_inner_radius_that_is_not_inner():
    with pytest.raises(ValueError) as e:
        RigSpec(radius_mm=22.0, inner_radius_mm=25.0, separation_mm=71.0)
    assert "OUTER" in str(e.value)


# -- intrinsics ------------------------------------------------------------

def test_intrinsics_fallback_is_flagged_not_silent():
    from spike import intrinsics as I

    it = I.load(path="definitely-not-here.json", width=1280, height=720,
                warn=False)
    assert it.calibrated is False, "an assumed FOV must never claim to be real"
    assert it.fx > 0 and it.K.shape == (3, 3)


def test_intrinsics_scale_with_resolution():
    """fx, fy, cx, cy are all in pixels and all scale with width. Forgetting
    this is a silent proportional error in every distance."""
    from spike import intrinsics as I

    it = I.Intrinsics(1360.9, 1360.9, 960.0, 540.0, None, 1920, 1080)
    half = it.for_size(960, 540)
    assert abs(half.fx - 680.45) < 0.1
    assert abs(half.cx - 480.0) < 0.1
    assert it.for_size(1920, 1080) is it            # no-op when unchanged


def test_intrinsics_round_trip_from_a_calibration_file(tmp_path):
    from spike import intrinsics as I

    p = tmp_path / "camera_intrinsics.json"
    p.write_text(json.dumps({
        "fx": 1400.0, "fy": 1398.0, "cx": 958.0, "cy": 541.0,
        "dist_coeffs": [0.1, -0.2, 0.0, 0.0, 0.05],
        "width": 1920, "height": 1080, "rms": 0.31}))
    it = I.load(path=str(p))
    assert it.calibrated and it.rms == 0.31
    assert it.fx_fy_agree                            # within 2%
    assert it.dist_coeffs.shape == (5, 1)


def test_fx_fy_disagreement_is_detectable():
    """update.md: if fx and fy differ by more than 2% you did not tilt enough
    during capture, and the focal length is not separated from distance."""
    from spike import intrinsics as I

    assert I.Intrinsics(1400, 1390, 0, 0).fx_fy_agree is True
    assert I.Intrinsics(1400, 1200, 0, 0).fx_fy_agree is False


def test_intrinsics_reads_the_key_names_calibrate_camera_actually_writes(tmp_path):
    """tools/calibrate_camera.py writes image_width / rms_reproj_px, not
    width / rms. Reading the wrong ones leaves width None, for_size() becomes
    a no-op, and every distance inherits a silent scale error."""
    from spike import intrinsics as I

    p = tmp_path / "camera_intrinsics.json"
    p.write_text(json.dumps({
        "image_width": 1920, "image_height": 1080,
        "fx": 1400.0, "fy": 1398.0, "cx": 958.0, "cy": 541.0,
        "dist_coeffs": [0.1, -0.2, 0.0, 0.0, 0.05],
        "rms_reproj_px": 0.31, "n_frames": 20, "hfov_deg": 69.1}))
    it = I.load(path=str(p))
    assert it.width == 1920 and it.rms == 0.31
    assert abs(it.for_size(1280, 720).fx - 1400.0 * 1280 / 1920) < 0.1


def test_intrinsics_refuses_a_file_with_no_width(tmp_path):
    """Better to fail loudly than to skip the rescale silently."""
    from spike import intrinsics as I

    p = tmp_path / "camera_intrinsics.json"
    p.write_text(json.dumps({"fx": 1400.0, "fy": 1400.0,
                             "cx": 960.0, "cy": 540.0}))
    with pytest.raises(ValueError):
        I.load(path=str(p))


def test_ring_pair_refuses_a_correctly_proportioned_pair_of_bad_fits():
    """The 1.1364 ratio is not sufficient on its own.

    MEASURED 2026-09-19 on hardware: background clutter fitted
    a = 122.33 / 105.20, ratio 1.163, which is inside the +/-6% tolerance and
    was accepted -- on arc coverages of 0.28 and 0.33, where a real rim in the
    same frames scored 0.94. Geometry alone cannot tell those apart, because a
    sloppy fit's radius is close to arbitrary and two of them land in the right
    proportion often enough to matter.
    """
    rig = ff.RigSpec(radius_mm=25.0, inner_radius_mm=22.0, separation_mm=71.0)
    good = dict(cx=500.0, cy=400.0, theta=0.0)
    outer = ff.Ellipse(a=122.33, b=120.0, coverage=0.28, residual=0.072, **good)
    inner = ff.Ellipse(a=105.20, b=103.0, coverage=0.33, residual=0.080, **good)

    # It is the ratio test's kind of pair: concentric, well separated, in
    # proportion. Only the fit quality condemns it.
    assert abs(outer.a / inner.a - rig.ring_ratio) / rig.ring_ratio < ff.RING_RATIO_TOL
    assert outer.a - inner.a > ff.MIN_RING_SEPARATION_PX
    assert ff.ring_pair([outer, inner], rig) is None

    # Same geometry, credible fits -> accepted. This is what stops the gate
    # above from being satisfiable by simply rejecting everything.
    outer.coverage, inner.coverage = 0.94, 0.88
    assert ff.ring_pair([outer, inner], rig) == (outer, inner)


def test_ring_pair_still_accepts_quality_free_ellipses():
    """Synthetic ellipses carry no arc quality; refusing them would refuse
    every geometric test in this file."""
    rig = ff.RigSpec(radius_mm=25.0, inner_radius_mm=22.0, separation_mm=71.0)
    outer = ff.Ellipse(cx=300.0, cy=200.0, a=60.0, b=58.0, theta=0.0)
    inner = ff.Ellipse(cx=300.0, cy=200.0, a=52.8, b=51.0, theta=0.0)
    assert outer.coverage is None
    assert ff.ring_pair([outer, inner], rig) == (outer, inner)


def _blank(w=W, h=H):
    return np.zeros((h, w), np.uint8)


def test_squares_are_not_rims():
    """A square passes every roundness test there is.

    MEASURED 2026-09-19: the four ArUco markers of the printed rig were all
    being reported as flawless rims -- cv2.fitEllipse on a square contour
    returns axis_ratio 1.00 and arc coverage 1.00. Only the fit residual tells
    them apart (markers 0.100-0.106, a real rim 0.031), which is why
    max_residual is 0.06 rather than the 0.18 it was.

    This is not a marker-board curiosity. A maker faire is full of screens,
    keycaps, boxes and picture frames, and every one of them is a square.
    """
    rig = RigSpec(radius_mm=25.0, inner_radius_mm=22.0, separation_mm=71.0)
    z = 533.0
    a = FX * rig.radius_mm / z                      # 64 px at this distance

    img = _blank()
    # Two squares the size and spacing of a real rim pair -- i.e. the most
    # favourable possible case for a false positive.
    for cx in (int(W / 2 - FX * rig.separation_mm / z / 2),
               int(W / 2 + FX * rig.separation_mm / z / 2)):
        cv2.rectangle(img, (cx - int(a), 400 - int(a)),
                      (cx + int(a), 400 + int(a)), 255, 3)
    assert ff.find_rims(img, rig, FX, expected_distance_mm=z) is None


def test_real_circles_still_found_at_the_tighter_residual():
    """The square gate must not be satisfiable by rejecting everything."""
    rig = RigSpec(radius_mm=25.0, inner_radius_mm=22.0, separation_mm=71.0)
    z = 533.0
    a = FX * rig.radius_mm / z
    sep = FX * rig.separation_mm / z

    img = _blank()
    for cx in (int(W / 2 - sep / 2), int(W / 2 + sep / 2)):
        cv2.circle(img, (cx, 400), int(round(a)), 255, 2)
    found = ff.find_rims(img, rig, FX, expected_distance_mm=z)
    assert found is not None
    left, right = found
    assert left.cx < right.cx
    # Distance from the major axis, trap (b).
    for e in (left, right):
        assert abs(FX * rig.radius_mm / e.a - z) < 0.06 * z


def test_max_gradient_sees_an_isoluminant_edge_that_grayscale_cannot():
    """The reason the right lens was invisible for a whole session.

    An orange rim against brightly lit skin is close to isoluminant: the
    boundary barely exists in luminance while being obvious in b*. Construct
    exactly that -- two colours with the same BGR->GRAY luma and different
    chroma -- and check each edge image for the boundary.

    MEASURED on hardware, same frames: grayscale found 2 candidates and never
    the right lens in any frame; max_gradient found 7 and both lenses.
    """
    # cv2's BGR->GRAY is 0.114 B + 0.587 G + 0.299 R.
    def luma(b, g, r):
        return 0.114 * b + 0.587 * g + 0.299 * r

    skin = (120, 150, 190)
    rim = (60, 163, 190)
    assert abs(luma(*skin) - luma(*rim)) < 1.5      # same brightness
    assert abs(skin[0] - rim[0]) > 50               # different colour

    img = np.zeros((200, 200, 3), np.uint8)
    img[:, :] = skin
    cv2.circle(img, (100, 100), 50, rim, 6)

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    assert cv2.Canny(gray, 40, 120).sum() == 0, "test is not isoluminant"

    mg = ff.max_gradient(img)
    assert mg.shape == gray.shape
    assert mg.dtype == np.uint8
    assert cv2.Canny(mg, 40, 120).sum() > 0


def test_max_gradient_survives_a_flat_image():
    """No gradient anywhere must not divide by zero."""
    flat = np.full((32, 32, 3), 77, np.uint8)
    out = ff.max_gradient(flat)
    assert out.shape == (32, 32)
    assert int(out.max()) == 0
