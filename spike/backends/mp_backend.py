"""Primary backend: MediaPipe Tasks FaceLandmarker.

Use mediapipe >= 1.0.0. Earlier 0.10.x releases published only macOS arm64 and
x86_64 Linux wheels, which is the origin of the widespread belief that
MediaPipe does not run on ARM64 Linux. 1.0.0 ships
mediapipe-1.0.0-py3-none-manylinux_2_28_aarch64.whl, so on Debian 12 (glibc
2.36) this is a plain pip install.

We run in IMAGE mode rather than VIDEO or LIVE_STREAM deliberately. VIDEO mode
adds internal temporal smoothing, which sounds desirable but is not: it would
sit underneath our own One Euro filter, and stacking two smoothers with
different time constants makes the tuning unpredictable and adds latency you
cannot see or control. Smooth once, at the top, where you can measure it.
"""

import os
import time

import numpy as np

from .base import Backend, FaceResult


class MediaPipeBackend(Backend):
    name = "mediapipe"
    verified = True

    def __init__(self, model_path, num_faces=1, min_detection_confidence=0.5,
                 min_presence_confidence=0.5, delegate="cpu"):
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision

        if not os.path.exists(model_path):
            raise FileNotFoundError(
                "face_landmarker task bundle not found at %s -- run setup.sh"
                % model_path)

        self._mp = mp
        base_opts = mp_python.BaseOptions(
            model_asset_path=model_path,
            # The QRB2210 has an Adreno GPU but no NPU. GPU delegate support on
            # this platform is unreliable; measure before trusting it. CPU is
            # the default for a reason.
            delegate=(mp_python.BaseOptions.Delegate.GPU if delegate == "gpu"
                      else mp_python.BaseOptions.Delegate.CPU),
        )
        opts = vision.FaceLandmarkerOptions(
            base_options=base_opts,
            running_mode=vision.RunningMode.IMAGE,
            num_faces=num_faces,
            min_face_detection_confidence=min_detection_confidence,
            min_face_presence_confidence=min_presence_confidence,
            output_face_blendshapes=False,       # we do not use them; they cost
            output_facial_transformation_matrixes=False,
        )
        self._lm = vision.FaceLandmarker.create_from_options(opts)
        self.version = getattr(mp, "__version__", "unknown")

    def detect(self, rgb, full=None):   # `full` ignored: DEAD on this board
        t0 = time.perf_counter()
        image = self._mp.Image(
            image_format=self._mp.ImageFormat.SRGB,
            data=np.ascontiguousarray(rgb))
        res = self._lm.detect(image)
        t1 = time.perf_counter()

        timings = {"infer_ms": (t1 - t0) * 1000.0}
        if not res.face_landmarks:
            return FaceResult(ok=False, timings=timings)

        lms = res.face_landmarks[0]
        arr = np.empty((len(lms), 3), dtype=np.float32)
        for i, p in enumerate(lms):
            arr[i, 0] = p.x
            arr[i, 1] = p.y
            arr[i, 2] = p.z
        return FaceResult(landmarks=arr, ok=True, score=1.0, timings=timings)

    def close(self):
        try:
            self._lm.close()
        except Exception:
            pass
