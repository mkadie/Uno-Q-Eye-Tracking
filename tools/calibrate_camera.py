#!/usr/bin/env python3
"""Camera intrinsics from the printed chessboard.

    python3 calibrate_camera.py capture          # grab frames, SPACE to keep
    python3 calibrate_camera.py solve            # -> camera_intrinsics.json

Why bother: every distance this project reports is f * size / pixels, so an
error in f is a proportional error in every measurement downstream. A C920's
real focal length differs from the spec-sheet FOV by a few percent, and at 78
degrees diagonal the lens distortion at the frame corners is not small. Twenty
minutes here removes a systematic error larger than the difference between any
two fiducial designs you might argue about.
"""

import glob
import json
import os
import sys

import cv2
import numpy as np

COLS, ROWS = 9, 6          # INNER corners, matching calibration_chessboard.pdf
SQUARE_MM = 20.0
SHOTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "calib_shots")
OUT_JSON = "camera_intrinsics.json"
CRIT = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)


def find(gray):
    flags = (cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE
             | cv2.CALIB_CB_FAST_CHECK)
    found, corners = cv2.findChessboardCorners(gray, (COLS, ROWS), flags)
    if found:
        corners = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), CRIT)
    return found, corners


def capture(device=0, width=1920, height=1080, want=20):
    os.makedirs(SHOTS, exist_ok=True)
    cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    if not cap.isOpened():
        sys.exit("could not open camera %s" % device)

    print(__doc__)
    print("""
  Aim for %d good frames. What matters is VARIETY, not count:

    - tilt the board 30-45 degrees, in both axes, not just face-on.
      A set of face-on views cannot separate focal length from distance,
      and you get a confident, wrong f.
    - push the board into all four CORNERS of the frame. Distortion is
      largest there, and a board that only ever visits the middle leaves
      the distortion coefficients unconstrained.
    - fill roughly a third to two thirds of the frame.
    - keep it FLAT and keep it still. Motion blur moves corners.

  SPACE keeps a frame, q finishes.
""" % want)

    kept = len(glob.glob(os.path.join(SHOTS, "*.png")))
    while True:
        okf, frame = cap.read()
        if not okf:
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        found, corners = find(gray)
        view = frame.copy()
        if found:
            cv2.drawChessboardCorners(view, (COLS, ROWS), corners, found)
        cv2.putText(view, "kept %d/%d   %s" % (kept, want,
                    "BOARD FOUND - SPACE to keep" if found else "no board"),
                    (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.9,
                    (0, 220, 0) if found else (0, 0, 220), 2)
        cv2.imshow("calibration", view)
        k = cv2.waitKey(1) & 0xFF
        if k == ord("q"):
            break
        if k == ord(" ") and found:
            cv2.imwrite(os.path.join(SHOTS, "shot_%03d.png" % kept), frame)
            kept += 1
            print("  kept %d" % kept)
            if kept >= want:
                print("  that is enough -- press q, then run: solve")
    cap.release()
    cv2.destroyAllWindows()


def solve():
    files = sorted(glob.glob(os.path.join(SHOTS, "*.png")))
    if len(files) < 8:
        sys.exit("only %d shots in %s -- capture more (aim for 20)"
                 % (len(files), SHOTS))

    objp = np.zeros((COLS * ROWS, 3), np.float32)
    objp[:, :2] = np.mgrid[0:COLS, 0:ROWS].T.reshape(-1, 2) * SQUARE_MM

    obj, img, used, shape = [], [], [], None
    for f in files:
        g = cv2.imread(f, cv2.IMREAD_GRAYSCALE)
        shape = g.shape[::-1]
        found, corners = find(g)
        if found:
            obj.append(objp)
            img.append(corners)
            used.append(f)
    print("  usable: %d of %d frames" % (len(obj), len(files)))
    if len(obj) < 8:
        sys.exit("not enough usable frames")

    rms, K, dist, rvecs, tvecs = cv2.calibrateCamera(obj, img, shape, None, None)
    w, h = shape
    fx, fy, cx, cy = K[0, 0], K[1, 1], K[0, 2], K[1, 2]
    fov_x = 2 * np.degrees(np.arctan(w / (2 * fx)))

    # Per-frame reprojection error: one bad frame (a curled sheet, a blurred
    # grab) drags the whole solution, and the mean hides it.
    per = []
    for i in range(len(obj)):
        proj, _ = cv2.projectPoints(obj[i], rvecs[i], tvecs[i], K, dist)
        # OpenCV 4 hands back corners as (N,1,2); OpenCV 5 as (N,2), and
        # projectPoints does not always agree with findChessboardCorners about
        # which. cv2.norm then refuses on a type mismatch. Flatten both and do
        # the RMS in numpy -- same number, no shape argument.
        a = np.asarray(img[i], dtype=np.float64).reshape(-1, 2)
        b = np.asarray(proj, dtype=np.float64).reshape(-1, 2)
        per.append(float(np.sqrt(np.mean(np.sum((a - b) ** 2, axis=1)))))
    worst = int(np.argmax(per))

    print("\n  RMS reprojection error   %.4f px   %s" % (
        rms, "good" if rms < 0.5 else "high -- see the notes below"))
    print("  fx %.1f   fy %.1f   cx %.1f   cy %.1f" % (fx, fy, cx, cy))
    print("  implied horizontal FOV   %.2f deg" % fov_x)
    print("  distortion k1 %.4f  k2 %.4f  p1 %.4f  p2 %.4f  k3 %.4f"
          % tuple(dist.ravel()[:5]))
    print("  worst frame              %s (%.3f px)"
          % (os.path.basename(used[worst]), per[worst]))
    if per[worst] > 3 * np.median(per):
        print("    ^ that frame is an outlier. Delete it and re-run solve.")
    if abs(fx - fy) / fx > 0.02:
        print("  NOTE fx and fy differ by >2%% -- usually means too few tilted"
              " views. Capture more at 30-45 degrees.")

    data = {"image_width": w, "image_height": h,
            "fx": fx, "fy": fy, "cx": cx, "cy": cy,
            "dist_coeffs": dist.ravel().tolist(),
            "rms_reproj_px": float(rms), "n_frames": len(obj),
            "square_mm": SQUARE_MM, "pattern": [COLS, ROWS],
            "hfov_deg": float(fov_x)}
    with open(OUT_JSON, "w") as f:
        json.dump(data, f, indent=2)
    print("\n  wrote %s" % OUT_JSON)
    print("  use fx/fy/cx/cy in pose_from_rims() and cv2.solvePnP instead of")
    print("  the assumed-FOV values -- that is the point of all this.")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "capture"
    if mode == "capture":
        capture(device=int(sys.argv[2]) if len(sys.argv) > 2 else 0)
    elif mode == "solve":
        solve()
    else:
        sys.exit(__doc__)
