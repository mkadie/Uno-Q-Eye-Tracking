"""Keep the screen awake while a full-screen gaze tool is running.

MEASURED 2026-09-21, and it is not a nicety: the monitor blanked in the middle
of a session and looked like a dead board. X's idle timer counts INPUT EVENTS
-- keyboard and pointer -- and OpenCV rendering is not an input event. A gaze
demo therefore looks completely idle to X while it is drawing sixty frames a
second, so DPMS blanks it on schedule.

Gaze is the whole point of these tools, so "the user has not touched anything
in 30 minutes" is the normal case rather than a sign of absence. At a faire
the board would go dark in front of a visitor.

Disable blanking for the life of the tool and restore the previous settings on
the way out, so this does not silently become a permanent change to someone's
desktop.
"""

import atexit
import os
import re
import shutil
import subprocess

_SAVED = None


def _xset(*args):
    return subprocess.run(["xset"] + list(args), capture_output=True,
                          text=True, timeout=5)


def _read_state():
    """(screensaver timeout, cycle, standby, suspend, off) or None."""
    try:
        out = _xset("q").stdout
    except Exception:
        return None
    ss = re.search(r"timeout:\s+(\d+)\s+cycle:\s+(\d+)", out)
    dp = re.search(r"Standby:\s+(\d+)\s+Suspend:\s+(\d+)\s+Off:\s+(\d+)", out)
    if not (ss and dp):
        return None
    return (int(ss.group(1)), int(ss.group(2)),
            int(dp.group(1)), int(dp.group(2)), int(dp.group(3)))


_LOCKER = ("light-locker", "xscreensaver", "gnome-screensaver",
           "mate-screensaver", "xfce4-screensaver")


def _pause_locker():
    """Stop a session locker for the life of the tool.

    MEASURED 2026-09-30: `xset s off` is NOT enough. light-locker runs its
    own timer and put the lock screen in front of a running talker, which on
    this board is unrecoverable -- the kiosk has no keyboard, so a visitor
    cannot type a password to get back. A locker on a kiosk is not a
    security feature, it is a way to end the exhibit.

    SIGSTOP rather than kill: the process comes back on SIGCONT at exit, so
    this does not quietly disarm the locker on someone's desktop forever.
    """
    for name in _LOCKER:
        try:
            subprocess.run(["pkill", "-STOP", "-x", name],
                           capture_output=True, timeout=5)
        except Exception:
            pass


def _resume_locker():
    for name in _LOCKER:
        try:
            subprocess.run(["pkill", "-CONT", "-x", name],
                           capture_output=True, timeout=5)
        except Exception:
            pass


def hold(verbose=True):
    """Disable screen blanking. Restored automatically at exit."""
    global _SAVED
    if not os.environ.get("DISPLAY") or not shutil.which("xset"):
        return False
    if _SAVED is not None:
        return True
    _SAVED = _read_state()
    try:
        _xset("s", "off")
        _xset("-dpms")
        _xset("dpms", "force", "on")
    except Exception:
        return False
    _pause_locker()
    atexit.register(release)
    if verbose and _SAVED:
        print("[nosleep] blanking off (was s=%ds dpms=%d/%d/%d); "
              "restored on exit" % (_SAVED[0], _SAVED[2], _SAVED[3], _SAVED[4]))
    return True


def release():
    """Put the previous settings back. Safe to call more than once."""
    global _SAVED
    if _SAVED is None:
        return
    s_timeout, s_cycle, standby, suspend, off = _SAVED
    _SAVED = None
    try:
        _xset("s", str(s_timeout), str(s_cycle))
        if standby or suspend or off:
            _xset("+dpms")
            _xset("dpms", str(standby), str(suspend), str(off))
    except Exception:
        pass
    _resume_locker()
