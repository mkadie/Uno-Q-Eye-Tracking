"""Backend interface shared by the MediaPipe and LiteRT paths."""


class FaceResult(object):
    """One frame's worth of face landmarks.

    landmarks: (478, 3) float array, x/y normalised to [0,1] of the INFERENCE
               image, z in the model's arbitrary depth units.
    ok:        False means no face was found this frame.
    """

    __slots__ = ("landmarks", "ok", "score", "timings")

    def __init__(self, landmarks=None, ok=False, score=0.0, timings=None):
        self.landmarks = landmarks
        self.ok = ok
        self.score = score
        self.timings = timings or {}


class Backend(object):
    """Duck-typed interface. Implementations: MediaPipeBackend, LiteRTBackend."""

    name = "abstract"
    verified = False  # has this path been exercised against real weights?

    def detect(self, rgb):
        """rgb: (H, W, 3) uint8 RGB array. Returns FaceResult."""
        raise NotImplementedError

    def close(self):
        pass
