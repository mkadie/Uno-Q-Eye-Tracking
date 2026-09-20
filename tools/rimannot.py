#!/usr/bin/env python3
"""Annotate one frame: board pose, and every round candidate with its size.

Numbers alone stopped being enough -- the fallback reported an implied radius
of 37.8 mm against a true 25.0, which means it is confidently measuring
something that is not a rim. Draw it.
"""
import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np, cv2
from spike import camera, config, intrinsics as I, rig_geometry
from spike.marker_board import MarkerBoard
from spike.frame_fiducial import RigSpec, Ellipse, arc_quality

W = 1920
cfg = config.load(); c = cfg["camera"]; fr = cfg.get("frame_rig", {})
H = int(round(W * c["height"] / c["width"]))
it = I.load(width=W, height=H)
rig = RigSpec(radius_mm=float(fr.get("radius_mm", 25.0)),
              inner_radius_mm=float(fr.get("inner_radius_mm", 22.0)),
              separation_mm=float(fr.get("separation_mm", 71.0)))
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
    if f is not None:
        frame = f
cam.close()
g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
vis = frame.copy()

bp = board.detect(g)
seed = 600.0
if bp:
    seed = bp["distance_mm"]
    print("board %.1f mm  yaw %+.1f pitch %+.1f roll %+.1f  reproj %.2f px  ids %s"
          % (seed, bp["yaw_deg"], bp["pitch_deg"], bp["roll_deg"],
             bp["reproj_px"], bp["ids_seen"]))
    # Draw the board origin and axes so its plane is visible.
    ax = np.float32([[0,0,0],[40,0,0],[0,40,0],[0,0,40]])
    pr, _ = cv2.projectPoints(ax, board._last_rvec, board._last_tvec,
                              it.K, it.dist_coeffs)
    pr = pr.reshape(-1, 2).astype(int)
    for k, col in ((1,(0,0,255)), (2,(0,255,0)), (3,(255,0,0))):
        cv2.line(vis, tuple(pr[0]), tuple(pr[k]), col, 3)
    cv2.circle(vis, tuple(pr[0]), 6, (255,255,255), -1)

expect_a = it.fx * rig.radius_mm / seed
print("at %.0f mm a TRUE rim is a=%.1f px (inner %.1f, gap %.1f)"
      % (seed, expect_a, expect_a / rig.ring_ratio,
         expect_a - expect_a / rig.ring_ratio))

edges = cv2.Canny(g, 40, 120)
cs, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
rows = []
for cc in cs:
    if len(cc) < 20:
        continue
    try:
        e = Ellipse.from_cv(cv2.fitEllipse(cc))
    except Exception:
        continue
    if not (expect_a * 0.45 <= e.a <= expect_a * 1.55) or e.axis_ratio < 0.60:
        continue
    cov, res = arc_quality(cc, e)
    if cov < 0.35 or res > 0.12:
        continue
    rows.append((e, cov, res))
rows.sort(key=lambda t: -t[1] * t[0].axis_ratio)
print("\n%d round candidates in the size window:" % len(rows))
for k, (e, cov, res) in enumerate(rows[:12]):
    Z = it.fx * rig.radius_mm / e.a
    print("  [%2d] a=%6.2f ratio=%.2f cov=%.2f res=%.3f at (%5.0f,%5.0f) -> %.0f mm"
          % (k, e.a, e.axis_ratio, cov, res, e.cx, e.cy, Z))
    col = (0,255,255) if k == 0 else (255,0,255)
    cv2.ellipse(vis, (int(e.cx), int(e.cy)), (int(e.a), int(e.b)),
                math.degrees(e.theta), 0, 360, col, 2)
    cv2.putText(vis, "%d:%.0f" % (k, e.a), (int(e.cx)-20, int(e.cy)-int(e.b)-6),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, col, 2)
# Reference: what a true rim would look like, drawn at frame centre.
cv2.circle(vis, (W//2, 80), int(expect_a), (0,255,0), 2)
cv2.putText(vis, "TRUE rim size at %.0f mm" % seed, (W//2+int(expect_a)+10, 85),
            cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0,255,0), 2)
cv2.imwrite("rimannot.png", vis)
print("\nwrote rimannot.png")
