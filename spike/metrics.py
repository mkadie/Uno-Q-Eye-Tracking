"""Timing and accuracy statistics.

Percentiles, not means. A pipeline that averages 20fps but stalls to 4fps
every second frame feels broken, and the mean hides that completely. p95
latency is what the user's hand-eye loop actually experiences.
"""

import numpy as np


class Timer(object):
    """Accumulates per-stage durations across frames."""

    def __init__(self):
        self.stages = {}

    def add(self, name, ms):
        self.stages.setdefault(name, []).append(float(ms))

    def add_all(self, d):
        for k, v in (d or {}).items():
            self.add(k, v)

    def summary(self):
        out = {}
        for k, v in self.stages.items():
            a = np.asarray(v, dtype=np.float64)
            if a.size == 0:
                continue
            out[k] = {
                "n": int(a.size),
                "mean": float(a.mean()),
                "p50": float(np.percentile(a, 50)),
                "p95": float(np.percentile(a, 95)),
                "max": float(a.max()),
            }
        return out

    def report(self, title="timings"):
        s = self.summary()
        if not s:
            return "  (no samples)"
        w = max(len(k) for k in s)
        lines = ["  %-*s %7s %8s %8s %8s" % (w, title, "mean", "p50", "p95", "max")]
        for k in sorted(s, key=lambda k: -s[k]["mean"]):
            v = s[k]
            lines.append("  %-*s %7.1f %8.1f %8.1f %8.1f"
                         % (w, k, v["mean"], v["p50"], v["p95"], v["max"]))
        return "\n".join(lines)


def fps_stats(frame_times):
    """frame_times: monotonic timestamps. Returns dict incl. worst-case fps."""
    t = np.asarray(frame_times, dtype=np.float64)
    if t.size < 2:
        return {"n": int(t.size), "fps_mean": 0.0, "fps_p5": 0.0}
    dt = np.diff(t)
    dt = dt[dt > 0]
    if dt.size == 0:
        return {"n": int(t.size), "fps_mean": 0.0, "fps_p5": 0.0}
    return {
        "n": int(t.size),
        "fps_mean": float(1.0 / dt.mean()),
        "fps_p50": float(1.0 / np.percentile(dt, 50)),
        # p5 fps = the slow tail. This is the number that determines whether
        # the cursor feels stable, not the mean.
        "fps_p5": float(1.0 / np.percentile(dt, 95)),
        "dt_p95_ms": float(np.percentile(dt, 95) * 1000.0),
    }
