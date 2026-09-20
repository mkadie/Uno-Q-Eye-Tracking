#!/usr/bin/env python3
"""Show the edge image itself around one rim.

The pair test now accepts the correct two lenses, but the ellipses land on the
brow and eye rather than the rim outline. That is a different question from
"can we see the rim": it asks what edges EXIST there, and a contour that is
present but broken needs a different fix from one that is absent.
"""
import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np, cv2
from spike import camera, config, intrinsics as I, rig_geometry
from spike.marker_board import MarkerBoard
from spike.frame_fiducial import RigSpec, Ellipse, arc_quality, max_gradient

W = 1920
cfg = config.load(); c = cfg["camera"]; fr = cfg.get("frame_rig", {})
H = int(round(W * c["height"] / c["width"]))
it = I.load(width=W, height=H)
rig = RigSpec(radius_mm=float(fr.get("radius_mm", 25.0)),
              inner_radius_mm=float(fr.get("inner_radius_mm", 22.0)),
              separation_mm=float(fr.get("separation_mm", 61.5)))
board = MarkerBoard(rig_geometry.OBJ_POINTS, rig_geometry.MARKER_IDS,
                    rig_geometry.DICT, it.K, it.dist_coeffs, min_markers=3)
cam = camera.Camera(c["device"], W, H, c["fps"], c["fourcc"],
                    int(fr.get("rim_exposure", 312)), c["focus"],
                    int(fr.get("rim_gain", 192))).open()
for _ in range(15):
    cam.read()
frame = None
for _ in range(6):
    f = cam.read()
    if f is not None: frame = f
cam.close()
g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
bp = board.detect(g)
Z = bp["distance_mm"] if bp else 450.0
ea = it.fx * rig.radius_mm / Z
print("board %.0f mm -> expect outer a=%.1f px, inner %.1f, gap %.1f"
      % (Z, ea, ea / rig.ring_ratio, ea - ea / rig.ring_ratio))

mg = max_gradient(frame)
# Locate the rim pair roughly: brightest orange-ish blob is unreliable, so
# just take the strongest round candidates and crop around their midpoint.
edges = cv2.Canny(mg, 40, 120)
cs, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
best = []
for cc in cs:
    if len(cc) < 20: continue
    try: e = Ellipse.from_cv(cv2.fitEllipse(cc))
    except Exception: continue
    if not (ea*0.55 <= e.a <= ea*1.45) or e.axis_ratio < 0.55: continue
    cov, res = arc_quality(cc, e)
    if cov < 0.40 or res > 0.06: continue
    best.append((e, cov, res))
if not best:
    print("no candidates"); sys.exit(1)
best.sort(key=lambda t: t[2])
e0 = best[0][0]
print("anchor at (%.0f,%.0f) a=%.1f res=%.3f" % (e0.cx, e0.cy, e0.a, best[0][2]))

pad = int(ea * 2.2)
x0, y0 = max(0, int(e0.cx-pad)), max(0, int(e0.cy-pad))
x1, y1 = min(W, int(e0.cx+pad)), min(H, int(e0.cy+pad))

# Three panels side by side: colour, max-gradient, Canny of it. Same pixels.
col = frame[y0:y1, x0:x1]
mgc = cv2.cvtColor(mg[y0:y1, x0:x1], cv2.COLOR_GRAY2BGR)
edc = cv2.cvtColor(edges[y0:y1, x0:x1], cv2.COLOR_GRAY2BGR)
# Draw a circle of the EXPECTED outer radius on the Canny panel so
# "is the outline there and the right size" is answerable by eye.
cv2.circle(edc, (int(e0.cx-x0), int(e0.cy-y0)), int(ea), (0,255,0), 1)
cv2.circle(edc, (int(e0.cx-x0), int(e0.cy-y0)), int(ea/rig.ring_ratio), (0,128,255), 1)
panel = np.hstack([col, mgc, edc])
cv2.imwrite("rimedge.png", panel)
print("wrote rimedge.png  (colour | max_gradient | Canny, green=expected outer,"
      " orange=expected inner)")
