"""Contingency backend: raw LiteRT/TFLite, no MediaPipe runtime.

*** VERIFICATION STATUS: VERIFIED ON HARDWARE 2026-08-08 ***

This is now the PRIMARY path on the UNO Q, not the contingency. The mediapipe
wheel installs and imports on this board and then dies with SIGILL the moment
it executes: the prebuilt aarch64 binary requires ARMv8.1 LSE atomics and the
QRB2210's core is ARMv8.0. There is no flag for that. See REPLICATION.md.

Verified by bin/facecheck against a real face at 584 mm: 10/10 geometry checks,
iris ring circularity cv 0.079/0.082, iris diameter over eye width 0.419/0.418,
detection on 5/5 frames at all 21 focus values swept.

One bug had to be fixed to get there, and it is instructive: LM_SIZE was 192,
taken from MediaPipe's older standalone face_landmark.tflite. The
face_landmarker.task bundle ships a 256x256 landmark model. The size is now
read from the model at construction time -- see __init__ -- because a constant
that must agree with a file is a constant that will eventually disagree with
it, and this one only failed once detection SUCCEEDED, which is the worst
possible time to find out.

Pipeline, mirroring what MediaPipe does internally:
  1. BlazeFace short-range detector, 128x128 input -> 896 anchor boxes
  2. Sigmoid scores, decode boxes + 6 keypoints, NMS
  3. Rotate/expand the winning box into an aligned face crop at the landmark
     model's own input size (256 for this bundle), using the two eye keypoints
     to establish roll
  4. Face landmark model on that crop -> 478 landmarks
  5. Un-rotate landmarks back into original frame coordinates
"""

import time

import numpy as np

from .base import Backend, FaceResult

DET_SIZE = 128

# Fallback only. The real value is read from the model at construction time --
# see LiteRTBackend.__init__. Hardcoding it is what made this module unusable:
# it was written as 192, which is MediaPipe's older standalone
# face_landmark.tflite, but the face_landmarker.task bundle ships a 256x256
# landmark model. set_tensor would raise on the first frame containing a face,
# so the failure only appeared once detection *worked*.
LM_SIZE = 256

ROI_SCALE = 1.5      # MediaPipe expands the detection box by this before crop
MIN_SCORE = 0.5
NMS_IOU = 0.3

# Tracking. Running the 128x128 detector on every frame costs ~11 ms and is
# almost always redundant: between consecutive frames the face has barely
# moved, so the previous frame's landmarks already say where to crop. This is
# what MediaPipe's own graph does -- detect once, then track, re-detecting only
# on loss. Measured saving here: ~11 ms of a ~55 ms budget.
REDETECT_EVERY = 30   # forced re-detection, bounds slow ROI drift
MAX_SIZE_JUMP = 0.45  # frame-to-frame face size change treated as lost track


def _sigmoid(x):
    # Clip at 60, not 100: the detector's logits are float32, and exp(100) is
    # 2.7e43, well past float32's 3.4e38 max, so a +-100 clip overflows and
    # warns on every frame. sigmoid(+-60) is already 0.0/1.0 to full float32
    # precision, so nothing is lost by clipping tighter.
    return 1.0 / (1.0 + np.exp(-np.clip(x, -60.0, 60.0)))


def generate_anchors():
    """BlazeFace short-range SSD anchors: 512 at stride 8, 384 at stride 16."""
    anchors = []
    for stride, count in ((8, 2), (16, 6)):
        fm = DET_SIZE // stride
        for y in range(fm):
            for x in range(fm):
                cx = (x + 0.5) / fm
                cy = (y + 0.5) / fm
                for _ in range(count):
                    anchors.append((cx, cy, 1.0, 1.0))
    return np.array(anchors, dtype=np.float32)   # (896, 4)


def decode_boxes(raw, anchors):
    """raw: (896, 16) -> boxes (896, 4) as xmin,ymin,xmax,ymax in [0,1]."""
    scale = float(DET_SIZE)
    cx = raw[:, 0] / scale * anchors[:, 2] + anchors[:, 0]
    cy = raw[:, 1] / scale * anchors[:, 3] + anchors[:, 1]
    w = raw[:, 2] / scale * anchors[:, 2]
    h = raw[:, 3] / scale * anchors[:, 3]
    return np.stack([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], axis=-1)


def decode_keypoints(raw, anchors):
    """6 keypoints per anchor: right eye, left eye, nose, mouth, right/left ear."""
    scale = float(DET_SIZE)
    kp = raw[:, 4:16].reshape(-1, 6, 2)
    kx = kp[:, :, 0] / scale * anchors[:, 2:3] + anchors[:, 0:1]
    ky = kp[:, :, 1] / scale * anchors[:, 3:4] + anchors[:, 1:2]
    return np.stack([kx, ky], axis=-1)


def nms(boxes, scores, iou_thresh=NMS_IOU):
    idx = np.argsort(scores)[::-1]
    keep = []
    while idx.size:
        i = idx[0]
        keep.append(i)
        if idx.size == 1:
            break
        xx1 = np.maximum(boxes[i, 0], boxes[idx[1:], 0])
        yy1 = np.maximum(boxes[i, 1], boxes[idx[1:], 1])
        xx2 = np.minimum(boxes[i, 2], boxes[idx[1:], 2])
        yy2 = np.minimum(boxes[i, 3], boxes[idx[1:], 3])
        inter = np.maximum(0, xx2 - xx1) * np.maximum(0, yy2 - yy1)
        a_i = (boxes[i, 2] - boxes[i, 0]) * (boxes[i, 3] - boxes[i, 1])
        a_r = ((boxes[idx[1:], 2] - boxes[idx[1:], 0]) *
               (boxes[idx[1:], 3] - boxes[idx[1:], 1]))
        iou = inter / np.maximum(a_i + a_r - inter, 1e-9)
        idx = idx[1:][iou <= iou_thresh]
    return keep


def _letterbox(img, size):
    """Resize preserving aspect, pad to square. Returns (out, scale, dx, dy)."""
    import cv2
    h, w = img.shape[:2]
    s = float(size) / max(h, w)
    nh, nw = int(round(h * s)), int(round(w * s))
    r = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
    out = np.zeros((size, size, 3), dtype=img.dtype)
    dy, dx = (size - nh) // 2, (size - nw) // 2
    out[dy:dy + nh, dx:dx + nw] = r
    return out, s, dx, dy


class LiteRTBackend(Backend):
    name = "litert"
    verified = True      # bin/facecheck, 2026-08-08, 10/10 geometry checks

    def __init__(self, detector_path, landmark_path, num_threads=4,
                 detect_input="both"):
        if detect_input not in ("colour", "gray", "both"):
            raise ValueError("detect_input must be colour|gray|both, got %r"
                             % (detect_input,))
        try:
            from ai_edge_litert.interpreter import Interpreter
        except ImportError:
            from tflite_runtime.interpreter import Interpreter

        self.det = Interpreter(model_path=detector_path,
                               num_threads=num_threads)
        self.det.allocate_tensors()
        self.lm = Interpreter(model_path=landmark_path,
                              num_threads=num_threads)
        self.lm.allocate_tensors()
        self.anchors = generate_anchors()
        # WHAT THE DETECTOR IS FED. "colour" | "gray" | "both".
        #
        # MEASURED 2026-10-04: under the red lamp -- the lamp that makes the
        # gaze point 3.2x steadier, so a lamp worth keeping -- the face is
        # nearly monochromatic in the wrong channel and the detector mostly
        # finds nothing. Brightening does NOT fix it (x2 and x3.5 both still
        # failed). Converting to grayscale found a face immediately, on four
        # out of four stashed red-lamp frames where colour found none.
        #
        # But grayscale is NOT free, and the same sweep is why this is not a
        # plain swap: on two BRIGHT stills, colour found a face and gray did
        # not. So "gray" is strictly better in one lighting and strictly worse
        # in another, which is an argument for neither as the default.
        #
        # "both" is the resolution: run colour, and only if it finds nothing
        # retry the same frame in gray. MEASURED over 18 stashed stills --
        # colour 10, gray 13, BOTH 15 -- and "both" was a strict superset of
        # colour on every single row, which is the property it was built for.
        #
        # THE COST IS NOT FREE AND IT IS NOT SMALL. On a frame where nothing
        # is found, so the retry always runs, detect() went 24.0 -> 48.7 ms
        # median (p95 39.1 -> 67.3). A doubling, not the ~11 ms the comment
        # below would have led you to guess -- that figure was measured
        # another way and does not transfer. But the cost is paid ONLY on
        # frames that returned nothing, where there was nothing to be late
        # for; when colour finds the face the retry never runs and the cost is
        # exactly zero. The visible effect is that recovery from a lost track
        # polls at half speed. That is the right place to spend it.
        #
        # The LANDMARK model keeps full colour in every mode. It is the stage
        # that has to localise an iris edge, it was never the stage that
        # failed, and nothing here measured that starving it is safe.
        self.detect_input = detect_input
        self._di = self.det.get_input_details()
        self._do = self.det.get_output_details()
        self._li = self.lm.get_input_details()
        self._lo = self.lm.get_output_details()

        # Take the input geometry from the models rather than from constants.
        # Anchor decoding is only valid for the detector resolution the anchors
        # were generated for, so a mismatch must fail loudly here rather than
        # silently decode every box against the wrong grid.
        det_h, det_w = (int(v) for v in self._di[0]["shape"][1:3])
        if (det_h, det_w) != (DET_SIZE, DET_SIZE):
            raise ValueError(
                "detector expects %dx%d but the anchor grid is built for %d. "
                "Regenerate anchors before trusting any output."
                % (det_h, det_w, DET_SIZE))
        self.lm_size = int(self._li[0]["shape"][1])
        if self.lm_size != int(self._li[0]["shape"][2]):
            raise ValueError("landmark model input is not square")

        # Tracking state.
        self._prev_px = None      # previous frame landmarks, source pixels
        self._since_det = 10 ** 9
        self._roi_ratio = None    # detector ROI side / landmark bbox side
        # detector_gray_hits is the figure that says whether the gray retry
        # is earning its place in the field. If it stays 0 across a session,
        # the lighting never needed it.
        self.stats = {"detector_frames": 0, "tracked_frames": 0,
                      "detector_colour_hits": 0, "detector_gray_hits": 0}

    def _detect_once(self, rgb, gray):
        img, s, dx, dy = _letterbox(rgb, DET_SIZE)
        if gray:
            # AFTER the letterbox, so this costs 128x128 pixels instead of
            # 1280x720 -- and in "both" mode the letterbox is shared, so the
            # retry is one more 128x128 invoke and nothing else.
            import cv2
            g = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
            img = cv2.cvtColor(g, cv2.COLOR_GRAY2RGB)
        inp = (img.astype(np.float32) / 127.5) - 1.0
        self.det.set_tensor(self._di[0]["index"], inp[None])
        self.det.invoke()

        outs = [self.det.get_tensor(o["index"])[0] for o in self._do]
        # Output order is not guaranteed across model revisions; identify by
        # trailing dimension rather than by position.
        raw = next(o for o in outs if o.shape[-1] == 16)
        logits = next(o for o in outs if o.shape[-1] == 1).ravel()

        scores = _sigmoid(logits)
        good = np.where(scores >= MIN_SCORE)[0]
        if good.size == 0:
            return None

        boxes = decode_boxes(raw[good], self.anchors[good])
        kps = decode_keypoints(raw[good], self.anchors[good])
        keep = nms(boxes, scores[good])
        if not keep:
            return None
        best = keep[0]

        # Undo letterboxing back into source pixel coordinates.
        h, w = rgb.shape[:2]
        def unpad(pt):
            return np.array([(pt[0] * DET_SIZE - dx) / s,
                             (pt[1] * DET_SIZE - dy) / s])
        box = np.array([unpad(boxes[best][:2]), unpad(boxes[best][2:])])
        kp = np.array([unpad(p) for p in kps[best]])
        return box, kp, float(scores[good][best])

    def _run_detector(self, rgb):
        """Detector per `detect_input`, counting which input actually found it."""
        if self.detect_input != "gray":
            hit = self._detect_once(rgb, False)
            if hit is not None:
                self.stats["detector_colour_hits"] += 1
                return hit
            if self.detect_input == "colour":
                return None
        hit = self._detect_once(rgb, True)
        if hit is not None:
            self.stats["detector_gray_hits"] += 1
        return hit

    @staticmethod
    def _bbox_side(px):
        lo = px.min(axis=0)
        hi = px.max(axis=0)
        return float(max(hi[0] - lo[0], hi[1] - lo[1])), (lo + hi) / 2.0

    def _roi_from_landmarks(self, px):
        """Derive the next crop from the previous frame's landmarks.

        The scale factor is not guessed. Every time the detector runs we record
        the ratio between the crop side it produced and the side of the
        landmark bounding box for the same face, then reuse that ratio while
        tracking. A hardcoded constant here would frame the face slightly
        differently from the detector path, and the landmark model -- trained
        on one particular framing -- would quietly get worse the longer
        tracking ran, which is the hardest kind of bug to notice.
        """
        side, centre = self._bbox_side(px)
        ratio = self._roi_ratio if self._roi_ratio else ROI_SCALE
        d = px[473] - px[468]        # left iris centre - right iris centre
        angle = float(np.degrees(np.arctan2(d[1], d[0])))
        return centre, side * ratio, angle

    def _crop_from(self, rgb, centre, side, angle):
        import cv2
        L = self.lm_size
        cx, cy = float(centre[0]), float(centre[1])
        M = cv2.getRotationMatrix2D((cx, cy), angle, 1.0)
        M[0, 2] += L / 2.0 - cx
        M[1, 2] += L / 2.0 - cy
        S = L / max(side, 1e-6)
        M = np.array([[S, 0, L * (1 - S) / 2.0],
                      [0, S, L * (1 - S) / 2.0]]) @ np.vstack([M, [0, 0, 1]])
        crop = cv2.warpAffine(rgb, M, (L, L), flags=cv2.INTER_LINEAR)
        return crop, M

    def _run_landmarks(self, crop):
        inp = crop.astype(np.float32) / 255.0
        self.lm.set_tensor(self._li[0]["index"], inp[None])
        self.lm.invoke()
        outs = [self.lm.get_tensor(o["index"]) for o in self._lo]
        lm_raw = next(o for o in outs if o.size >= 478 * 3)
        return lm_raw.reshape(-1, 3)[:478].astype(np.float32)

    def _aligned_crop(self, rgb, box, kp):
        """Rotate the face upright and crop to LM_SIZE.

        Roll comes from the two eye keypoints (0 = right eye, 1 = left eye).
        Feeding an un-rotated crop to the landmark model degrades it badly --
        it was trained on aligned faces.
        """
        import cv2
        r_eye, l_eye = kp[0], kp[1]
        d = l_eye - r_eye
        angle = np.degrees(np.arctan2(d[1], d[0]))
        cx, cy = (box[0] + box[1]) / 2.0
        side = float(np.max(box[1] - box[0])) * ROI_SCALE

        L = self.lm_size
        M = cv2.getRotationMatrix2D((float(cx), float(cy)), angle, 1.0)
        M[0, 2] += L / 2.0 - cx
        M[1, 2] += L / 2.0 - cy
        S = L / side
        M = np.array([[S, 0, L * (1 - S) / 2.0],
                      [0, S, L * (1 - S) / 2.0]]) @ np.vstack([M, [0, 0, 1]])
        crop = cv2.warpAffine(rgb, M, (L, L), flags=cv2.INTER_LINEAR)
        return crop, M

    def detect(self, rgb, full=None):
        """Detect a face and return 478 landmarks, normalised to `rgb`.

        `full` is an optional higher-resolution version of the same frame. When
        given, detection and tracking still run on `rgb` (cheap), but the
        landmark crop is taken from `full` -- so the fixed 256x256 landmark
        input is filled with real pixels instead of upscaled ones.

        Why it matters here, MEASURED 2026-08-16: iris radius is 8.3 px at
        1280x720 against 13.2 px at 1920x1080, and Gate 1c's vertical signal is
        nearly absent (r_y = 0.22) -- which is what too-few iris pixels looks
        like, vertical iris excursion being the smaller axis. Both models have
        FIXED input sizes, so cropping from full res costs no inference time;
        only the capture and the warp get more expensive.

        Landmarks come back in `rgb` coordinates either way, so callers and the
        saved normalisation are unaffected.
        """
        t0 = time.perf_counter()
        h, w = rgb.shape[:2]
        # Scale between the detection image and the crop source.
        k = 1.0 if full is None else float(full.shape[1]) / float(w)

        use_tracking = (self._prev_px is not None
                        and self._since_det < REDETECT_EVERY)
        det_ms = 0.0
        score = 1.0
        box = None

        if use_tracking:
            centre, side, angle = self._roi_from_landmarks(self._prev_px)
            prev_side, _ = self._bbox_side(self._prev_px)
        else:
            det = self._run_detector(rgb)
            det_ms = (time.perf_counter() - t0) * 1000.0
            if det is None:
                self._prev_px = None
                self._since_det = 10 ** 9
                return FaceResult(ok=False, timings={
                    "detect_ms": det_ms, "landmark_ms": 0.0,
                    "infer_ms": det_ms})
            box, kp, score = det
            r_eye, l_eye = kp[0], kp[1]
            d = l_eye - r_eye
            angle = float(np.degrees(np.arctan2(d[1], d[0])))
            centre = (box[0] + box[1]) / 2.0
            side = float(np.max(box[1] - box[0])) * ROI_SCALE
            prev_side = None
            self._since_det = 0
            self.stats["detector_frames"] += 1

        t1 = time.perf_counter()
        # Crop from the high-res frame when one was supplied, scaling the ROI
        # into its coordinates. Everything after this is mapped straight back
        # into `rgb` space, so tracking, the bounds checks and the returned
        # normalisation all stay in one coordinate system.
        src = rgb if full is None else full
        crop, M = self._crop_from(
            src, (centre[0] * k, centre[1] * k), side * k, angle)
        pts = self._run_landmarks(crop)

        Minv = np.linalg.inv(np.vstack([M, [0, 0, 1]]))
        xy1 = np.concatenate([pts[:, :2], np.ones((pts.shape[0], 1))], axis=1)
        back = (Minv @ xy1.T).T[:, :2] / k
        t2 = time.perf_counter()

        # Calibrate the tracking scale off the detector path, and validate the
        # tracked path against it. A tracked ROI that has drifted produces
        # landmarks that are still 478 points in a face-like arrangement, just
        # progressively mis-scaled -- so check rather than trust.
        new_side, _ = self._bbox_side(back)
        if not use_tracking and new_side > 1e-6:
            r = side / new_side
            self._roi_ratio = r if self._roi_ratio is None else (
                0.7 * self._roi_ratio + 0.3 * r)
        lost = False
        if use_tracking:
            if prev_side and abs(new_side - prev_side) / prev_side > MAX_SIZE_JUMP:
                lost = True
            inb = np.mean((back[:, 0] > -0.1 * w) & (back[:, 0] < 1.1 * w) &
                          (back[:, 1] > -0.1 * h) & (back[:, 1] < 1.1 * h))
            if inb < 0.9:
                lost = True
            self.stats["tracked_frames"] += 1

        if lost:
            # Do not return a tracked result we do not believe. Drop the state
            # so the next frame pays for a detector run and starts clean.
            self._prev_px = None
            self._since_det = 10 ** 9
            ms = (t2 - t0) * 1000.0
            return FaceResult(ok=False, timings={
                "detect_ms": det_ms, "landmark_ms": (t2 - t1) * 1000.0,
                "infer_ms": ms})

        self._prev_px = back
        self._since_det += 1

        out = np.empty_like(pts)
        out[:, 0] = back[:, 0] / w
        out[:, 1] = back[:, 1] / h
        out[:, 2] = pts[:, 2] / self.lm_size

        return FaceResult(landmarks=out, ok=True, score=score, timings={
            "detect_ms": det_ms,
            "landmark_ms": (t2 - t1) * 1000.0,
            "infer_ms": (t2 - t0) * 1000.0,
        })
