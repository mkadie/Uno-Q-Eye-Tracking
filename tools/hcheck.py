#!/usr/bin/env python3
"""Draw what find_rims_hough locked onto, plus every Hough candidate."""
import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np, cv2
from spike import camera, config, intrinsics as I, rig_geometry
from spike.marker_board import MarkerBoard
from spike.frame_fiducial import (RigSpec, max_gradient, ring_radii,
                                  ring_ellipse, find_rims_hough,
                                  pose_from_rims)
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
for _ in range(15): cam.read()
frame = None
for _ in range(6):
    f = cam.read()
    if f is not None: frame = f
cam.close()
g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
bp = board.detect(g)
if bp is None:
    print("BOARD NOT VISIBLE -- no ground truth in this frame.")
    Z = 450.0
else:
    Z = bp["distance_mm"]
ea = it.fx * rig.radius_mm / Z
print("board %s -> expect rim a=%.1f px"
      % ("%.1f mm" % Z if bp else "ABSENT (assuming %.0f)" % Z, ea))
mg = max_gradient(frame)
vis = frame.copy()

circles = cv2.HoughCircles(mg, cv2.HOUGH_GRADIENT, dp=1.5,
                           minDist=max(8.0, ea*0.8), param1=110, param2=55,
                           minRadius=int(ea*0.70), maxRadius=int(ea*1.35))
print("hough radius window %d-%d px" % (int(ea*0.70), int(ea*1.35)))
if circles is not None:
    for k,(cx,cy,r) in enumerate(circles[0][:12]):
        rr = ring_radii(mg, float(cx), float(cy), float(r), rig)
        e = ring_ellipse(mg, float(cx), float(cy), rr[0]) if rr else None
        tag = "-" if rr is None else "ann %.1f/%.1f=%.3f" % (rr[0], rr[1], rr[0]/rr[1])
        print("  H[%d] c=(%4.0f,%4.0f) r=%5.1f  %s%s" % (
            k, cx, cy, r, tag,
            "" if e is None else "  -> a=%.1f ratio=%.2f  Z=%.0f mm" % (
                e.a, e.axis_ratio, it.fx*rig.radius_mm/e.a)))
        cv2.circle(vis, (int(cx),int(cy)), int(r), (255,0,255), 1)
        cv2.putText(vis, str(k), (int(cx)-8,int(cy)), cv2.FONT_HERSHEY_SIMPLEX,
                    0.7, (255,0,255), 2)
r = find_rims_hough(frame, rig, it.fx, it.fy, it.cx, it.cy,
                    expected_distance_mm=Z, grad=mg)
if r:
    po = pose_from_rims(r[0], r[1], rig, it.fx, it.fy, it.cx, it.cy, pitch_hint_deg=0.0)
    print("CHOSEN pair -> %.0f mm  yaw %+.1f  span_resid %.1f"
          % (po["distance_mm"], po["yaw_deg"], po["span_residual_mm"]))
    for e in r:
        cv2.ellipse(vis, (int(e.cx),int(e.cy)), (int(e.a),int(e.b)),
                    math.degrees(e.theta), 0,360, (0,255,255), 4)
else:
    print("CHOSEN pair: none")
# reference: true expected size
cv2.circle(vis, (150,150), int(ea), (0,255,0), 3)
cv2.putText(vis, "expected rim", (40,290), cv2.FONT_HERSHEY_SIMPLEX, 1.0,(0,255,0),2)
cv2.imwrite("hcheck.png", vis)
print("wrote hcheck.png")
