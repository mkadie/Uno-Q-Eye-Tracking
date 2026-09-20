#!/usr/bin/env python3
"""Is the chessboard visible, whole, and detected? Run before a capture session.

Exists because a partially-visible board is never detected no matter how well
lit, and that failure looks identical to a lighting problem from the chair.
Inline heredocs over ssh mangle their own quoting, so this lives in a file.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np, cv2
from spike import camera, config

COLS, ROWS = 9, 6
FLAGS = (cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE
         | cv2.CALIB_CB_FAST_CHECK)

c = config.load()["camera"]
cam = camera.Camera(c["device"], c["width"], c["height"], c["fps"],
                    c["fourcc"], c["exposure"], c["focus"], c["gain"]).open()
for _ in range(30):
    cam.read()

hits, last, frame = 0, None, None
for _ in range(15):
    f = cam.read()
    if f is None:
        continue
    frame = f
    g = cv2.cvtColor(f, cv2.COLOR_BGR2GRAY)
    ok, corners = cv2.findChessboardCorners(g, (COLS, ROWS), FLAGS)
    if ok:
        hits += 1
        last = (f.copy(), corners, g.shape)

g = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
print("  brightness mean %.1f  p95 %.0f" % (g.mean(), np.percentile(g, 95)))
print("  %dx%d detected on %d of 15 frames" % (COLS, ROWS, hits))

if last is not None:
    f, corners, shape = last
    h, w = shape
    # OpenCV 4 returns (N,1,2); OpenCV 5 returns (N,2). Handle both.
    pts = corners.reshape(-1, 2)
    x, y = pts[:, 0], pts[:, 1]
    print("  spans x %.0f-%.0f of %d, y %.0f-%.0f of %d" % (x.min(), x.max(), w,
                                                            y.min(), y.max(), h))
    print("  fills ~%.0f%% of the frame  (want 33-66%%)"
          % (100 * (x.max() - x.min()) * (y.max() - y.min()) / (w * h)))
    print("  margins L%.0f R%.0f T%.0f B%.0f px"
          % (x.min(), w - x.max(), y.min(), h - y.max()))
    cv2.drawChessboardCorners(f, (COLS, ROWS), corners, True)
    cv2.imwrite("scene.png", f)
    print("  READY -- corners drawn on scene.png")
else:
    cv2.imwrite("scene.png", frame)
    print("  NOT DETECTED -- saved the raw frame as scene.png")
cam.close()
