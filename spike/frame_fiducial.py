"""6-DOF head pose from the circular rims of lensless party glasses.

The rims themselves ARE the fiducial. Nothing is printed, cut or glued on.

Why circles: a circle projects to an EXACT ellipse under perspective, and no
other outline does. So every departure from circular in the image is pure pose
information, and the inversion is closed form -- no solver, no template, no
per-batch calibration of the frame shape. A wayfarer or cat-eye outline is
already non-circular, so its shape and its perspective are entangled and you
would need a contour template per production batch.

Why two rims: they resolve the planar-marker sign ambiguity for yaw. Both lie
in one plane, so the rig's own x-axis must be perpendicular to the shared
normal, which picks the yaw branch. (It does NOT rescue pitch -- see trap (d).)

Rejected, with reasons, so nobody re-proposes them:
  - wayfarers + printed ArUco tabs: no flat area big enough, ~600 glue joints
    across 200 pairs, and a tab that rotates silently corrupts the geometry.
  - cat-eye + rhinestones: rhinestones are MIRRORS. The glint moves with the
    light, not the object. And 2-3 mm is about 5 px at working distance.
  - QR codes: built for a data payload; their corners are not optimised for
    pose.

Coordinate conventions, fixed here so everything downstream agrees:
  camera x right, y DOWN, z forward into the scene (OpenCV image convention)
  rig rotation R = Rz(roll) @ Ry(yaw) @ Rx(pitch)
  rim centres lie on the rig's local x-axis at (+/- separation/2, 0, 0)
"""

import math

import numpy as np

# Below this much measured yaw the pitch SIGN is not recoverable from geometry
# at all -- see trap (d) in pose_from_rims. This is a geometric threshold, not
# a tuning knob, and it is deliberately generous.
YAW_MIN_FOR_PITCH_SIGN_DEG = 5.0

# The rim is a RING, so Canny returns two concentric ellipses per lens and
# their ratio is fixed by the product: 50.0 mm outer over 44.0 mm inner.
# CALIPERED 2026-09-19.
RING_RATIO = 50.0 / 44.0                 # 1.1364
RING_RATIO_TOL = 0.06                    # +/- 6%

# Two fits closer than this are two fits of the SAME edge, not the two edges
# of a ring. A 3 mm rim subtends 6.8 px at 1920 and 2.3 px at 640 -- below
# about 960 the edges merge, and accepting a merged pair would fabricate
# confidence in a radius that is really the rim midline.
#
# MEASURED, and this is not hypothetical: bin/rimcheck at detect_width 1280
# reported an implied radius of 23.71 mm. The mid-rim radius is 23.50. It had
# been fitting the merged midline all along, which is a 6% distance error that
# nothing downstream could see.
MIN_RING_SEPARATION_PX = 4.0

# MEASURED 2026-09-19 on hardware: the ratio test ALONE will accept junk. A
# background pair fitted a = 122.33 / 105.20, ratio 1.163 against the wanted
# 1.1364 -- comfortably inside +/-6%, a clean accept -- on arc coverages of
# 0.28 and 0.33. A real rim in the same frames scored 0.94.
#
# The ratio asks "are these two ellipses concentric and correctly
# proportioned", and two sloppy fits of unrelated clutter can satisfy that by
# accident, because a bad fit's radius is close to arbitrary. So a pair is only as
# trustworthy as its WORSE member. find_rims already gates candidates at
# min_coverage before grouping, so this changes nothing on that path; it
# exists because ring_pair is public and documented as a standalone filter,
# and called directly it had no quality floor whatsoever.
#
# Only enforced when the caller supplied quality -- synthetic ellipses have
# none, and refusing them would be refusing the tests.
MIN_RING_COVERAGE = 0.40

# Concentric means concentric. Centres further apart than this fraction of the
# outer semi-major axis are two unrelated circles that happen to be nested.
RING_CONCENTRIC_FRAC = 0.25


class RigSpec:
    """Physical dimensions of one pair of glasses.

    `measured_n` is how many pairs were actually calipered. Everything
    downstream is meaningless until that is a real number: a 1 mm error in
    `radius_mm` is a ~4% error in every distance this module reports, and it
    is silent.
    """

    def __init__(self, radius_mm=25.0, separation_mm=71.0, measured_n=0,
                 spread_mm=None, inner_radius_mm=22.0):
        if radius_mm <= 0 or separation_mm <= 0:
            raise ValueError("rig dimensions must be positive, got "
                             "radius_mm=%r separation_mm=%r"
                             % (radius_mm, separation_mm))
        if separation_mm < 2.0 * radius_mm:
            # Physically impossible -- the rims would overlap. Almost always
            # means the caller measured the gap between the rims rather than
            # centre to centre.
            raise ValueError(
                "separation_mm (%.1f) < 2 * radius_mm (%.1f): the rims would "
                "overlap. Did you measure edge-to-edge instead of centre-to-"
                "centre?" % (separation_mm, 2.0 * radius_mm))
        if inner_radius_mm is not None and inner_radius_mm >= radius_mm:
            raise ValueError(
                "inner_radius_mm (%.1f) must be smaller than radius_mm (%.1f)"
                " -- radius_mm is the OUTER radius"
                % (inner_radius_mm, radius_mm))
        self.radius_mm = float(radius_mm)
        self.inner_radius_mm = (None if inner_radius_mm is None
                                else float(inner_radius_mm))
        self.separation_mm = float(separation_mm)
        self.measured_n = int(measured_n)
        self.spread_mm = None if spread_mm is None else float(spread_mm)

    @property
    def trusted(self):
        """Have enough pairs been calipered to believe these numbers?"""
        return self.measured_n >= 5

    @property
    def ring_ratio(self):
        """Outer/inner radius. The identity check for a lens rim."""
        if not self.inner_radius_mm:
            return RING_RATIO
        return self.radius_mm / self.inner_radius_mm

    def __repr__(self):
        return ("RigSpec(radius_mm=%.2f, separation_mm=%.2f, measured_n=%d, "
                "spread_mm=%r, trusted=%s)"
                % (self.radius_mm, self.separation_mm, self.measured_n,
                   self.spread_mm, self.trusted))


class Ellipse:
    """A fitted rim. Semi-axes, with `a` the major one, `theta` in radians."""

    def __init__(self, cx, cy, a, b, theta, coverage=None, residual=None):
        self.cx = float(cx)
        self.cy = float(cy)
        self.a = float(a)
        self.b = float(b)
        self.theta = float(theta)
        # Optional, set by find_rims from arc_quality(). Carried on the object
        # so ring_pair can refuse a pair of bad fits -- see MIN_RING_COVERAGE.
        self.coverage = None if coverage is None else float(coverage)
        self.residual = None if residual is None else float(residual)
        if self.b > self.a:
            raise ValueError("a must be the MAJOR semi-axis (a >= b), got "
                             "a=%.3f b=%.3f" % (self.a, self.b))

    @classmethod
    def from_cv(cls, fit):
        """Adapt cv2.fitEllipse output.

        TRAP (a): cv2.fitEllipse returns FULL axis lengths as the
        (width, height) of a rotated bounding box, and `angle` is the rotation
        of that box. Width lies along the rotated x-axis and height along the
        rotated y-axis -- so when the major axis is the HEIGHT one, its
        direction is angle + 90, not angle.

        Getting this backwards transposes every tilt by 90 degrees. It does not
        raise; it produces a plausible-looking pose that is wrong, which is the
        worst failure mode available.
        """
        (cx, cy), (w, h), angle_deg = fit
        if h >= w:
            a, b = h / 2.0, w / 2.0
            theta = math.radians(angle_deg + 90.0)
        else:
            a, b = w / 2.0, h / 2.0
            theta = math.radians(angle_deg)
        # Axes are lines, not vectors: fold into [0, pi).
        theta = theta % math.pi
        return cls(cx, cy, a, b, theta)

    @property
    def axis_ratio(self):
        """b / a = cos(tilt) for a circle. 1.0 means square-on."""
        return self.b / self.a if self.a > 0 else 0.0

    def __repr__(self):
        return ("Ellipse(cx=%.1f, cy=%.1f, a=%.2f, b=%.2f, theta=%.1f deg)"
                % (self.cx, self.cy, self.a, self.b, math.degrees(self.theta)))


def _axis_mean(thetas):
    """Mean of angles that are defined only modulo pi (axes, not vectors)."""
    s = sum(math.sin(2.0 * t) for t in thetas)
    c = sum(math.cos(2.0 * t) for t in thetas)
    return 0.5 * math.atan2(s, c)


def _line_diff(a, b):
    """Angle between two LINES, in [0, pi/2]."""
    d = abs(a - b) % math.pi
    return min(d, math.pi - d)


def _normal_in_plane(yaw, pitch, roll):
    """Image-plane (x, y) components of the rig normal.

    n = Rz(roll) @ Ry(yaw) @ Rx(pitch) @ (0, 0, 1)
      = Rz(roll) @ (cos(pitch)sin(yaw), -sin(pitch), cos(pitch)cos(yaw))

    The ellipse foreshortens ALONG this direction, so its minor axis lies
    parallel to it. That is what lets us test a candidate pitch sign against
    the observed ellipse orientation.
    """
    nx = math.cos(pitch) * math.sin(yaw)
    ny = -math.sin(pitch)
    cr, sr = math.cos(roll), math.sin(roll)
    return nx * cr - ny * sr, nx * sr + ny * cr


def pose_from_rims(left, right, rig, fx, fy, cx, cy, pitch_hint_deg=None):
    """Closed-form 6-DOF pose from two fitted rims.

    `left` and `right` are Ellipse objects; left must be the one further left
    in the IMAGE. Returns a dict -- see the module docstring for conventions.
    """
    f = math.sqrt(float(fx) * float(fy))    # rims are circles; pixels assumed square

    # TRAP (b): distance comes from the MAJOR axis. The major axis IS the tilt
    # axis, so it is the one direction that is never foreshortened -- which
    # makes distance immune to head rotation and lands sub-millimetre. Using
    # the minor axis, or the mean of the two, couples distance to pose and
    # every downstream metre-scale number inherits the wobble.
    z_left = f * rig.radius_mm / left.a
    z_right = f * rig.radius_mm / right.a

    def backproject(e, z):
        return np.array([(e.cx - cx) * z / fx, (e.cy - cy) * z / fy, z])

    p_left = backproject(left, z_left)
    p_right = backproject(right, z_right)

    # The known separation is a free consistency check: if these two ellipses
    # are not actually the two rims of one pair, the span will not match.
    span_mm = float(np.linalg.norm(p_right - p_left))
    span_residual_mm = abs(span_mm - rig.separation_mm)

    centre = 0.5 * (p_left + p_right)
    distance_mm = float(centre[2])

    # TRAP (c): yaw from the DEPTH DIFFERENCE, never from eccentricity.
    # With R = Rz Ry Rx, a rim at local (+S/2, 0, 0) sits at depth
    # z_c - (S/2)sin(yaw), so z_right - z_left = -S sin(yaw).
    # Deriving yaw from the axis ratio instead carries a systematic
    # perspective bias of a couple of degrees, because b/a = cos(tilt) holds
    # exactly only for a circle centred on the optical axis. The depth path
    # has no such bias and is what the < 0.5 deg test pins.
    sin_yaw = -(z_right - z_left) / rig.separation_mm
    # |sin_yaw| > 1 is not a large yaw, it is an IMPOSSIBLE one: the two rims
    # would be further apart in depth than the rig is wide. It means a bad
    # radius on at least one rim, and the clamp below turns that into a
    # confident +/-90 deg rather than an error. MEASURED 2026-09-20: a real
    # pair fitted 79.2 and 95.0 px -- a 72 mm depth difference across a
    # 61.5 mm separation -- and came out as a clean-looking 90 deg yaw that
    # only the span residual caught. Flag it so callers can tell the
    # difference between "turned a long way" and "arithmetic gave up".
    yaw_impossible = abs(sin_yaw) > 1.0
    yaw = math.asin(max(-1.0, min(1.0, sin_yaw)))

    # Roll is the image-plane angle of the rig's own x-axis, which is simply
    # the line joining the two rim centres. Rz leaves z alone, so this is
    # exact to first order regardless of yaw and pitch.
    roll = math.atan2(right.cy - left.cy, right.cx - left.cx)

    # Tilt magnitude from the averaged foreshortening of both rims.
    ratio = 0.5 * (left.axis_ratio + right.axis_ratio)
    tilt = math.acos(max(-1.0, min(1.0, ratio)))

    # cos(tilt) = cos(yaw) * cos(pitch)  -- the rig normal's z component.
    cos_yaw = math.cos(yaw)
    if abs(cos_yaw) < 1e-9:
        pitch_mag = 0.0
    else:
        pitch_mag = math.acos(max(-1.0, min(1.0, math.cos(tilt) / cos_yaw)))

    # TRAP (d): the pitch SIGN is geometrically degenerate near zero yaw.
    # Both rim centres lie ON the rig's x-axis and pitch rotates ABOUT that
    # axis, so at zero yaw, tilting up and tilting down produce mathematically
    # identical rim geometry. No amount of filtering or averaging fixes this --
    # the information is not in the image.
    #
    # The gate is on MEASURED YAW, not on how well separated the two candidate
    # normals look. Between roughly 1 and 3 degrees of yaw the candidates DO
    # separate cleanly and the winner is systematically the WRONG one, so a
    # separation score is not a correctness score. Gating on it would convert
    # an honest "ambiguous" into a confident error.
    yaw_deg = math.degrees(yaw)
    pitch_ambiguous = abs(yaw_deg) < YAW_MIN_FOR_PITCH_SIGN_DEG
    pitch_sign_from_hint = False

    if pitch_mag < 1e-9:
        sign = 1.0
    elif pitch_ambiguous:
        if pitch_hint_deg is not None:
            # ONE BIT ONLY. The hint says which way, never how far: its
            # magnitude comes from a different estimator with a different bias,
            # and mixing the two would launder that bias into this result.
            sign = 1.0 if float(pitch_hint_deg) >= 0.0 else -1.0
            pitch_sign_from_hint = True
        else:
            sign = 1.0
    else:
        observed = _axis_mean([left.theta, right.theta]) + math.pi / 2.0
        best, sign = None, 1.0
        for cand in (1.0, -1.0):
            nx, ny = _normal_in_plane(yaw, cand * pitch_mag, roll)
            if abs(nx) < 1e-12 and abs(ny) < 1e-12:
                continue
            d = _line_diff(math.atan2(ny, nx), observed)
            if best is None or d < best:
                best, sign = d, cand

    pitch = sign * pitch_mag

    return {
        "yaw_impossible": yaw_impossible,
        "t_mm": centre,
        "distance_mm": distance_mm,
        "z_left_mm": float(z_left),
        "z_right_mm": float(z_right),
        "yaw_deg": yaw_deg,
        "pitch_deg": math.degrees(pitch),
        "roll_deg": math.degrees(roll),
        "tilt_deg": math.degrees(tilt),
        "pitch_ambiguous": bool(pitch_ambiguous),
        "pitch_sign_from_hint": bool(pitch_sign_from_hint),
        "span_mm": span_mm,
        "span_residual_mm": span_residual_mm,
    }


def arc_quality(points, e, bins=36):
    """How much of a full ellipse does this contour actually cover, and how
    well does it fit? Returns (coverage, rms_residual / a).

    MEASURED 2026-09-16 on real glasses, and this is the whole reason the
    function exists: cv2.fitEllipse will fit a confident ellipse to a 90-degree
    ARC without complaint. On a real face the rim edge is broken into fragments
    and tangled with eyebrow, eyelid and hair edges, so the unfiltered detector
    reported 100% detection with a 17 mm radius on a 23.5 mm rim and an axis
    ratio of 0.585 while the subject faced the camera square-on. Every one of
    those was garbage, and nothing downstream could tell.

    Coverage is the fraction of angular bins around the fitted centre that
    contain at least one contour point: a whole rim approaches 1.0, an arc
    cannot exceed its own angular extent.

    Residual is the MEDIAN normalised distance to the fitted ellipse, not the
    RMS. MEASURED 2026-09-16: on a real face the rim contour usually arrives
    with a temple arm or an eyebrow fused to part of it, and RMS lets that
    minority of outlier points destroy an otherwise clean rim -- the right rim
    scored RMS 0.297 against median 0.151, while genuine junk scored 0.288
    median. RMS could not separate them; the median can.
    """
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 2)
    dx, dy = pts[:, 0] - e.cx, pts[:, 1] - e.cy

    ang = np.arctan2(dy, dx)
    hist, _ = np.histogram(ang, bins=bins, range=(-math.pi, math.pi))
    coverage = float((hist > 0).sum()) / float(bins)

    ct, st = math.cos(-e.theta), math.sin(-e.theta)
    xr = dx * ct - dy * st
    yr = dx * st + dy * ct
    if e.a <= 0 or e.b <= 0:
        return coverage, float("inf")
    r = np.sqrt((xr / e.a) ** 2 + (yr / e.b) ** 2)
    return coverage, float(np.median(np.abs(r - 1.0)))


def ring_pair(ellipses, rig, ratio_tol=RING_RATIO_TOL,
              min_sep_px=MIN_RING_SEPARATION_PX,
              concentric_frac=RING_CONCENTRIC_FRAC,
              min_coverage=MIN_RING_COVERAGE):
    """Find the (outer, inner) concentric pair that is one lens rim.

    The rim is a ring, so a clean detection yields TWO concentric ellipses
    whose radius ratio is fixed by the product (50.0/44.0 = 1.1364). Requiring
    that ratio is the strongest false-positive filter available here:

        lens rim         1.136   accept
        coffee lid       1.060   reject
        lanyard grommet  1.350   reject
        CD               8.000   reject

    It also answers the question a single ellipse cannot: WHICH EDGE am I
    looking at? Mistaking the inner edge for the outer is a 13.6% scale error
    -- 82 mm at 600 mm -- and with one ellipse there is no way to tell. With
    the pair, the outer is simply the larger one.

    Returns (outer, inner) or None.
    """
    want = rig.ring_ratio
    best, best_err = None, None
    for i in range(len(ellipses)):
        for j in range(len(ellipses)):
            if i == j:
                continue
            outer, inner = ellipses[i], ellipses[j]
            if outer.a <= inner.a:
                continue
            # Two fits of the SAME edge, not two edges of a ring. Accepting
            # these is how a merged rim silently becomes a confident radius
            # that is really the midline -- see MIN_RING_SEPARATION_PX.
            if (outer.a - inner.a) < min_sep_px:
                continue
            if math.hypot(outer.cx - inner.cx,
                          outer.cy - inner.cy) > concentric_frac * outer.a:
                continue
            err = abs(outer.a / inner.a - want) / want
            if err > ratio_tol:
                continue
            # A pair is only as trustworthy as its worse member.
            if any(e.coverage is not None and e.coverage < min_coverage
                   for e in (outer, inner)):
                continue
            if best_err is None or err < best_err:
                best, best_err = (outer, inner), err
    return best


def max_gradient(bgr):
    """Single-channel edge-strength image: the per-pixel MAX gradient across
    B, G, R, a* and b*.

    MEASURED 2026-09-19 on the orange glasses, same frames, only the edge
    image different:
        grayscale   2 candidates survived, and the RIGHT lens was never found
        max_gradient 7 survived, both lenses found, pair test ACCEPT
    Grayscale could not see the right rim in any frame of the session.

    Why: an orange rim against brightly lit skin is close to isoluminant, so
    the rim-to-skin boundary barely exists in luminance while being obvious in
    b*. The left lens survived in grayscale only because it happened to sit
    against the dark eye socket.

    This is NOT the colour thresholding that CLAUDE.md rules out, and the
    distinction is the point: a threshold picks a colour and a cut, so it is
    tuned at setup and drifts by lunchtime. Taking the max gradient picks no
    colour and has no cut -- it says only "an edge in any channel is an edge",
    which is equally true of all five rim colours and of a hall whose lights
    change. The ellipse is still found geometrically and colour is still read
    afterwards purely as an identity label.
    """
    import cv2

    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
    acc = None
    for ch in (bgr[:, :, 0], bgr[:, :, 1], bgr[:, :, 2],
               lab[:, :, 1], lab[:, :, 2]):
        b = cv2.GaussianBlur(ch, (5, 5), 0).astype(np.float32)
        m = np.hypot(cv2.Sobel(b, cv2.CV_32F, 1, 0, ksize=3),
                     cv2.Sobel(b, cv2.CV_32F, 0, 1, ksize=3))
        acc = m if acc is None else np.maximum(acc, m)
    peak = float(acc.max())
    if peak <= 1e-6:
        return np.zeros(acc.shape, np.uint8)
    return np.clip(acc / peak * 255.0, 0, 255).astype(np.uint8)


def ring_radii(grad, cx, cy, r_hint, rig, span=0.45, n_ang=180,
               ratio_tol=RING_RATIO_TOL):
    """Find the OUTER and INNER radii of a rim by radial profile.

    The annulus never formed with contour fitting, for a reason that has
    nothing to do with the annulus: on a real face the rim outline arrives
    broken into arcs and fused with brow and hair edges, so no connected
    component is a ring. MEASURED 2026-09-19.

    A radial profile sidesteps connectivity entirely. Walk outward from the
    centre along many angles and take the MEDIAN edge strength at each radius.
    A ring appears as two peaks; a gap in the ring costs a few angles out of
    180 and the median does not notice. That is the property contour fitting
    could not offer at any setting -- it is why this is a median and not a
    mean, and why n_ang is large.

    The two peaks are then required to sit at the rig's fixed 50.0/44.0 =
    1.1364. That ratio is the identity check (a coffee lid is 1.060, a grommet
    1.350) AND the answer to which edge is which, since the outer is simply
    the larger. Mistaking inner for outer is a 13.6% scale error -- 82 mm at
    600 mm -- and a single radius cannot tell.

    Returns (outer_px, inner_px) or None.
    """
    import cv2

    h, w = grad.shape[:2]
    r_lo = max(3.0, r_hint * (1.0 - span))
    r_hi = r_hint * (1.0 + span)
    n_rad = max(16, int(round(r_hi - r_lo)) * 2)
    radii = np.linspace(r_lo, r_hi, n_rad)
    ang = np.linspace(0.0, 2.0 * math.pi, n_ang, endpoint=False)
    ca, sa = np.cos(ang), np.sin(ang)

    xs = (cx + np.outer(radii, ca)).astype(np.float32)
    ys = (cy + np.outer(radii, sa)).astype(np.float32)
    ok = (xs >= 0) & (xs < w - 1) & (ys >= 0) & (ys < h - 1)
    if not ok.any():
        return None
    samp = cv2.remap(grad, xs, ys, cv2.INTER_LINEAR,
                     borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    samp = np.where(ok, samp.astype(np.float32), np.nan)
    with np.errstate(all="ignore"):
        prof = np.nanmedian(samp, axis=1)
    if not np.isfinite(prof).any():
        return None
    prof = np.nan_to_num(prof)

    # Local maxima only: a shoulder on the side of a stronger edge is not a
    # ring edge, and accepting one is how the midline gets reported as the rim.
    peaks = [i for i in range(1, len(prof) - 1)
             if prof[i] >= prof[i - 1] and prof[i] > prof[i + 1]]
    if len(peaks) < 2:
        return None
    want = rig.ring_ratio
    best, best_score = None, None
    for i in peaks:
        for j in peaks:
            ro, ri = radii[i], radii[j]
            if ro <= ri:
                continue
            if (ro - ri) < MIN_RING_SEPARATION_PX:
                continue
            if abs(ro / ri - want) / want > ratio_tol:
                continue
            # Prefer the strongest pair, not the closest ratio: ratio is
            # already gated, and edge strength is what says "this is the rim"
            # rather than a coincidence among weak texture peaks.
            score = prof[i] + prof[j]
            if best_score is None or score > best_score:
                best, best_score = (float(ro), float(ri)), score
    return best


def ring_ellipse(grad, cx, cy, r_outer, band=0.14, n_ang=180, keep=0.75):
    """Fit the outer rim edge from the GRADIENT image, one point per angle.

    ring_radii() locates the outer edge from a median profile, which is robust
    because it pools every angle. Throwing that away and refitting to binary
    Canny pixels puts the clutter straight back -- brow and hair edges near
    the rim drag the fit, and MEASURED 2026-09-19 that cost 28.8 mm of jitter
    against a board steady to 3.2 mm.

    So sample the gradient along each ray and take the single strongest
    response inside a narrow band around the known outer radius. That yields
    exactly one point per angle, on the strongest edge near where the rim
    already is, and it cannot return two points from one ray or none. Then fit
    those points, trimming the worst by radial residual -- an angle whose ray
    crosses an eyebrow contributes one bad point, not a whole contour.

    Distance still comes from the MAJOR axis of the result, which is the
    unforeshortened one (trap b). That is why this fits an ellipse rather than
    reporting the profile radius directly: the profile median pools over all
    angles and so lands between the major and minor axes, which under yaw is
    not the number the geometry wants.
    """
    import cv2

    h, w = grad.shape[:2]
    lo, hi = r_outer * (1.0 - band), r_outer * (1.0 + band)
    n_rad = max(9, int(round(hi - lo)) * 3)
    radii = np.linspace(lo, hi, n_rad)
    ang = np.linspace(0.0, 2.0 * math.pi, n_ang, endpoint=False)

    xs = (cx + np.outer(radii, np.cos(ang))).astype(np.float32)
    ys = (cy + np.outer(radii, np.sin(ang))).astype(np.float32)
    inb = (xs >= 0) & (xs < w - 1) & (ys >= 0) & (ys < h - 1)
    samp = cv2.remap(grad, xs, ys, cv2.INTER_LINEAR,
                     borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    samp = np.where(inb, samp.astype(np.float32), -1.0)

    idx = np.argmax(samp, axis=0)
    col = np.arange(n_ang)
    good = samp[idx, col] > 0.0
    if int(good.sum()) < 5:
        return None
    pts = np.stack([xs[idx, col][good], ys[idx, col][good]],
                   axis=1).astype(np.float32)

    e = None
    for _ in range(3):
        if len(pts) < 5:
            return None
        try:
            e = Ellipse.from_cv(cv2.fitEllipse(pts.reshape(-1, 1, 2)))
        except Exception:
            return None
        if e.a <= 0 or e.b <= 0:
            return None
        dx, dy = pts[:, 0] - e.cx, pts[:, 1] - e.cy
        ct, st = math.cos(-e.theta), math.sin(-e.theta)
        u, v = dx * ct - dy * st, dx * st + dy * ct
        err = np.abs(np.hypot(u / e.a, v / e.b) - 1.0)
        n_keep = max(5, int(len(pts) * keep))
        if n_keep >= len(pts):
            break
        pts = pts[np.argsort(err)[:n_keep]]
    return e


def refine_ellipse(edge_img, cx, cy, r, band=0.30, iters=3, keep=0.80):
    """Fit an ellipse to edge POINTS near a ring, ignoring contour connectivity.

    MEASURED 2026-09-19, and the reason this exists: on a real face the rim
    outline is present at the right size and the right place -- it is plainly
    visible in the edge image -- but findContours never returns it as one
    contour. It arrives broken into arcs AND fused with eyebrow and hair edges
    that touch it, so every connected component is either a fragment or a
    fragment plus clutter. Neither fits an ellipse, and the best-scoring
    candidate in the whole frame was the EYE.

    Morphological closing is the usual answer to a broken outline and is not
    available here: a 3x3 close bridges the two rim edges, which are only
    ~7-10 px apart, and destroys the annulus outright.

    So do not ask which pixels are connected -- ask which pixels lie near a
    ring of about the right radius, and fit those. Trimmed reweighting then
    walks off the clutter: fit, drop the worst points by radial residual,
    refit. Connectivity was never the information we wanted.
    """
    import cv2

    ys, xs = np.nonzero(edge_img)
    if xs.size < 5:
        return None
    d = np.hypot(xs - cx, ys - cy)
    m = (d > r * (1.0 - band)) & (d < r * (1.0 + band))
    if int(m.sum()) < 5:
        return None
    pts = np.stack([xs[m], ys[m]], axis=1).astype(np.float32)

    e = None
    for _ in range(max(1, iters)):
        if len(pts) < 5:
            return None
        try:
            e = Ellipse.from_cv(cv2.fitEllipse(pts.reshape(-1, 1, 2)))
        except Exception:
            return None
        # Radial residual in the ellipse's own frame: rotate into the axes,
        # then measure how far each point is from the unit ellipse.
        dx, dy = pts[:, 0] - e.cx, pts[:, 1] - e.cy
        ct, st = math.cos(-e.theta), math.sin(-e.theta)
        u, v = dx * ct - dy * st, dx * st + dy * ct
        if e.a <= 0 or e.b <= 0:
            return None
        rad = np.hypot(u / e.a, v / e.b)
        err = np.abs(rad - 1.0)
        n_keep = max(5, int(len(pts) * keep))
        if n_keep >= len(pts):
            break
        pts = pts[np.argsort(err)[:n_keep]]
    return e


def find_rims(gray, rig, fx, expected_distance_mm=600.0, tolerance=0.45,
              canny=(40, 120), min_coverage=0.40, max_residual=0.06,
              close_px=0, clahe=False, annulus=False):
    """Locate the two rims by SHAPE. Returns (left, right) or None.

    Detection is deliberately geometric and never colour-based. Five rim
    colours and a hall whose lighting drifts all day means any colour
    threshold that works at setup fails after lunch. Find the ellipse by its
    shape, then read colour from INSIDE it purely as a visitor-identity label.

    `min_coverage` and `max_residual` are what stop it fitting arcs -- see
    arc_quality(). A missed frame costs nothing here (head pose is sampled
    every detect_every_n frames anyway) whereas a confidently wrong pose
    steers the cursor and cannot be detected downstream. Prefer returning None.

    MEASURED 2026-09-16 on real glasses: coverage 0.40 is deliberately
    permissive because a real rim often arrives as a clean PARTIAL arc -- the
    left rim scored coverage 0.44 with a median residual of 0.058 and fitted
    to 40.3 px against a true 42.0. What makes that safe is not this gate but
    the pair-level scale-invariant ratio check below, which no accidental pair
    has ever passed.

    MEASURED 2026-09-19, and the reason max_residual is 0.06 and not the 0.18
    it used to be: A SQUARE IS A PERFECT ELLIPSE BY EVERY OTHER TEST. Fitting
    cv2.fitEllipse to the contour of an ArUco marker returns axis_ratio 1.00
    and arc coverage 1.00 -- it passes the roundness gate and the coverage
    gate outright, and at 0.18 it passed the residual gate too. All four
    markers of the printed rig were being reported as flawless rims.

    Residual is the ONLY gate that separates them, and it separates them
    cleanly: the markers sat at 0.100-0.106 while a real rim in the same
    session scored 0.031. 0.06 is the midpoint. This matters well beyond the
    marker board -- screens, keycaps, boxes and picture frames are everywhere
    a faire will put them, and every one of them is a square.

    `clahe` defaults OFF: it rescued a badly underlit room but costs contrast
    fidelity, and with adequate light the raw image fits better. Turn it on
    when the face region is below ~80 mean.
    """
    import cv2

    if clahe:
        # MEASURED 2026-09-16 on real glasses in a dim room: without local
        # contrast enhancement, 0 of 12 frames produced a contour that was
        # simultaneously round, right-sized, well-covered and a good fit.
        # With CLAHE at these Canny thresholds, 9 of 12 did. Black frames
        # against hair and shadowed skin is close to the worst case for a
        # global threshold, and a maker-faire hall will not be kinder.
        gray = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(gray)

    edges = cv2.Canny(gray, canny[0], canny[1])
    if close_px:
        # MEASURED 2026-09-19, and the reason this now defaults OFF: closing
        # is INCOMPATIBLE WITH THE ANNULUS. The two edges of a 3 mm rim are
        # about 7 px apart at 1920, and a 3x3 close bridges them -- it fuses
        # the ring into one thick blob whose contour no longer fits an
        # ellipse at all. Same scene, same frame, only this line different:
        #     close_px = 3  ->  0 candidates survived cov>=0.40 & res<=0.06
        #     close_px = 0  ->  3 survived, including the rim at res 0.044
        # So it was not merely unhelpful, it was deleting the signal it was
        # added to rescue, and silently -- the failure looks like "the rim
        # was not visible".
        #
        # Left available because a genuinely broken outline in a dim room is
        # a real case, but anything above 0 forfeits annulus mode: use it
        # only with annulus=False, and expect the radius you get to be the
        # midline rather than the outer edge.
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close_px, close_px))
        edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, k)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST,
                                   cv2.CHAIN_APPROX_NONE)

    expect_a = fx * rig.radius_mm / float(expected_distance_mm)
    lo, hi = expect_a * (1.0 - tolerance), expect_a * (1.0 + tolerance)

    cands = []
    for c in contours:
        if len(c) < 20:                      # fitEllipse needs >= 5; 20 for sanity
            continue
        try:
            e = Ellipse.from_cv(cv2.fitEllipse(c))
        except Exception:
            continue
        if not (lo <= e.a <= hi):
            continue
        # A rim seen at a plausible head pose is never edge-on. This also
        # throws out the long thin contours that temple arms and shadows make.
        if e.axis_ratio < 0.35:
            continue
        cov, res = arc_quality(c, e)
        if cov < min_coverage or res > max_residual:
            continue
        e.coverage, e.residual = cov, res
        cands.append(e)

    if annulus:
        # ANNULUS MODE. Each lens is a RING, so group candidates into
        # concentric outer/inner pairs and keep the OUTER of each. Two
        # payoffs, both measured: the 1.1364 ratio rejects almost every
        # non-lens circle, and the outer edge is IDENTIFIED rather than
        # guessed -- guessing wrong is a 13.6% scale error, 82 mm at 600 mm.
        #
        # Needs ~4 px of radial separation to resolve a 3 mm rim, i.e.
        # detect_width 1920. Canny returns roughly four edges per lens (both
        # sides of both boundaries), so accepted lenses are also de-duplicated
        # by position -- otherwise the leftovers pair up into a phantom second
        # lens sitting exactly on top of the real one.
        order = sorted(range(len(cands)), key=lambda k: -cands[k].a)
        lenses, taken = [], set()
        for i in order:
            if i in taken:
                continue
            for j in order:
                if j == i or j in taken:
                    continue
                pr = ring_pair([cands[i], cands[j]], rig)
                if pr is None:
                    continue
                outer = pr[0]
                dup = any(math.hypot(outer.cx - L.cx, outer.cy - L.cy)
                          < 0.5 * outer.a for L in lenses)
                taken.add(i)
                taken.add(j)
                if not dup:
                    lenses.append(outer)
                break
        cands = lenses

    if len(cands) < 2:
        return None

    # Pair by the known separation -- the same free check pose_from_rims uses.
    expect_px = fx * rig.separation_mm / float(expected_distance_mm)
    best, pair = None, None
    for i in range(len(cands)):
        for j in range(i + 1, len(cands)):
            p, q = cands[i], cands[j]
            d = math.hypot(q.cx - p.cx, q.cy - p.cy)
            # Rims of one pair are the same size on the sensor; wildly
            # different radii means two unrelated circles.
            size_err = abs(p.a - q.a) / max(p.a, q.a)
            score = abs(d - expect_px) / expect_px + size_err
            if best is None or score < best:
                best, pair = score, (p, q)

    if pair is None or best > tolerance + 0.5:
        return None
    p, q = pair

    # SCALE-INVARIANT consistency check, and the one that actually works.
    # The rig fixes the ratio separation/radius; that ratio is identical at
    # every distance, so unlike the size gate it needs no distance estimate
    # and cannot be fooled by a subject who is simply nearer or further than
    # expected.
    #
    # MEASURED 2026-09-16: without it, 62% of frames on a real face "yielded a
    # pair" and 0% of those were plausible -- fragments of eyebrow and eyelid
    # paired at sep/radius ~5.0 against the rig's true 2.67. The pose that
    # comes out is confident and entirely fictional.
    mean_a = 0.5 * (p.a + q.a)
    if mean_a <= 0:
        return None
    observed_ratio = math.hypot(q.cx - p.cx, q.cy - p.cy) / mean_a
    expect_ratio = rig.separation_mm / rig.radius_mm
    if abs(observed_ratio - expect_ratio) / expect_ratio > 0.35:
        return None

    return (p, q) if p.cx <= q.cx else (q, p)


def find_rims_hough(bgr, rig, fx, fy=None, cx0=None, cy0=None,
                    expected_distance_mm=600.0, tolerance=0.25,
                    grad=None, size_err_max=0.30, ratio_tol=0.35,
                    max_roll_deg=35.0, max_yaw_deg=45.0):
    """Locate both rims: Hough centres, annulus check, gradient-profile fit.

    This is the path that works on real faces, and it replaces the contour
    front end rather than tuning it. MEASURED 2026-09-19 against the marker
    board in the same frames: annulus on 100% of frames, pose on 85-92%,
    paired distance error p50 -0.4 mm, 6.9 mm std under a 5-frame median,
    against a board steady to 1.4 mm.

    find_rims() is kept for synthetic geometry and clean images. It cannot do
    this job: on a face the rim outline is present at the right size and place
    but arrives broken into arcs AND fused with the brow and hair edges that
    touch it, so no connected component is ever a ring, and the best-scoring
    contour in the whole frame was the EYE.

    The annulus is REQUIRED here, not optional. It is what identifies the
    outer edge instead of guessing -- measured p50 ratio of 1.000 against the
    board's expectation, where an inner-edge lock reads 1.136 and is a silent
    13.6% scale error.

    Returns (left, right) ordered by image x, or None.
    """
    import cv2

    if fy is None:
        fy = fx
    if cx0 is None:
        cx0 = bgr.shape[1] / 2.0
    if cy0 is None:
        cy0 = bgr.shape[0] / 2.0
    mg = max_gradient(bgr) if grad is None else grad
    ea = fx * rig.radius_mm / float(expected_distance_mm)
    if ea < 6.0:
        return None
    # Tie the Hough radius window to `tolerance` rather than hardcoding it.
    # MEASURED 2026-09-20: with the window at 0.70-1.35 while the candidate
    # gate was +/-0.40, Hough could propose circles the gate would have
    # refused, and the ladder at 450 mm came out bimodal -- most frames near
    # -7 mm with a tail at -105 mm, IQR 77 mm. The tail was a ~30% oversized
    # lock that a wide window admitted. One window, one number.
    lo_r = max(4, int(ea * (1.0 - tolerance)))
    hi_r = max(lo_r + 2, int(ea * (1.0 + tolerance)))
    circles = cv2.HoughCircles(
        mg, cv2.HOUGH_GRADIENT, dp=1.5, minDist=max(8.0, ea * 0.8),
        param1=110, param2=55, minRadius=lo_r, maxRadius=hi_r)
    if circles is None:
        return None

    lo, hi = ea * (1.0 - tolerance), ea * (1.0 + tolerance)
    cands = []
    for cx, cy, r in circles[0][:12]:
        rr = ring_radii(mg, float(cx), float(cy), float(r), rig)
        if rr is None:
            continue
        e = ring_ellipse(mg, float(cx), float(cy), rr[0])
        if e is None or e.axis_ratio < 0.55:
            continue
        if not (lo <= e.a <= hi):
            continue
        cands.append(e)
    if len(cands) < 2:
        return None

    # Pair on the scale-invariant separation/radius ratio: it holds at every
    # distance, so unlike the size window it cannot be fooled by a subject who
    # is simply nearer or further than expected.
    #
    # MEASURED 2026-09-20, and the reason the SCORE is not this ratio: at
    # 450 mm a spurious background pair beat the real rims on ratio+size error
    # by 0.122 to 0.126, and the ladder read 353 mm against a board at 457.
    # Ratio and size error are both cheap for clutter to satisfy -- any two
    # round-ish blobs at roughly the right spacing pass -- so ranking by them
    # is ranking by how easy the test is to fake.
    #
    # Rank by SPAN RESIDUAL instead. It compares the depth implied by the
    # separation against the depth implied by the radii, so it is a
    # measurement the candidate pair did not get to choose, and two unrelated
    # circles have no reason to agree on it. The real pair scored 1.5% on
    # ratio; the impostor scored 6% but won on size. On span residual they are
    # not close.
    #
    # Also require ROLL sanity. The rims sit side by side on one face, so the
    # line joining their centres is near-horizontal unless the head is rolled.
    # The impostor pair was diagonal -- 102 px of vertical offset against the
    # real pair's 3 px -- and nothing in the ratio test noticed.
    want = rig.separation_mm / rig.radius_mm
    best, pair = None, None
    for i in range(len(cands)):
        for j in range(i + 1, len(cands)):
            p, q = cands[i], cands[j]
            d = math.hypot(q.cx - p.cx, q.cy - p.cy)
            mean_a = 0.5 * (p.a + q.a)
            if mean_a <= 0:
                continue
            obs = d / mean_a
            size_err = abs(p.a - q.a) / max(p.a, q.a)
            if abs(obs - want) / want > ratio_tol or size_err > size_err_max:
                continue
            if abs(math.degrees(math.atan2(abs(q.cy - p.cy),
                                           max(abs(q.cx - p.cx), 1e-6)))) > max_roll_deg:
                continue
            # Depth difference is bounded by the geometry: the rims sit
            # separation_mm apart on one rigid plane, so |z_r - z_l| can never
            # exceed separation_mm * sin(yaw), and a head does not yaw past
            # max_yaw_deg while still showing both rims. This replaces
            # size_err as the real gate -- size_err is a fixed fraction, while
            # this scales correctly with distance, which is what the geometry
            # actually requires. MEASURED 2026-09-20: it rejects the 79.2/95.0
            # px pair that produced a fictional 90 deg yaw, and size_err 0.166
            # waved through.
            zp = fx * rig.radius_mm / p.a
            zq = fx * rig.radius_mm / q.a
            if abs(zq - zp) > rig.separation_mm * math.sin(
                    math.radians(max_yaw_deg)):
                continue
            lo_e, hi_e = (p, q) if p.cx <= q.cx else (q, p)
            pose = pose_from_rims(lo_e, hi_e, rig, fx, fy, cx0, cy0,
                                  pitch_hint_deg=0.0)
            if not plausible(pose, rig):
                continue
            score = pose["span_residual_mm"]
            if best is None or score < best:
                best, pair = score, (lo_e, hi_e)
    return pair


def eye_roi(pose, left, right, pad=1.25):
    """Crop covering both rims, as (x, y, w, h) in pixels.

    Caller clamps to the frame. Cropping here before the landmark model is
    what buys back the inference cost of detecting the rims at all.
    """
    xs = [left.cx - left.a, left.cx + left.a,
          right.cx - right.a, right.cx + right.a]
    ys = [left.cy - left.a, left.cy + left.a,
          right.cy - right.a, right.cy + right.a]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    w, h = (x1 - x0) * pad, (y1 - y0) * pad
    cxm, cym = 0.5 * (x0 + x1), 0.5 * (y0 + y1)
    return (int(round(cxm - w / 2.0)), int(round(cym - h / 2.0)),
            int(round(w)), int(round(h)))


def plausible(pose, rig, max_span_error_mm=8.0, max_tilt_deg=45.0):
    """Cheap sanity gate on a recovered pose.

    The span check is the valuable one: it is a measurement the pose did not
    use for its own derivation, so it catches two unrelated circles paired as
    a rig -- which otherwise yields a confident, entirely fictional pose.
    """
    if pose["span_residual_mm"] > max_span_error_mm:
        return False
    if pose["tilt_deg"] > max_tilt_deg:
        return False
    if pose["distance_mm"] <= 0.0:
        return False
    return True
