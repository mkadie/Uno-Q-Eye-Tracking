#!/usr/bin/env python3
"""Hough centres + point-based ellipse refit, against the board.

findContours cannot deliver the rim outline as one contour (broken, and fused
with brow/hair). Hough voting does not care about connectivity -- every edge
pixel votes for a centre -- so a rim broken into six arcs still peaks in the
same place. Then refine_ellipse fits the POINTS near that ring.
"""
import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np, cv2
from spike import camera, config, intrinsics as I, rig_geometry
from spike.marker_board import MarkerBoard
from spike.frame_fiducial import (RigSpec, Ellipse, arc_quality, max_gradient,
                                  refine_ellipse, ring_radii, ring_ellipse, ring_pair,
                                  pose_from_rims, plausible)

N = int(sys.argv[1]) if len(sys.argv) > 1 else 40
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
for _ in range(12):
    cam.read()

want = rig.separation_mm / rig.radius_mm
res_rows, ax_rows, n_board, n_pair, n_ann, n = [], [], 0, 0, 0, 0
seed = 450.0
vis_saved = False
while n < N:
    f = cam.read()
    if f is None:
        continue
    n += 1
    g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
    bp = board.detect(g)
    if bp:
        n_board += 1
        seed = bp["distance_mm"]
    ea = it.fx * rig.radius_mm / seed

    mg = max_gradient(f)
    circles = cv2.HoughCircles(mg, cv2.HOUGH_GRADIENT, dp=1.5,
                               minDist=int(ea * 0.8), param1=110, param2=55,
                               minRadius=int(ea * 0.70), maxRadius=int(ea * 1.35))
    if circles is None:
        continue
    edges = cv2.Canny(mg, 40, 120)
    cand, n_ann_f = [], 0
    for cx, cy, r in circles[0][:12]:
        # Annulus by radial profile: identifies the OUTER edge instead of
        # guessing, and gives a radius to refit against that is not inflated
        # by brow clutter the way a wide band is.
        rr = ring_radii(mg, float(cx), float(cy), float(r), rig)
        if rr is not None:
            n_ann_f += 1
            e = ring_ellipse(mg, float(cx), float(cy), rr[0])
        else:
            e = refine_ellipse(edges, float(cx), float(cy), float(r))
        if e is None or e.axis_ratio < 0.55:
            continue
        if not (ea * 0.6 <= e.a <= ea * 1.4):
            continue
        cand.append(e)
    if n_ann_f:
        n_ann += 1
    if len(cand) < 2:
        continue

    best, pair = None, None
    for i in range(len(cand)):
        for j in range(i + 1, len(cand)):
            p, q = cand[i], cand[j]
            d = math.hypot(q.cx - p.cx, q.cy - p.cy)
            mean_a = 0.5 * (p.a + q.a)
            obs = d / mean_a
            size_err = abs(p.a - q.a) / max(p.a, q.a)
            if abs(obs - want) / want > 0.35 or size_err > 0.30:
                continue
            score = abs(obs - want) / want + size_err
            if best is None or score < best:
                best, pair = score, (p, q)
    if pair is None:
        continue
    p, q = pair if pair[0].cx <= pair[1].cx else (pair[1], pair[0])
    pose = pose_from_rims(p, q, rig, it.fx, it.fy, it.cx, it.cy,
                          pitch_hint_deg=0.0)
    if not plausible(pose, rig):
        continue
    n_pair += 1
    res_rows.append((bp["distance_mm"] if bp else None, pose["distance_mm"],
                     pose["yaw_deg"], pose["span_residual_mm"]))
    ax_rows.append((p.a, q.a, p.axis_ratio, q.axis_ratio,
                    math.hypot(q.cx - p.cx, q.cy - p.cy)))
    if not vis_saved:
        v = f.copy()
        for e, col in ((p, (0, 255, 255)), (q, (0, 255, 0))):
            cv2.ellipse(v, (int(e.cx), int(e.cy)), (int(e.a), int(e.b)),
                        math.degrees(e.theta), 0, 360, col, 3)
        cv2.imwrite("rimhough.png", v)
        vis_saved = True
cam.close()

print("frames %d | board %d (%.0f%%) | annulus %d (%.0f%%) | rim pose %d (%.0f%%)"
      % (n, n_board, 100.0*n_board/max(n,1), n_ann, 100.0*n_ann/max(n,1),
         n_pair, 100.0*n_pair/max(n,1)))
if not res_rows:
    print("no rim pose"); sys.exit(0)
rim = np.array([r[1] for r in res_rows])
print("RIM distance %.1f +/- %.1f mm   span_resid %.1f mm   yaw %+.1f +/- %.1f"
      % (rim.mean(), rim.std(),
         np.mean([r[3] for r in res_rows]),
         np.mean([r[2] for r in res_rows]), np.std([r[2] for r in res_rows])))
pr = [(b, m) for b, m, _, _ in res_rows if b is not None]
if len(pr) >= 3:
    d = np.array([b - m for b, m in pr])
    print("BOARD %.1f +/- %.1f mm" % (np.mean([b for b, _ in pr]),
                                      np.std([b for b, _ in pr])))
    print("vs board: BIAS %+.1f mm   JITTER %.1f mm   (n=%d)"
          % (d.mean(), d.std(), len(d)))

if ax_rows:
    A = np.array(ax_rows)
    print()
    print("per-rim semi-major:  left %.1f +/- %.1f px   right %.1f +/- %.1f px"
          % (A[:,0].mean(), A[:,0].std(), A[:,1].mean(), A[:,1].std()))
    print("axis ratio:          left %.2f +/- %.2f      right %.2f +/- %.2f"
          % (A[:,2].mean(), A[:,2].std(), A[:,3].mean(), A[:,3].std()))
    print("centre separation:   %.1f +/- %.1f px" % (A[:,4].mean(), A[:,4].std()))
    print()
    # Which single quantity would give the best distance if used alone?
    import itertools
    for nm, col in (("left a", A[:,0]), ("right a", A[:,1]),
                    ("mean a", 0.5*(A[:,0]+A[:,1])), ("separation", A[:,4])):
        size_mm = rig.separation_mm if nm == "separation" else rig.radius_mm
        z = it.fx * size_mm / col
        print("  Z from %-11s %.1f +/- %.1f mm" % (nm+":", z.mean(), z.std()))

if ax_rows:
    a = np.sort(0.5*(A[:,0]+A[:,1]))
    print("\nmean-a distribution (px), sorted:")
    print("  " + " ".join("%.0f" % v for v in a))
    print("  p5 %.1f  p25 %.1f  p50 %.1f  p75 %.1f  p95 %.1f"
          % tuple(np.percentile(a, [5,25,50,75,95])))
    ea0 = it.fx * rig.radius_mm / np.mean([r[0] for r in res_rows if r[0]])
    print("  board says the outer rim should be a=%.1f px" % ea0)
    print("  ratio measured/expected: p50 %.3f  (1.136 would mean we locked"
          " onto the INNER edge)" % (np.median(a)/ea0))

pr2 = [(b, m) for b, m, _, _ in res_rows if b is not None]
if len(pr2) >= 5:
    d = np.array([m - b for b, m in pr2])          # rim minus board, per frame
    print("\nPAIRED ERROR, per frame (rim - board), percentiles:")
    print("  p5 %+.1f   p25 %+.1f   p50 %+.1f   p75 %+.1f   p95 %+.1f mm"
          % tuple(np.percentile(d, [5, 25, 50, 75, 95])))
    print("  median abs error %.1f mm   IQR width %.1f mm"
          % (np.median(np.abs(d)), np.percentile(d,75)-np.percentile(d,25)))
    print("  mean %+.1f  std %.1f mm   <- what the std hides: %.0f%% of frames"
          % (d.mean(), d.std(),
             100.0*np.mean(np.abs(d - np.median(d)) > 3*np.percentile(np.abs(d-np.median(d)),50))))
    # A 5-frame median is legitimate here, not masking: head pose is sampled
    # every detect_every_n=5 frames anyway, so it costs nothing real.
    k = 5
    if len(pr2) >= k:
        med = np.array([np.median([m for _, m in pr2[i:i+k]])
                        for i in range(len(pr2)-k+1)])
        bb  = np.array([np.median([b for b, _ in pr2[i:i+k]])
                        for i in range(len(pr2)-k+1)])
        dm = med - bb
        print("  with a %d-frame median: p50 %+.1f  IQR %.1f  std %.1f mm"
              % (k, np.median(dm), np.percentile(dm,75)-np.percentile(dm,25), dm.std()))
