"""Target presentation and sampling, shared by bin/calibrate and bin/repeat.

Extracted from bin/calibrate 2026-08-18 so the repeatability test can reuse it
rather than fork a second copy of the collection loop -- two copies of "settle,
then average N non-blink frames" would drift apart and quietly stop measuring
the same thing.
"""

import time

import cv2
import numpy as np

from spike import features


WIN = "calibration"


def grid_points(n, w, h, margin=0.12):
    """n-point grid inset from the edges. Corners matter most -- that is where
    the polynomial has the least support and the most extrapolation error."""
    side = int(round(np.sqrt(n)))
    xs = np.linspace(margin, 1 - margin, side)
    ys = np.linspace(margin, 1 - margin, side)
    return [(int(x * w), int(y * h)) for y in ys for x in xs]


def shuffled(points, rng):
    """Randomise presentation order.

    MEASURED 2026-08-16, and it invalidates the interpretation of runs 1-6:
    presented as a raster, elapsed time is collinear with target y
    (r = +0.98 in the calibration block). Every "the head drifts over time"
    reading is therefore indistinguishable from "the head follows the target
    down the screen", and the two call for completely different fixes -- one
    wants online recalibration, the other wants the head-pose features dropped.

    Randomising decorrelates them, which is the only way either can be
    measured. The order is returned so it can be saved with the run.
    """
    idx = rng.permutation(len(points))
    return [points[i] for i in idx], idx


#: The original six. Kept EXACTLY as-is as the default so every run from
#: 2026-08-16 onward stays comparable with runs 1-5 -- changing the default
#: grid would silently invalidate that whole series.
_VAL6 = [(0.30, 0.30), (0.70, 0.30), (0.50, 0.50), (0.30, 0.70), (0.70, 0.70),
         (0.08, 0.08)]


def validation_points(w, h, n=6):
    """Deliberately offset from the calibration grid, including one point
    closer to a corner than any calibration point, to expose extrapolation.

    n > 6 gives a denser offset grid. Six points is enough to score a mapping
    but not to follow a curve: measuring how error falls as online
    recalibration clicks accumulate needs points to spend on clicks AND points
    left over to score on, and with six you run out after three.
    """
    if n <= len(_VAL6):
        rel = _VAL6[:n]
    else:
        # Half-cell offset from the calibration grid, so validation points sit
        # BETWEEN calibration points rather than on top of them.
        side = int(round(np.sqrt(n - 1)))
        xs = np.linspace(0.20, 0.80, side)
        ys = np.linspace(0.20, 0.80, side)
        rel = [(float(x), float(y)) for y in ys for x in xs]
        rel.append((0.08, 0.08))     # keep the extrapolation probe
    return [(int(x * w), int(y * h)) for x, y in rel]


def draw_target(canvas, pt, phase, label=""):
    canvas[:] = (16, 16, 18)
    r_outer = int(26 - 10 * phase)
    cv2.circle(canvas, pt, r_outer, (70, 140, 220), 2, cv2.LINE_AA)
    cv2.circle(canvas, pt, 5, (240, 240, 245), -1, cv2.LINE_AA)
    if label:
        cv2.putText(canvas, label, (30, 44), cv2.FONT_HERSHEY_SIMPLEX,
                    0.7, (150, 150, 160), 1, cv2.LINE_AA)
    cv2.putText(canvas, "look at the dot   |   q aborts",
                (30, canvas.shape[0] - 30), cv2.FONT_HERSHEY_SIMPLEX,
                0.6, (110, 110, 120), 1, cv2.LINE_AA)


def collect_point(cam, be, cfg, canvas, pt, label, tracker=None):
    """Show one target, settle, then average feature vectors over N samples.

    `tracker` (optional) is a tagtrack.TagTracker. When given, each accepted
    sample carries the ArUco tag's image position appended as two extra
    columns, and a frame where the tag is not found is REJECTED outright
    rather than averaged in with a gap. A calibration point half of whose
    samples lack the head signal is worse than one that retried.
    """
    settle = cfg["calibration"]["settle_ms"] / 1000.0
    n = cfg["calibration"]["samples_per_point"]
    size = cfg["inference"]["input_size"]
    blink_thr = cfg["inference"]["blink_ear_threshold"]

    t0 = time.perf_counter()
    feats = []
    while True:
        el = time.perf_counter() - t0
        phase = min(1.0, el / settle) if el < settle else 1.0
        draw_target(canvas, pt, phase, label)
        cv2.imshow(WIN, canvas)
        if (cv2.waitKey(1) & 0xFF) == ord("q"):
            return None

        frame = cam.read()
        if frame is None:
            continue
        h, w = frame.shape[:2]
        s = float(size) / max(h, w)
        small = cv2.resize(frame, (int(w * s), int(h * s)),
                           interpolation=cv2.INTER_AREA) if s < 1 else frame
        rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
        # Detect on the small frame, but crop the landmark ROI from the FULL
        # one. Both models have fixed input sizes, so this costs no inference
        # time and fills the 256x256 landmark input with real pixels.
        full_rgb = None if s >= 1 else cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        res = be.detect(rgb, full=full_rgb)
        if not res.ok:
            continue
        try:
            feat, diag = features.extract(res.landmarks, rgb.shape[1],
                                          rgb.shape[0])
        except Exception:
            continue
        # Blink frames carry garbage iris landmarks. Including them in a
        # calibration average poisons that whole grid point.
        if features.is_blinking(diag, blink_thr):
            continue
        if tracker is not None:
            hit = tracker.find(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
            if hit is None:
                continue
            # Normalised by frame size so a calibration survives a
            # resolution change, exactly like every other feature here.
            feat = np.concatenate([feat, [hit[0][0] / float(w),
                                          hit[0][1] / float(h)]])
        if el >= settle:
            feats.append(feat)
            if len(feats) >= n:
                break
    return np.mean(np.asarray(feats), axis=0)
