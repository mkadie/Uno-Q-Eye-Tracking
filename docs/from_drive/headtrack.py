#!/usr/bin/env python3
"""
R.O.A.R. head tracker — Arduino Uno Q (Linux side).
Tracks the printed ArUco tag (DICT_4X4_50) on glasses/hat, 5-point calibration,
emits absolute pointer over the link to the RP2350 HID bridge.

Link protocol (ASCII lines, 115200):
  UnoQ -> bridge : "M x y"  (x,y 0..32767 absolute)   "L" (lost)   "K" (dwell click)
  bridge -> UnoQ : "CAL" (calibrate)  "REC" (recenter)  "PAUSE" (toggle)

Usage:
  python3 headtrack.py --link /dev/ttyUSB0          # USB-UART dongle on the hub -> bridge RX/TX
  python3 headtrack.py --link bridge                # App Lab Bridge -> STM32 sketch -> Serial1 (D0/D1)
  python3 headtrack.py --link stdout --preview      # bench, no bridge
  python3 headtrack.py --link uinput --dwell 1.0    # local: virtual abs mouse on the Uno Q itself
                                                    #   kill -USR1 <pid> = calibrate, -USR2 = recenter
"""
import argparse, json, math, os, signal, subprocess, sys, threading, time
import numpy as np
import cv2
cv2.setNumThreads(1)   # leave the other A53 cores to the Talker + Piper

FULL = 32767
CAL_POINTS = [(0.5, 0.5), (0.15, 0.15), (0.85, 0.15), (0.85, 0.85), (0.15, 0.85)]  # 5-pt, center first
SETTLE_S, COLLECT_S, MIN_SAMPLES, MAX_JITTER_PX, RETRIES = 0.5, 0.7, 8, 3.0, 2

# ---------------------------------------------------------------- link
class Link:
    def __init__(self, spec, on_cmd):
        self.on_cmd, self.kind = on_cmd, spec
        if spec == "stdout":
            self.w = lambda s: print(s, flush=True)
        elif spec == "uinput":
            # Virtual absolute pointer (same shape as a QEMU USB tablet, which libinput/X/Wayland
            # treat as an absolute mouse). Any app on the Uno Q's display sees a normal cursor.
            from evdev import UInput, AbsInfo, ecodes as e
            self.e = e
            self.ui = UInput({e.EV_KEY: [e.BTN_LEFT, e.BTN_RIGHT, e.BTN_MIDDLE],
                              e.EV_REL: [e.REL_WHEEL],
                              e.EV_ABS: [(e.ABS_X, AbsInfo(0, 0, FULL, 0, 0, 0)),
                                         (e.ABS_Y, AbsInfo(0, 0, FULL, 0, 0, 0))]},
                             name="ROAR headtrack", vendor=0x1209, product=0x0001)
            self.w = self._ui
        elif spec == "bridge":
            from arduino.app_utils import Bridge          # App Lab runtime
            Bridge.provide("rp_cmd", lambda s: on_cmd(str(s).strip()))
            self.w = lambda s: Bridge.notify("emit", s)
        else:
            import serial
            self.ser = serial.Serial(spec, 115200, timeout=0.05)
            self.w = lambda s: self.ser.write((s + "\n").encode())
            threading.Thread(target=self._rx, daemon=True).start()
    def _ui(self, line):
        e, ui, p = self.e, self.ui, line.split()
        if p[0] == "M":
            ui.write(e.EV_ABS, e.ABS_X, int(p[1])); ui.write(e.EV_ABS, e.ABS_Y, int(p[2])); ui.syn()
        elif p[0] == "K":
            ui.write(e.EV_KEY, e.BTN_LEFT, 1); ui.syn(); time.sleep(0.03)
            ui.write(e.EV_KEY, e.BTN_LEFT, 0); ui.syn()
    def _rx(self):
        buf = b""
        while True:
            buf += self.ser.read(64)
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if line.strip(): self.on_cmd(line.decode(errors="ignore").strip())
    def move(self, nx, ny):
        self.w("M %d %d" % (int(np.clip(nx, 0, 1) * FULL), int(np.clip(ny, 0, 1) * FULL)))
    def send(self, s): self.w(s)

# ---------------------------------------------------------------- camera
def lock_camera(dev):
    # C920x: fixed focus / exposure / WB so the tag's pixels don't shift with auto loops.
    # Control names differ across kernels; set both spellings, ignore failures.
    for c in ["focus_automatic_continuous=0", "focus_auto=0", "focus_absolute=30",
              "auto_exposure=1", "exposure_auto=1", "exposure_time_absolute=156", "exposure_absolute=156",
              "white_balance_automatic=0", "white_balance_temperature_auto=0",
              "exposure_dynamic_framerate=0", "power_line_frequency=2"]:
        subprocess.run(["v4l2-ctl", "-d", dev, "-c", c], capture_output=True)

def open_camera(dev, w, h, fps):
    cap = cv2.VideoCapture(dev, cv2.CAP_V4L2)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, w); cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
    cap.set(cv2.CAP_PROP_FPS, fps); cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    lock_camera(dev)
    return cap

# ---------------------------------------------------------------- tag detection with ROI
class TagTracker:
    def __init__(self, marker_id):
        p = cv2.aruco.DetectorParameters()
        p.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX   # sub-px centroid = low jitter
        p.adaptiveThreshWinSizeMax = 33
        self.det = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50), p)
        self.id, self.roi, self.misses = marker_id, None, 0
    def find(self, gray):
        if self.roi is not None:
            x0, y0, x1, y1 = self.roi
            hit = self._detect(gray[y0:y1, x0:x1], x0, y0)
            if hit is not None: return hit
            self.misses += 1
            if self.misses < 3: return None               # brief occlusion: don't pay full-frame cost yet
        return self._detect(gray, 0, 0)
    def _detect(self, img, ox, oy):
        corners, ids, _ = self.det.detectMarkers(img)
        if ids is None: return None
        for c, i in zip(corners, ids.ravel()):
            if i != self.id: continue
            c = c.reshape(4, 2) + (ox, oy)
            ctr, side = c.mean(0), float(np.linalg.norm(c[0] - c[2]) / 1.414)
            m = int(side * 2.5)
            self.roi = (max(0, int(ctr[0]) - m), max(0, int(ctr[1]) - m), int(ctr[0]) + m, int(ctr[1]) + m)
            self.misses = 0
            return ctr, side
        return None

# ---------------------------------------------------------------- filtering
class OneEuro:
    def __init__(self, mincut=1.0, beta=0.02, dcut=1.0):
        self.mc, self.b, self.dc, self.x, self.dx, self.t = mincut, beta, dcut, None, 0.0, None
    @staticmethod
    def _a(cut, dt): r = 2 * math.pi * cut * dt; return r / (r + 1)
    def __call__(self, x, t):
        if self.x is None: self.x, self.t = x, t; return x
        dt = max(t - self.t, 1e-3); self.t = t
        dx = (x - self.x) / dt
        self.dx = self.dx + self._a(self.dc, dt) * (dx - self.dx)
        cut = self.mc + self.b * abs(self.dx)
        self.x = self.x + self._a(cut, dt) * (x - self.x)
        return self.x

# ---------------------------------------------------------------- calibration model
class Calib:
    """screen_norm = A @ [u, v, 1]. Affine, least squares over 5 points (3 needed)."""
    def __init__(self, A=None): self.A = A
    def fit(self, feats, targets):
        X = np.hstack([np.asarray(feats), np.ones((len(feats), 1))])
        A, *_ = np.linalg.lstsq(X, np.asarray(targets), rcond=None)
        self.A = A.T
        pred = X @ A
        return float(np.sqrt(((pred - targets) ** 2).sum(1).mean()))      # RMS, normalized screen units
    def map(self, uv): return self.A @ np.array([uv[0], uv[1], 1.0])
    def recenter(self, uv, target=(0.5, 0.5)):                          # 1-pt drift fix, keeps gain
        self.A[:, 2] += np.asarray(target) - self.map(uv)
    def save(self, path, meta):
        json.dump({"A": self.A.tolist(), **meta}, open(path, "w"), indent=1)
    @classmethod
    def load(cls, path):
        try: return cls(np.array(json.load(open(path))["A"]))
        except Exception: return cls()

# ---------------------------------------------------------------- app
class App:
    def __init__(s, a):
        s.a, s.cmds = a, []
        s.link = Link(a.link, s.cmds.append)
        s.cap = open_camera(a.dev, a.width, a.height, a.fps)
        s.tag = TagTracker(a.id)
        s.cal = Calib.load(a.calfile)
        s.fx, s.fy = OneEuro(a.mincut, a.beta), OneEuro(a.mincut, a.beta)
        s.paused, s.lost_sent, s.last = False, False, None
        s.dwell_anchor, s.dwell_t0 = None, 0.0
        signal.signal(signal.SIGUSR1, lambda *_: s.cmds.append("CAL"))
        signal.signal(signal.SIGUSR2, lambda *_: s.cmds.append("REC"))

    def grab(s):
        ok, frame = s.cap.read()
        if not ok: return None, None
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        return s.tag.find(gray), frame

    def calibrate(s):
        print("calibrating", flush=True)
        feats, tgts = [], []
        for tx, ty in CAL_POINTS:
            for attempt in range(RETRIES + 1):
                s.link.move(tx, ty)                      # cursor IS the target — works on any host
                t0, samples = time.time(), []
                while time.time() - t0 < SETTLE_S + COLLECT_S:
                    hit, _ = s.grab()
                    if hit and time.time() - t0 >= SETTLE_S: samples.append(hit[0])
                pts = np.array(samples)
                if len(pts) >= MIN_SAMPLES and pts.std(0).max() <= MAX_JITTER_PX:
                    feats.append(np.median(pts, 0)); tgts.append((tx, ty)); break
                print("  point %s unstable (%d samples) retry" % ((tx, ty), len(pts)), flush=True)
        if len(feats) < 4:
            print("calibration failed: %d/5 points" % len(feats), flush=True); return False
        span = np.ptp(np.array(feats), 0)
        rms = s.cal.fit(np.array(feats), np.array(tgts))
        s.cal.save(s.a.calfile, {"id": s.a.id, "res": [s.a.width, s.a.height], "rms": rms,
                                 "span_px": span.tolist(), "t": time.time()})
        # span = tag travel the user produced. Small span = high gain = user with limited range. That's fine.
        print("calibrated: rms %.3f of screen, tag span %.0fx%.0f px" % (rms, *span), flush=True)
        s.fx, s.fy = OneEuro(s.a.mincut, s.a.beta), OneEuro(s.a.mincut, s.a.beta)
        return True

    def handle(s):
        while s.cmds:
            c = s.cmds.pop(0)
            if c == "CAL": s.calibrate()
            elif c == "REC" and s.last is not None and s.cal.A is not None: s.cal.recenter(s.last)
            elif c == "PAUSE": s.paused = not s.paused

    def dwell(s, p, t):
        if s.a.dwell <= 0: return
        if s.dwell_anchor is None or np.hypot(*(p - s.dwell_anchor)) > s.a.dwell_r:
            s.dwell_anchor, s.dwell_t0 = p, t
        elif t - s.dwell_t0 >= s.a.dwell:
            s.link.send("K"); s.dwell_t0 = t + 0.6          # refractory

    def run(s):
        if s.cal.A is None or s.a.cal: s.calibrate()
        n, tfps = 0, time.time()
        while True:
            s.handle()
            hit, frame = s.grab()
            t = time.time()
            if hit is None:
                if not s.lost_sent: s.link.send("L"); s.lost_sent = True
            else:
                s.lost_sent = False
                s.last = hit[0]
                if s.cal.A is not None and not s.paused:
                    p = s.cal.map(hit[0])
                    p = np.array([s.fx(p[0], t), s.fy(p[1], t)])
                    s.link.move(*p); s.dwell(p, t)
            if s.a.preview and frame is not None:
                if hit: cv2.circle(frame, tuple(int(v) for v in hit[0]), int(hit[1] / 2), (0, 255, 0), 2)
                cv2.imshow("headtrack", frame)
                k = cv2.waitKey(1) & 0xFF
                if k == ord("c"): s.cmds.append("CAL")
                if k == ord("r"): s.cmds.append("REC")
                if k == 27: break
            n += 1
            if t - tfps > 5: print("%.1f fps" % (n / (t - tfps)), flush=True); n, tfps = 0, t

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--link", default="stdout")
    ap.add_argument("--dev", default="/dev/video0")
    ap.add_argument("--id", type=int, default=0)
    ap.add_argument("--width", type=int, default=1280); ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--calfile", default=os.path.expanduser("~/.headtrack_cal.json"))
    ap.add_argument("--cal", action="store_true", help="force calibration at start")
    ap.add_argument("--mincut", type=float, default=1.0); ap.add_argument("--beta", type=float, default=0.02)
    ap.add_argument("--dwell", type=float, default=0.0, help="dwell-click seconds, 0=off (sip-n-puff clicks)")
    ap.add_argument("--dwell-r", dest="dwell_r", type=float, default=0.03, help="dwell radius, screen fraction")
    ap.add_argument("--preview", action="store_true")
    App(ap.parse_args()).run()
