#!/usr/bin/env python3
"""Rim detection with the MONITOR as the face lamp.

Room lighting has blocked this measurement five times in one session. The
screen is the one light source already pointed at the subject's face and it is
fully under software control, so use it: fill it white, let the sensor settle,
then capture. Validated in the game build, where the same trick lifted the
face region from mean 21 to usable.

    python3 tools/rimlit.py [width] [expect_mm]
"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np, cv2
from spike import camera, config, intrinsics as I
from spike.frame_fiducial import (RigSpec, Ellipse, arc_quality, ring_pair,
                                  find_rims, pose_from_rims, plausible)

W = int(sys.argv[1]) if len(sys.argv) > 1 else 1920
EXPECT = float(sys.argv[2]) if len(sys.argv) > 2 else 600.0
cfg = config.load(); c = cfg["camera"]; fr = cfg.get("frame_rig", {})
H = int(round(W * c["height"] / c["width"]))
it = I.load(width=W, height=H)
rig = RigSpec(radius_mm=float(fr.get("radius_mm", 25.0)),
              inner_radius_mm=float(fr.get("inner_radius_mm", 22.0)),
              separation_mm=float(fr.get("separation_mm", 71.0)))

# Fill the screen white BEFORE opening the camera, so the face is already lit
# when the sensor settles.
win = "facelight"
cv2.namedWindow(win, cv2.WINDOW_NORMAL)
cv2.setWindowProperty(win, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
white = np.full((cfg["screen"]["height_px"], cfg["screen"]["width_px"], 3),
                255, np.uint8)
for _ in range(20):
    cv2.imshow(win, white)
    cv2.waitKey(10)

cam = camera.Camera(c["device"], W, H, c["fps"], c["fourcc"],
                    c["exposure"], c["focus"], c["gain"]).open()
for _ in range(40):                       # settle under the new light
    cam.read()
    cv2.imshow(win, white); cv2.waitKey(1)

best = None
for _ in range(25):
    f = cam.read()
    cv2.imshow(win, white); cv2.waitKey(1)
    if f is None:
        continue
    g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
    r = find_rims(g, rig, it.fx, expected_distance_mm=EXPECT,
                  annulus=True, clahe=False, close_px=0)
    if r is not None:
        p = pose_from_rims(r[0], r[1], rig, it.fx, it.fy, it.cx, it.cy,
                           pitch_hint_deg=0.0)
        best = (f, g, r, p)
        break
    last = (f, g)
cam.close()
cv2.destroyAllWindows()

if best is not None:
    f, g, r, p = best
    print("  ANNULUS LOCK. brightness mean %.1f" % g.mean())
    print("  outer L %.1f px  R %.1f px" % (r[0].a, r[1].a))
    print("  distance %.1f mm   yaw %+.1f  roll %+.1f  span_resid %.1f mm"
          % (p["distance_mm"], p["yaw_deg"], p["roll_deg"],
             p["span_residual_mm"]))
    print("  plausible: %s" % plausible(p, rig))
    cv2.imwrite("rimlit.png", f)
else:
    f, g = last
    print("  no annulus lock. brightness mean %.1f  p95 %.0f"
          % (g.mean(), np.percentile(g, 95)))
    ro = it.fx * rig.radius_mm / EXPECT
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
        if not (ro * 0.4 <= e.a <= ro * 1.8) or e.axis_ratio < 0.5:
            continue
        cov, res = arc_quality(cc, e)
        rows.append((e.a, e.axis_ratio, cov, res, e.cx, e.cy))
    rows.sort(key=lambda r: -r[0])
    print("  round, rim-sized candidates (need TWO concentric per lens):")
    for a, ar, cov, res, cx, cy in rows[:10]:
        print("    a=%6.1f ratio=%.2f cov=%.2f res=%.3f at (%5.0f,%5.0f)"
              % (a, ar, cov, res, cx, cy))
    cv2.imwrite("rimlit.png", f)
print("  wrote rimlit.png")
