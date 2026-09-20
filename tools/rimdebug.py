#!/usr/bin/env python3
"""Why did the rims not detect? Dumps the frame, the edge map, and every
ellipse candidate with the reason it was kept or dropped."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np, cv2
from spike import camera, config, intrinsics as I
from spike.frame_fiducial import RigSpec, Ellipse, arc_quality, ring_pair

cfg = config.load(); c = cfg["camera"]; fr = cfg.get("frame_rig", {})
W = int(sys.argv[1]) if len(sys.argv) > 1 else 1920
H = int(round(W * c["height"] / c["width"]))
EXPECT = float(sys.argv[2]) if len(sys.argv) > 2 else 600.0

it = I.load(width=W, height=H)
rig = RigSpec(radius_mm=float(fr.get("radius_mm", 25.0)),
              inner_radius_mm=float(fr.get("inner_radius_mm", 22.0)),
              separation_mm=float(fr.get("separation_mm", 71.0)))
cam = camera.Camera(c["device"], W, H, c["fps"], c["fourcc"],
                    c["exposure"], c["focus"], c["gain"]).open()
for _ in range(30):
    cam.read()
frame = None
for _ in range(10):
    frame = cam.read()
    if frame is not None:
        break
cam.close()

g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
print("  %dx%d  brightness mean %.1f  p95 %.0f" % (W, H, g.mean(),
                                                   np.percentile(g, 95)))
ro = it.fx * rig.radius_mm / EXPECT
ri = it.fx * rig.inner_radius_mm / EXPECT
print("  at %.0f mm expect outer %.1f px, inner %.1f px, rim gap %.1f px"
      % (EXPECT, ro, ri, ro - ri))

edges = cv2.Canny(g, 40, 120)
cs, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
print("  contours: %d" % len(cs))

lo, hi = ro * 0.55, ro * 1.45
kept = []
near = []
for cc in cs:
    if len(cc) < 20:
        continue
    try:
        e = Ellipse.from_cv(cv2.fitEllipse(cc))
    except Exception:
        continue
    if not (lo * 0.6 <= e.a <= hi * 1.6):        # a wider net, to SEE them
        continue
    cov, res = arc_quality(cc, e)
    ok = (lo <= e.a <= hi) and e.axis_ratio >= 0.35 and cov >= 0.40 and res <= 0.18
    near.append((e.a, e.axis_ratio, cov, res, e.cx, e.cy, ok))
    if ok:
        kept.append(e)
near.sort(key=lambda r: -r[0])
print("  ellipses in the size neighbourhood: %d" % len(near))
for a, ar, cov, res, cx, cy, ok in near[:14]:
    print("    a=%6.1f ratio=%.2f cov=%.2f res=%.3f at (%5.0f,%5.0f) %s"
          % (a, ar, cov, res, cx, cy, "KEEP" if ok else "drop"))
print("  kept: %d" % len(kept))
print("  ring_pair on kept: %s" % ("FOUND" if ring_pair(kept, rig) else "None"))

cv2.imwrite("rimdbg.png", frame)
cv2.imwrite("rimdbg_edges.png", edges)
print("  wrote rimdbg.png and rimdbg_edges.png")
