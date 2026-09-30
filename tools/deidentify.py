#!/usr/bin/env python3
"""Blur everything in a capture except the face and the drawn annotations.

WHY THIS EXISTS: board_artifacts holds annotated camera frames that are the
measurement evidence for the glasses-rim work. They were shot in the
developer's home, and several show him shirtless. The consent given for
publication was for his FACE, so this keeps the face and destroys the rest.

Three rules, in order:

  1. KEEP the detected face, generously boxed -- it is the subject of every
     one of these figures and the rim annotations sit on it.
  2. KEEP pixels that were DRAWN ON by the analysis. A stroke is a pure
     colour (one channel pegged, another near zero); no skin, wall or
     furniture is. Preserving them keeps the candidate circles and labels
     that make the figures readable, and a circle outline over a destroyed
     background reveals nothing about the room.
  3. DESTROY everything else -- downsample to 1/28 and back, THEN blur.
     A Gaussian alone is partly invertible; throwing the pixels away is not.

Run: python3 tools/deidentify.py board_artifacts/*.png
"""
import os
import sys

import cv2
import numpy as np

BLOCK = 44          # downsample factor; bigger = less recoverable
FACE_PAD = 0.22     # expand the detector's box by this fraction each way
CHIN_PAD = 0.10     # far less below: the chin is where the torso starts


# mediapipe 1.0.0 removed the legacy `mp.solutions` API, so this uses the
# Tasks face LANDMARKER and takes the landmark hull rather than a detector
# box. That is the better input anyway: a hull of 478 points tracks the jaw
# and hairline, where a detector box is square and swallows shoulders.
# The bundle is the repo's own models/face_landmarker.task -- the same
# artifact the board infers with, so no new dependency is introduced.
_LANDMARKER = None


def _landmarker():
    global _LANDMARKER
    if _LANDMARKER is None:
        from mediapipe.tasks import python as mpp
        from mediapipe.tasks.python import vision
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        _LANDMARKER = vision.FaceLandmarker.create_from_options(
            vision.FaceLandmarkerOptions(
                base_options=mpp.BaseOptions(
                    model_asset_path=os.path.join(
                        here, "models", "face_landmarker.task")),
                num_faces=4))
    return _LANDMARKER


def face_boxes(img):
    """Every face found, as (x0, y0, x1, y1) pixel boxes."""
    import mediapipe as mp
    h, w = img.shape[:2]
    res = _landmarker().detect(mp.Image(
        image_format=mp.ImageFormat.SRGB,
        data=cv2.cvtColor(img, cv2.COLOR_BGR2RGB)))
    out = []
    for lms in (res.face_landmarks or []):
        xs = [p.x * w for p in lms]
        ys = [p.y * h for p in lms]
        x, y = min(xs), min(ys)
        bw, bh = max(xs) - x, max(ys) - y
        out.append((int(x - bw * FACE_PAD), int(y - bh * FACE_PAD),
                    int(x + bw * (1 + FACE_PAD)),
                    int(y + bh * (1 + CHIN_PAD))))
    return out


def drawn_mask(img):
    """Pixels the analysis drew: a pegged channel beside a near-zero one."""
    b, g, r = (c.astype(np.int16) for c in cv2.split(img))
    hi = np.maximum(np.maximum(b, g), r)
    lo = np.minimum(np.minimum(b, g), r)
    m = ((hi > 195) & (lo < 95)).astype(np.uint8)
    # Grow by one pixel so a stroke keeps its antialiased edge and stays
    # legible instead of turning into a dotted line.
    return cv2.dilate(m, np.ones((3, 3), np.uint8), iterations=1)


def deidentify(path):
    img = cv2.imread(path)
    if img is None:
        return path, "unreadable"
    h, w = img.shape[:2]
    small = cv2.resize(img, (max(1, w // BLOCK), max(1, h // BLOCK)),
                       interpolation=cv2.INTER_AREA)
    wiped = cv2.GaussianBlur(
        cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST), (31, 31), 0)

    keep = np.zeros((h, w), np.uint8)
    boxes = face_boxes(img)
    for (x0, y0, x1, y1) in boxes:
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(w, x1), min(h, y1)
        if x1 > x0 and y1 > y0:
            cv2.ellipse(keep, ((x0 + x1) // 2, (y0 + y1) // 2),
                        ((x1 - x0) // 2, (y1 - y0) // 2), 0, 0, 360, 1, -1)
    # Feather the edge ONLY -- do not gain it up. MEASURED 2026-09-29: a
    # 61 px blur followed by a x1.6 gain pushed the mask out so far that the
    # shelves and the bed stayed sharp in every frame. The blur must soften
    # the boundary, never move it, so erode first by roughly the feather
    # radius and let the blur put it back.
    keep = cv2.erode(keep, np.ones((21, 21), np.uint8), iterations=1)
    keep = cv2.GaussianBlur(keep * 255, (31, 31), 0).astype(np.float32) / 255.0
    keep = keep[..., None]

    out = (img * keep + wiped * (1 - keep)).astype(np.uint8)
    d = drawn_mask(img).astype(bool)
    out[d] = img[d]
    cv2.imwrite(path, out)
    kept = float(keep.mean())
    return path, ("%d face(s), %.0f%% of frame kept sharp"
                  % (len(boxes), 100 * kept) if boxes else "NO FACE - all wiped")


if __name__ == "__main__":
    for p in sys.argv[1:]:
        name, how = deidentify(p)
        print("  %-34s %s" % (os.path.basename(name), how))
