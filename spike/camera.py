"""V4L2 capture with control locking that actually survives the C920.

THE C920 GOTCHA
---------------
The Logitech C920 family resets its UVC controls at VIDIOC_STREAMON. Set
exposure and focus before opening the capture -- the obvious order -- and the
camera silently discards them the moment streaming starts. No error is raised
anywhere. You just get autofocus hunting and auto-exposure breathing, and you
spend two days blaming your gaze code for the jitter.

So the order here is: open capture, pull and discard a few frames to get the
stream genuinely running, THEN apply controls, THEN read them back and verify.
The readback is not paranoia -- it is the only way to know it worked.

CONTROL NAME DRIFT
------------------
uvcvideo renamed its controls to the standard V4L2 set around kernel 5.19:
    exposure_auto            -> auto_exposure
    exposure_absolute        -> exposure_time_absolute
    focus_auto               -> focus_automatic_continuous
    white_balance_temperature_auto -> white_balance_automatic
We probe which vocabulary the running kernel speaks instead of guessing.
Value semantics survived the rename: 1 = manual, 3 = aperture priority (auto).
"""

import os
import re
import shutil
import subprocess
import threading
import time

import cv2

# (preferred_name, legacy_name)
CTRL_ALIASES = {
    "auto_exposure": ("auto_exposure", "exposure_auto"),
    "exposure_time_absolute": ("exposure_time_absolute", "exposure_absolute"),
    "focus_automatic_continuous": ("focus_automatic_continuous", "focus_auto"),
    "focus_absolute": ("focus_absolute", "focus_absolute"),
    "white_balance_automatic": ("white_balance_automatic",
                                "white_balance_temperature_auto"),
    "white_balance_temperature": ("white_balance_temperature",
                                  "white_balance_temperature"),
    "gain": ("gain", "gain"),
    # UVC "dynamic framerate": lets the camera shorten exposure on its own to
    # sustain the requested fps. It silently overrides exposure_time_absolute
    # EVEN IN MANUAL MODE -- observed on the C920 clamping a requested 250 to
    # 156 with auto_exposure already set to 1, reproducibly. Must be turned off
    # BEFORE exposure is set, or "manual" exposure still varies with scene
    # brightness, which is the exact breathing this class exists to stop.
    "exposure_dynamic_framerate": ("exposure_dynamic_framerate",
                                   "exposure_auto_priority"),
}

MANUAL_EXPOSURE = 1  # 3 = aperture priority (auto), 1 = manual. Both eras.


class _Grabber(threading.Thread):
    """Keep the newest frame available so the pipeline never waits on the sensor.

    Measured on the UNO Q before this existed: 30.5 ms of an 85.8 ms frame
    budget was spent inside cap.read(), which is exactly 1/30 s. That is not
    work, it is the pipeline standing still until the sensor produces the next
    frame, and it was 35% of the loop.

    Single slot, newest wins. A queue would be wrong here: for a pointing
    device a stale frame is worse than no frame, and buffering only converts
    latency you can see into latency you cannot.
    """

    daemon = True

    def __init__(self, cap):
        super().__init__(daemon=True)
        self.cap = cap
        self.cv = threading.Condition()
        self.frame = None
        self.seq = 0
        self.running = True
        self.fail = 0

    def run(self):
        while self.running:
            ok, f = self.cap.read()
            if not ok:
                self.fail += 1
                time.sleep(0.002)
                continue
            with self.cv:
                self.frame = f
                self.seq += 1
                self.cv.notify_all()

    def stop(self):
        self.running = False


def _have_v4l2ctl():
    return shutil.which("v4l2-ctl") is not None


def list_controls(device):
    """Return {control_name: current_value} as the kernel reports them."""
    if not _have_v4l2ctl():
        return {}
    try:
        out = subprocess.run(["v4l2-ctl", "-d", device, "--list-ctrls"],
                             capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return {}
    ctrls = {}
    for line in out.splitlines():
        m = re.match(r"\s*(\w+)\s+0x[0-9a-f]+\s+\(\w+\)", line)
        if not m:
            continue
        v = re.search(r"value=(-?\d+)", line)
        ctrls[m.group(1)] = int(v.group(1)) if v else None
    return ctrls


def resolve_name(logical, available):
    for cand in CTRL_ALIASES.get(logical, (logical,)):
        if cand in available:
            return cand
    return None


def set_control(device, name, value):
    if not _have_v4l2ctl():
        return False
    try:
        r = subprocess.run(
            ["v4l2-ctl", "-d", device, "--set-ctrl", "%s=%d" % (name, value)],
            capture_output=True, text=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False


def list_formats(device):
    if not _have_v4l2ctl():
        return ""
    try:
        return subprocess.run(["v4l2-ctl", "-d", device, "--list-formats-ext"],
                              capture_output=True, text=True,
                              timeout=5).stdout
    except Exception:
        return ""


class Camera:
    """Capture with verified manual exposure and focus.

    width/height are the CAPTURE resolution. Capture wide and downscale for
    inference rather than capturing small: the C920's 78 deg lens spends most
    of its sensor on the room, so you want the pixels, then you crop.
    """

    def __init__(self, device="/dev/video0", width=1920, height=1080, fps=30,
                 fourcc="MJPG", exposure=None, focus=None, gain=None,
                 warmup_frames=8, threaded=True):
        # MEASURED 2026-08-16: /dev/videoN is NOT stable across boots on this
        # board. The Qualcomm Venus codec driver and USB enumeration race for
        # the low numbers, so the C920 was video0 on 2026-08-08 and video2 on
        # 2026-08-16. /dev/v4l/by-id/... is the only stable name for it, so
        # accept one and resolve it here, ONCE -- before open() parses an index
        # out of it and before v4l2-ctl is handed it. Resolving in one place is
        # what keeps the capture index and the control calls on the same node.
        # os.path.realpath leaves a non-existent path alone; open() reports it.
        # Only absolute paths get resolved: realpath("2") would helpfully turn a
        # bare index into $CWD/2, which is neither a node nor an index.
        self.requested = device
        self.device = (os.path.realpath(device)
                       if device.startswith("/") else device)
        self.width, self.height, self.fps = width, height, fps
        self.fourcc = fourcc
        self.exposure, self.focus, self.gain = exposure, focus, gain
        self.warmup_frames = warmup_frames
        self.threaded = threaded
        self._grab = None
        self._last_seq = 0
        self.cap = None
        self.applied = {}
        self.verified = {}

    def open(self):
        # cv2's V4L2 backend takes an integer index, not a path, so the device
        # has to be a real /dev/videoN by now. Match it strictly rather than
        # scraping digits: "..._C920_1DB6303F-video-index0" scrapes to a
        # garbage index that opens the WRONG camera, or fails with no clue why.
        # __init__ has already resolved symlinks, so a mismatch here is a real
        # misconfiguration and is worth an error that names both paths.
        m = re.fullmatch(r"(?:/dev/video)?(\d+)", self.device)
        if m is None:
            raise RuntimeError(
                "camera device %r resolved to %r, which is not a /dev/videoN "
                "node -- check `ls -l /dev/v4l/by-id/`"
                % (self.requested, self.device))
        idx = int(m.group(1))
        self.cap = cv2.VideoCapture(idx, cv2.CAP_V4L2)
        if not self.cap.isOpened():
            raise RuntimeError(
                "could not open %s (index %d)%s" % (
                    self.device, idx,
                    "" if self.device == self.requested
                    else " resolved from %s" % self.requested))

        # MJPEG is not optional at 1080p30 -- YUYV at that rate exceeds USB 2.0
        # bandwidth and the driver will silently drop you to 5fps or 720p.
        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*self.fourcc))
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self.cap.set(cv2.CAP_PROP_FPS, self.fps)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # latency, not throughput

        # Stream must be genuinely running before controls will stick.
        for _ in range(self.warmup_frames):
            self.cap.read()
        time.sleep(0.2)
        self._apply_controls()
        # Only now. _apply_controls reads controls back to verify them, and a
        # background thread pulling frames during that window makes the
        # verification race the writes -- which is indistinguishable from the
        # STREAMON reset it exists to detect.
        self.start_grabber()
        return self

    def _apply_controls(self):
        avail = list_controls(self.device)
        if not avail:
            self.verified = {"_note": "v4l2-ctl unavailable; controls unmanaged"}
            return

        plan = []
        if self.exposure is not None:
            plan.append(("auto_exposure", MANUAL_EXPOSURE))
            # Order matters: dynamic framerate must be off before the exposure
            # value is written, or the camera re-derives it from the fps target.
            plan.append(("exposure_dynamic_framerate", 0))
            plan.append(("exposure_time_absolute", int(self.exposure)))
        if self.focus is not None:
            plan.append(("focus_automatic_continuous", 0))
            plan.append(("focus_absolute", int(self.focus)))
        if self.gain is not None:
            plan.append(("gain", int(self.gain)))
        # White balance drift changes apparent iris contrast frame to frame.
        plan.append(("white_balance_automatic", 0))

        for logical, value in plan:
            name = resolve_name(logical, avail)
            if name is None:
                self.applied[logical] = "unsupported"
                continue
            ok = set_control(self.device, name, value)
            self.applied[logical] = "%s=%d %s" % (name, value,
                                                  "ok" if ok else "FAILED")

        # Read back. This is the step that catches a STREAMON reset.
        time.sleep(0.15)
        after = list_controls(self.device)
        for logical, value in plan:
            name = resolve_name(logical, avail)
            if name is None:
                continue
            got = after.get(name)
            rec = {"want": value, "got": got, "ok": got == value}
            if not rec["ok"] and logical == "exposure_time_absolute":
                # Distinguish EV quantisation from an actual STREAMON reset.
                # While streaming, this camera family snaps exposure to stops a
                # factor of two apart and floors anything in between. That is
                # not the control being ignored, and raising warmup_frames --
                # the usual remedy -- will never fix it. Only choosing a
                # representable value will.
                try:
                    if got and 0.5 < float(got) / float(value) < 1.0:
                        rec["note"] = ("floored to the EV stop below; %s is not "
                                       "representable while streaming" % value)
                except (TypeError, ValueError, ZeroDivisionError):
                    pass
            self.verified[name] = rec

    def start_grabber(self):
        """Begin background capture. Call AFTER controls are applied."""
        if self.threaded and self._grab is None:
            self._grab = _Grabber(self.cap)
            self._grab.start()

    def read(self, timeout=2.0):
        """Return the newest frame not yet handed out, or None on timeout.

        Deliberately never returns the same frame twice. Handing back a
        duplicate would let a benchmark report a frame rate the camera is not
        actually delivering -- the loop would spin on one image and call it
        throughput.
        """
        if self._grab is None:
            ok, frame = self.cap.read()
            return frame if ok else None
        with self._grab.cv:
            if self._grab.seq == self._last_seq:
                self._grab.cv.wait(timeout)
            if self._grab.seq == self._last_seq or self._grab.frame is None:
                return None
            self._last_seq = self._grab.seq
            return self._grab.frame

    def control_report(self):
        lines = []
        for name, v in self.verified.items():
            if name.startswith("_"):
                lines.append("  %s" % v)
                continue
            mark = "OK  " if v["ok"] else "BAD "
            lines.append("  %s%-32s want=%-6s got=%s"
                         % (mark, name, v["want"], v["got"]))
        return "\n".join(lines) if lines else "  (no controls applied)"

    def all_verified(self):
        return all(v["ok"] for k, v in self.verified.items()
                   if not k.startswith("_"))

    def close(self):
        if self._grab is not None:
            self._grab.stop()
            self._grab.join(timeout=1.0)
            self._grab = None
        if self.cap is not None:
            self.cap.release()
            self.cap = None

    def __enter__(self):
        return self.open()

    def __exit__(self, *a):
        self.close()
