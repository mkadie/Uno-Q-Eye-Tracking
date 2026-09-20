#!/usr/bin/env python3
"""Why did ring_pair reject? Dump every candidate and every pairwise verdict.

The sweep proved light is not the limit -- the face is properly exposed at
1250/0 -- yet no annulus forms. So the question is no longer "can Canny see
the rim" but "which of ring_pair's four gates is firing, and on what". Each
gate is printed by name so the answer is a reading, not a guess.

    python3 tools/ringwhy.py [expo] [gain]
"""
import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np, cv2
from spike import camera, config, intrinsics as I
from spike.frame_fiducial import (RigSpec, Ellipse, arc_quality,
                                  RING_RATIO_TOL, MIN_RING_SEPARATION_PX,
                                  RING_CONCENTRIC_FRAC)

EXPO = int(sys.argv[1]) if len(sys.argv) > 1 else 1250
GAIN = int(sys.argv[2]) if len(sys.argv) > 2 else 0
W = 1920
cfg = config.load(); c = cfg["camera"]; fr = cfg.get("frame_rig", {})
H = int(round(W * c["height"] / c["width"]))
it = I.load(width=W, height=H)
rig = RigSpec(radius_mm=float(fr.get("radius_mm", 25.0)),
              inner_radius_mm=float(fr.get("inner_radius_mm", 22.0)),
              separation_mm=float(fr.get("separation_mm", 71.0)))

cam = camera.Camera(c["device"], W, H, c["fps"], c["fourcc"],
                    EXPO, c["focus"], GAIN).open()
for _ in range(15):
    cam.read()
frame = None
for _ in range(8):
    f = cam.read()
    if f is not None:
        frame = f
cam.close()
g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
cv2.imwrite("ringwhy.png", frame)
print("expo %d gain %d  frame mean %.1f  face ROI mean %.1f"
      % (EXPO, GAIN, g.mean(), g[380:700, 830:1220].mean()))

# Wide size net: we do NOT know the distance, so do not gate on it here.
cands = []
for lo, hi in ((30, 90), (40, 110)):
    edges = cv2.Canny(g, lo, hi)
    cs, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    for cc in cs:
        if len(cc) < 18:
            continue
        try:
            e = Ellipse.from_cv(cv2.fitEllipse(cc))
        except Exception:
            continue
        if not (25.0 <= e.a <= 130.0) or e.axis_ratio < 0.55:
            continue
        cov, res = arc_quality(cc, e)
        if cov < 0.25 or res > 0.08:
            continue
        cands.append((e, cov, res, (lo, hi)))
cands.sort(key=lambda t: -t[0].a)
print("\n%d candidates (semi-major 25-130 px, ratio>=0.55, cov>=0.25, res<=0.08)"
      % len(cands))
for k, (e, cov, res, th) in enumerate(cands[:16]):
    print("  [%2d] a=%6.2f b=%6.2f ratio=%.2f cov=%.2f res=%.3f at (%5.0f,%5.0f)"
          "  -> Z=%.0f mm if OUTER" % (k, e.a, e.b, e.axis_ratio, cov, res,
                                       e.cx, e.cy, it.fx * rig.radius_mm / e.a))

print("\npairwise verdicts (want ratio %.4f +/-%.0f%%, sep >=%.1f px, "
      "centres within %.2f*a):" % (rig.ring_ratio, RING_RATIO_TOL * 100,
                                   MIN_RING_SEPARATION_PX, RING_CONCENTRIC_FRAC))
shown = 0
for i in range(min(len(cands), 16)):
    for j in range(min(len(cands), 16)):
        if i == j:
            continue
        o, n = cands[i][0], cands[j][0]
        if o.a <= n.a:
            continue
        d = math.hypot(o.cx - n.cx, o.cy - n.cy)
        if d > 0.6 * o.a:          # not even loosely co-located: not informative
            continue
        sep = o.a - n.a
        ratio = o.a / n.a
        err = abs(ratio - rig.ring_ratio) / rig.ring_ratio
        why = []
        if sep < MIN_RING_SEPARATION_PX: why.append("SEP %.1f<%.1f" % (sep, MIN_RING_SEPARATION_PX))
        if d > RING_CONCENTRIC_FRAC * o.a: why.append("OFFCENTRE %.1f>%.1f" % (d, RING_CONCENTRIC_FRAC*o.a))
        if err > RING_RATIO_TOL: why.append("RATIO %.3f (%.0f%% off)" % (ratio, err*100))
        print("  [%2d]/[%2d] a %6.2f/%6.2f sep %5.2f d %5.2f ratio %.3f  %s"
              % (i, j, o.a, n.a, sep, d, ratio,
                 "ACCEPT" if not why else " ; ".join(why)))
        shown += 1
        if shown >= 24:
            break
    if shown >= 24:
        break
if shown == 0:
    print("  none -- no two candidates are even loosely co-located,")
    print("  i.e. only ONE edge per lens is being found.")
