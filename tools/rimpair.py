#!/usr/bin/env python3
"""Which stage of find_rims kills the pair? Count survivors at each gate.

'pair 0%' says the pipeline failed but not where. find_rims filters on size,
then roundness, then coverage/residual, then scores pairs by the
separation-to-radius ratio. Any one of those can be the whole story and they
are invisible from outside.
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
    if f is not None: frame = f
cam.close()
g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
vis = frame.copy()

bp = board.detect(g)
seed = bp["distance_mm"] if bp else 600.0
print("board %.1f mm (reproj %.2f)" % (seed, bp["reproj_px"]) if bp else "no board")

TOL = 0.45
ea = it.fx * rig.radius_mm / seed
lo, hi = ea * (1 - TOL), ea * (1 + TOL)
print("expect outer a=%.1f px, accept %.1f-%.1f" % (ea, lo, hi))

CLOSE = int(sys.argv[1]) if len(sys.argv) > 1 else 3
SRC = sys.argv[2] if len(sys.argv) > 2 else "gray"
if SRC == "maxgrad":
    # Per-pixel MAX gradient over B,G,R,a*,b*. This tunes nothing and prefers
    # no colour -- it only says "an edge in any channel is an edge" -- so it
    # is not the colour thresholding CLAUDE.md rules out. The ellipse is still
    # found geometrically. Motivation: an orange rim against lit skin is close
    # to isoluminant, so the inner edge is nearly invisible in luminance.
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
    acc = np.zeros(g.shape, np.float32)
    for ch in (frame[:, :, 0], frame[:, :, 1], frame[:, :, 2],
               lab[:, :, 1], lab[:, :, 2]):
        b = cv2.GaussianBlur(ch, (5, 5), 0).astype(np.float32)
        m = np.hypot(cv2.Sobel(b, cv2.CV_32F, 1, 0, ksize=3),
                     cv2.Sobel(b, cv2.CV_32F, 0, 1, ksize=3))
        acc = np.maximum(acc, m)
    g = np.clip(acc / max(acc.max(), 1e-6) * 255, 0, 255).astype(np.uint8)
print("edge source: %s" % SRC)
edges = cv2.Canny(g, 40, 120)
if CLOSE:
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (CLOSE, CLOSE))
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, k)
print("close_px = %d" % CLOSE)
cs, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)

n_len = n_size = n_round = 0
keep = []
for cc in cs:
    if len(cc) < 20:
        continue
    n_len += 1
    try:
        e = Ellipse.from_cv(cv2.fitEllipse(cc))
    except Exception:
        continue
    if not (lo <= e.a <= hi):
        continue
    n_size += 1
    if e.axis_ratio < 0.35:
        continue
    n_round += 1
    cov, res = arc_quality(cc, e)
    if cov < 0.40 or res > 0.06:
        continue
    keep.append((e, cov, res))

print("\ncontours>=20pts %d -> in size window %d -> round enough %d -> "
      "cov>=0.40 & res<=0.06 %d" % (n_len, n_size, n_round, len(keep)))
keep.sort(key=lambda t: t[2])
for i, (e, cov, res) in enumerate(keep[:10]):
    print("  [%d] a=%6.2f ratio=%.2f cov=%.2f res=%.3f at (%5.0f,%5.0f) -> %.0f mm"
          % (i, e.a, e.axis_ratio, cov, res, e.cx, e.cy,
             it.fx * rig.radius_mm / e.a))
    cv2.ellipse(vis, (int(e.cx), int(e.cy)), (int(e.a), int(e.b)),
                math.degrees(e.theta), 0, 360, (0, 255, 255), 2)
    cv2.putText(vis, str(i), (int(e.cx) - 10, int(e.cy) - int(e.b) - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)

want = rig.separation_mm / rig.radius_mm
print("\npair test: separation/mean_radius must be %.2f +/-35%% (%.2f-%.2f)"
      % (want, want * 0.65, want * 1.35))
if len(keep) < 2:
    print("  IMPOSSIBLE -- fewer than two survivors. Only one rim is being")
    print("  found, so no pair constraint can ever apply.")
else:
    for i in range(min(len(keep), 8)):
        for j in range(i + 1, min(len(keep), 8)):
            p, q = keep[i][0], keep[j][0]
            d = math.hypot(q.cx - p.cx, q.cy - p.cy)
            mean_a = 0.5 * (p.a + q.a)
            obs = d / mean_a
            size_err = abs(p.a - q.a) / max(p.a, q.a)
            ok = abs(obs - want) / want <= 0.35
            print("  [%d]x[%d] sep %6.1f px  ratio %5.2f  size_err %.2f  %s"
                  % (i, j, d, obs, size_err, "ACCEPT" if ok else "reject"))
cv2.imwrite("rimpair.png", vis)
print("\nwrote rimpair.png")
