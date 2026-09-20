#!/usr/bin/env python3
"""Find an exposure/gain that actually resolves the rim ANNULUS.

The 156/0 pair in config.toml was measured in a bright room in August and is a
GAZE setting -- short exposure to avoid blur on a fast saccade. Rim pose is a
different problem: the head moves slowly (detect_every_n = 5), so a long
exposure costs nothing here and buys the photons the two rim edges need.

Exposure must come off the C920's EV ladder; anything else floors to the stop
below while still reading back as if it stuck.

    python3 tools/rimsweep.py [expect_mm]
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np, cv2
from spike import camera, config, intrinsics as I
from spike.frame_fiducial import (RigSpec, Ellipse, arc_quality, ring_pair,
                                  find_rims, pose_from_rims, plausible)

EXPECT = float(sys.argv[1]) if len(sys.argv) > 1 else 550.0
LADDER = [156, 312, 625, 1250]        # the C920 EV stops; nothing between works
GAINS  = [0, 96, 192]
W = 1920

cfg = config.load(); c = cfg["camera"]; fr = cfg.get("frame_rig", {})
H = int(round(W * c["height"] / c["width"]))
it = I.load(width=W, height=H)
rig = RigSpec(radius_mm=float(fr.get("radius_mm", 25.0)),
              inner_radius_mm=float(fr.get("inner_radius_mm", 22.0)),
              separation_mm=float(fr.get("separation_mm", 71.0)))
ro = it.fx * rig.radius_mm / EXPECT
ri = it.fx * rig.inner_radius_mm / EXPECT
print("at %.0f mm expect outer %.1f px, inner %.1f px, gap %.1f px"
      % (EXPECT, ro, ri, ro - ri))
print()
print("%6s %5s | %6s %6s | %5s | %s" %
      ("expo", "gain", "face", "p95", "cands", "result"))

best = None
for expo in LADDER:
    for gain in GAINS:
        try:
            cam = camera.Camera(c["device"], W, H, c["fps"], c["fourcc"],
                                expo, c["focus"], gain).open()
        except Exception as e:
            print("%6d %5d | open failed: %s" % (expo, gain, e)); continue
        for _ in range(12):
            cam.read()
        frames = [f for f in (cam.read() for _ in range(6)) if f is not None]
        cam.close()
        if not frames:
            print("%6d %5d | no frames" % (expo, gain)); continue

        note, ncand = "", 0
        for f in frames:
            g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
            roi = g[380:700, 830:1220]
            r = find_rims(g, rig, it.fx, expected_distance_mm=EXPECT,
                          annulus=True, clahe=False, close_px=0)
            if r is not None:
                p = pose_from_rims(r[0], r[1], rig, it.fx, it.fy, it.cx, it.cy,
                                   pitch_hint_deg=0.0)
                note = "ANNULUS  %.0f mm  yaw %+.1f  plausible=%s" % (
                    p["distance_mm"], p["yaw_deg"], plausible(p, rig))
                if best is None:
                    best = (expo, gain, p)
                    cv2.imwrite("rimsweep_best.png", f)
                break
            # count round rim-sized candidates so a near miss is visible
            edges = cv2.Canny(g, 40, 120)
            cs, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
            n = 0
            for cc in cs:
                if len(cc) < 20: continue
                try: e = Ellipse.from_cv(cv2.fitEllipse(cc))
                except Exception: continue
                if ro*0.5 <= e.a <= ro*1.6 and e.axis_ratio >= 0.55:
                    cov, res = arc_quality(cc, e)
                    if cov >= 0.3 and res <= 0.06: n += 1
            ncand = max(ncand, n)
        g = cv2.cvtColor(frames[-1], cv2.COLOR_BGR2GRAY)
        roi = g[380:700, 830:1220]
        print("%6d %5d | %6.1f %6.0f | %5d | %s"
              % (expo, gain, roi.mean(), np.percentile(roi, 95), ncand,
                 note or "no annulus"))

print()
if best:
    print("BEST: exposure %d gain %d -> %.0f mm" % (best[0], best[1], best[2]["distance_mm"]))
    print("wrote rimsweep_best.png")
else:
    print("no annulus at any setting -- the limit is light on the face, not exposure")
