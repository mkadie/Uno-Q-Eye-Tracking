#!/usr/bin/env python3
"""Does the INNER rim edge appear in a colour-aware edge map?

At 312/192 the outer edge of the right lens fits cleanly (a=56.4, ratio 0.88,
cov 0.94) but the inner edge is absent. Suspected cause: Canny runs on
LUMINANCE, and a red rim against brightly-lit skin is nearly isoluminant --
the outer edge (rim against dark background) has contrast to spare, the inner
edge has almost none.

This is NOT a retreat to colour thresholding, which config.toml and CLAUDE.md
rule out for good reason: five rim colours and drifting hall light make any
tuned threshold a setup-day-only trick. Taking the per-pixel MAX gradient
across channels tunes nothing and prefers no colour -- it only says "an edge in
any channel is an edge". The ellipse is still found geometrically.

    python3 tools/ringchan.py [expo] [gain]
"""
import sys, os, math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np, cv2
from spike import camera, config, intrinsics as I
from spike.frame_fiducial import (RigSpec, Ellipse, arc_quality,
                                  RING_RATIO_TOL, MIN_RING_SEPARATION_PX,
                                  RING_CONCENTRIC_FRAC)

EXPO = int(sys.argv[1]) if len(sys.argv) > 1 else 312
GAIN = int(sys.argv[2]) if len(sys.argv) > 2 else 192
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
    if f is not None: frame = f
cam.close()
cv2.imwrite("ringchan.png", frame)

def edge_maps(img):
    """Several edge images over the SAME pixels, so they can be compared."""
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    out = {"gray": cv2.Canny(g, 40, 120)}
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    for nm, ch in (("lab_a", lab[:, :, 1]), ("lab_b", lab[:, :, 2]),
                   ("hsv_s", hsv[:, :, 1]),
                   ("B", img[:, :, 0]), ("G", img[:, :, 1]), ("R", img[:, :, 2])):
        out[nm] = cv2.Canny(cv2.GaussianBlur(ch, (5, 5), 0), 30, 90)
    # per-pixel max gradient across B,G,R,a*,b* -- tunes nothing, prefers
    # no colour, and is what should actually ship if it wins here.
    acc = np.zeros(g.shape, np.float32)
    for ch in (img[:, :, 0], img[:, :, 1], img[:, :, 2],
               lab[:, :, 1], lab[:, :, 2]):
        b = cv2.GaussianBlur(ch, (5, 5), 0).astype(np.float32)
        m = np.hypot(cv2.Sobel(b, cv2.CV_32F, 1, 0, ksize=3),
                     cv2.Sobel(b, cv2.CV_32F, 0, 1, ksize=3))
        acc = np.maximum(acc, m)
    acc = np.clip(acc / max(acc.max(), 1e-6) * 255, 0, 255).astype(np.uint8)
    out["maxgrad"] = cv2.Canny(acc, 40, 110)
    return out

def fits(edges, amin, amax, min_ratio=0.70, max_res=0.09):
    cs, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    r = []
    for cc in cs:
        if len(cc) < 18: continue
        try: e = Ellipse.from_cv(cv2.fitEllipse(cc))
        except Exception: continue
        if not (amin <= e.a <= amax) or e.axis_ratio < min_ratio: continue
        cov, res = arc_quality(cc, e)
        if cov < 0.30 or res > max_res: continue
        r.append((e, cov, res))
    return r

# Anchor on the lens found in grayscale, then work in a crop around it at
# FULL resolution -- update.md 2.2: the concentric check needs the full-res ROI,
# and cropping also deletes the frame-wide clutter that dominated the last run.
cands = fits(edge_maps(frame)["gray"], 30.0, 95.0,
             min_ratio=0.75, max_res=0.12)
anchor = max(cands or [(None, 0, 0)],
             key=lambda t: t[1] * (t[0].axis_ratio if t[0] else 0))
print("grayscale round candidates: %d" % len(cands))
for e, cov, res in sorted(cands, key=lambda t: -t[1])[:6]:
    print("   a=%6.2f ratio=%.2f cov=%.2f res=%.3f at (%5.0f,%5.0f)"
          % (e.a, e.axis_ratio, cov, res, e.cx, e.cy))
if anchor[0] is None:
    print("no anchor lens found in grayscale at %d/%d" % (EXPO, GAIN)); sys.exit(1)
A = anchor[0]
print("anchor lens: a=%.2f ratio=%.2f cov=%.2f at (%.0f,%.0f)"
      % (A.a, A.axis_ratio, anchor[1], A.cx, A.cy))
pad = int(A.a * 2.0)
x0, y0 = max(0, int(A.cx - pad)), max(0, int(A.cy - pad))
x1, y1 = min(W, int(A.cx + pad)), min(H, int(A.cy + pad))
crop = frame[y0:y1, x0:x1]
cv2.imwrite("ringchan_crop.png", crop)
want_inner = A.a / rig.ring_ratio
print("crop %dx%d  -- inner edge should sit at a=%.1f (%.1f px inside)\n"
      % (crop.shape[1], crop.shape[0], want_inner, A.a - want_inner))

print("%-9s | %-5s | %s" % ("channel", "fits", "semi-major values near the rim"))
for nm, ed in edge_maps(crop).items():
    r = sorted(fits(ed, A.a * 0.65, A.a * 1.35), key=lambda t: -t[0].a)
    vals = " ".join("%.1f(c%.2f)" % (e.a, cov) for e, cov, _ in r[:6])
    # does this channel produce a valid annulus on its own?
    ok = ""
    for i in range(len(r)):
        for j in range(len(r)):
            if i == j: continue
            o, n = r[i][0], r[j][0]
            if o.a <= n.a or (o.a - n.a) < MIN_RING_SEPARATION_PX: continue
            if math.hypot(o.cx-n.cx, o.cy-n.cy) > RING_CONCENTRIC_FRAC*o.a: continue
            if abs(o.a/n.a - rig.ring_ratio)/rig.ring_ratio > RING_RATIO_TOL: continue
            ok = "  <== ANNULUS %.1f/%.1f = %.3f  -> Z=%.0f mm" % (
                o.a, n.a, o.a/n.a, it.fx * rig.radius_mm / o.a)
            break
        if ok: break
    print("%-9s | %-5d | %s%s" % (nm, len(r), vals or "-", ok))
