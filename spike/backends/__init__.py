"""Backend selection with graceful fallback."""

import os
import subprocess
import sys

from .base import Backend, FaceResult

# Smoke test run in a CHILD process -- see mediapipe_runs() for why that is not
# optional. Constructs a landmarker and runs one frame, which is the point at
# which the native library is actually executed.
_MP_SMOKE = r"""
import sys
import numpy as np
try:
    import mediapipe as mp
    from mediapipe.tasks import python as t
    from mediapipe.tasks.python import vision as v
    lm = v.FaceLandmarker.create_from_options(
        v.FaceLandmarkerOptions(
            base_options=t.BaseOptions(model_asset_path=sys.argv[1]),
            num_faces=1))
    lm.detect(mp.Image(image_format=mp.ImageFormat.SRGB,
                       data=np.zeros((64, 64, 3), np.uint8)))
except BaseException as e:
    sys.stderr.write("%s: %s" % (type(e).__name__, e))
    sys.exit(2)
sys.exit(0)
"""


def mediapipe_runs(model_path=None, timeout=90):
    """Can MediaPipe actually EXECUTE here -- not merely import?

    This has to be a subprocess, and the reason is worth stating plainly
    because it is not obvious and it cost a Gate 0.

    The prebuilt mediapipe aarch64 wheel is compiled with ARMv8.1 LSE atomics.
    The UNO Q's core is ARMv8.0 and has no LSE, so the moment native code runs
    the process is killed with SIGILL. That is not a Python exception. No
    try/except can catch it, because there is no stack left to unwind -- the
    interpreter is simply gone.

    Worse, `import mediapipe` SUCCEEDS on such a machine: libmediapipe.so is
    loaded lazily, so nothing native has executed yet. An import-based check
    therefore reports a healthy primary backend that will kill the program on
    the first frame containing a face.

    Returns (ok, detail).
    """
    model_path = model_path or DEFAULT_TASK
    if not os.path.exists(model_path):
        return False, "model bundle missing at %s" % model_path
    try:
        p = subprocess.run([sys.executable, "-c", _MP_SMOKE, model_path],
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "smoke test timed out after %ss" % timeout
    except Exception as e:                      # interpreter missing, etc.
        return False, "could not run smoke test: %s" % e

    if p.returncode == 0:
        return True, "executes"
    if p.returncode < 0:
        # Killed by a signal. SIGILL (-4) is the LSE case; SIGABRT (-6) is the
        # fail-fast guard catching it first.
        detail = "killed by signal %d" % (-p.returncode)
        if "lse" in (p.stderr or "").lower():
            detail += " -- binary needs ARMv8.1 LSE atomics, this CPU lacks them"
        return False, detail
    err = (p.stderr or "").strip().splitlines()
    msg = err[-1] if err else "exit %d" % p.returncode
    if "lse" in (p.stderr or "").lower():
        msg = ("needs ARMv8.1 LSE atomics, this CPU lacks them (%s)"
               % msg.split(":")[0])
    return False, msg

DEFAULT_TASK = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "models", "face_landmarker.task")


def available():
    """Report which inference paths this machine can actually run."""
    out = {}
    try:
        import mediapipe
        ver = getattr(mediapipe, "__version__", "present")
        # Importing is not evidence of anything. Make it run.
        ok, detail = mediapipe_runs()
        out["mediapipe"] = ver if ok else "UNAVAILABLE: %s imports but %s" % (
            ver, detail)
    except Exception as e:
        out["mediapipe"] = "UNAVAILABLE: %s" % e
    try:
        import ai_edge_litert
        out["ai_edge_litert"] = getattr(ai_edge_litert, "__version__", "present")
    except Exception as e:
        out["ai_edge_litert"] = "UNAVAILABLE: %s" % e
    try:
        import tflite_runtime
        out["tflite_runtime"] = getattr(tflite_runtime, "__version__", "present")
    except Exception as e:
        out["tflite_runtime"] = "UNAVAILABLE: %s" % e
    return out


def create(prefer="mediapipe", model_path=None, **kw):
    """Build a backend, falling back if the preferred one will not load."""
    model_path = model_path or DEFAULT_TASK
    errors = []

    if prefer == "mediapipe":
        # Gate on the subprocess smoke test BEFORE constructing anything in
        # this process. Constructing MediaPipeBackend on a CPU without LSE does
        # not raise -- it terminates the interpreter, taking the caller and any
        # unsaved measurement data with it.
        ok, detail = mediapipe_runs(model_path)
        if ok:
            try:
                from .mp_backend import MediaPipeBackend
                return MediaPipeBackend(model_path, **kw)
            except Exception as e:
                errors.append("mediapipe: %s" % e)
        else:
            errors.append("mediapipe: %s" % detail)

    try:
        from .litert_backend import LiteRTBackend
        base = os.path.dirname(model_path)
        det = os.path.join(base, "bundle", "face_detector.tflite")
        lmk = os.path.join(base, "bundle", "face_landmarks_detector.tflite")
        # Pass kw through. It used to be dropped here, which meant
        # num_threads from config.toml was silently ignored and the backend
        # always ran its default of 4 -- the exact setting measured to be
        # slower than 3 on this board.
        return LiteRTBackend(det, lmk, **kw)
    except Exception as e:
        errors.append("litert: %s" % e)

    raise RuntimeError("no usable backend.\n  " + "\n  ".join(errors))
