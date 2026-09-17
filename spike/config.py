"""TOML config loading with defaults and validation."""

import os

try:
    import tomllib          # 3.11+
except ImportError:         # pragma: no cover
    import tomli as tomllib

DEFAULTS = {
    "camera": {
        "device": "/dev/video0", "width": 1920, "height": 1080, "fps": 30,
        "fourcc": "MJPG", "exposure": 250, "focus": 40, "gain": None,
    },
    "inference": {
        "backend": "mediapipe", "input_size": 320, "num_threads": 4,
        "blink_ear_threshold": 0.15,
    },
    "screen": {
        "width_px": 1920, "height_px": 1080,
        "width_mm": 527, "height_mm": 296, "viewing_distance_mm": 600,
    },
    "filter": {"min_cutoff": 1.0, "beta": 0.007, "d_cutoff": 1.0},
    "calibration": {
        "points": 9, "samples_per_point": 30, "settle_ms": 700,
        "ridge": 0.001, "ring_size": 256, "refit_every": 12,
    },
    "breath": {
        "thresholds": {
            "soft_puff": 4.0, "hard_puff": 12.0,
            "soft_sip": -4.0, "hard_sip": -12.0,
        },
        "debounce_ms": 40, "hold_ms": 1500, "command_timeout_ms": 4000,
        "sequences": {
            "puff": "recalibrate",
            "puff,puff": "mode_toggle",
        },
    },
    "serial": {"port": "/dev/ttyUSB0", "baud": 115200,
               "heartbeat_timeout_ms": 1500},

    # This unit's identity. Only matters once more than one gaze mouse shares
    # a USB host -- see the [[cursor]] discussion in validate_cursors().
    "device": {
        "name": "primary",
        "usb_label": "Gaze Mouse",
    },

    # Host-side binding table. Empty by default: a single-unit build needs
    # none of this.
    "cursor": [],
}

# Categorical slots 1 and 2 from the validated palette. These two clear the
# all-pairs colourblind gates in both light and dark; adding a third and
# fourth accent should reuse the next slots in that fixed order rather than
# inventing hues.
DEFAULT_ACCENTS = ("#2a78d6", "#eb6834", "#1baf7a")


def _merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load(path=None):
    path = path or os.environ.get("GAZE_CONFIG", "config.toml")
    user = {}
    if os.path.exists(path):
        with open(path, "rb") as f:
            user = tomllib.load(f)
    cfg = _merge(DEFAULTS, user)
    validate(cfg)
    return cfg


def validate_cursors(cfg):
    """Validate the multi-unit identity table.

    WHY THIS EXISTS
    ---------------
    Two gaze mice on one USB host (a Fruit Jam, say) are indistinguishable by
    descriptor if they are the same build: same VID, same PID, same product
    string. The host enumerates them in whatever order it happens to, so
    cursor A and cursor B swap between reboots. Users notice this immediately
    and it is maddening.

    The fix is to give each unit a distinct USB product string, set from
    boot.py, and bind cursors against it here. Note that we vary the product
    STRING, never the VID/PID -- inventing a vendor ID means squatting on
    somebody else's registered number, and it buys nothing the string does not.

    GLYPHS ARE REQUIRED AND MUST BE UNIQUE
    --------------------------------------
    Distinguishing two cursors by colour alone fails for a colourblind user.
    On an assistive device that would be a poor joke, so the glyph -- the
    cursor's actual shape -- is the identity channel, and the accent colour is
    decorative reinforcement. This function enforces that: duplicate glyphs are
    an error even when the accents differ.
    """
    cursors = cfg.get("cursor") or []
    if not cursors:
        return cfg

    seen = {"name": {}, "match": {}, "glyph": {}}
    for i, c in enumerate(cursors):
        for key in ("name", "match", "glyph"):
            if not c.get(key):
                raise ValueError(
                    "[[cursor]] #%d is missing required key %r. 'match' is the "
                    "USB product string to bind on; 'glyph' is the cursor "
                    "shape, which carries identity so that colour never has to."
                    % (i + 1, key))
            v = c[key]
            if v in seen[key]:
                extra = ""
                if key == "glyph":
                    extra = (" Two cursors sharing a glyph are "
                             "distinguishable only by colour, which fails for "
                             "a colourblind user.")
                raise ValueError(
                    "[[cursor]] %r duplicated between %r and %r.%s"
                    % (key, seen[key][v], c.get("name", "?"), extra))
            seen[key][v] = c.get("name", "?")
        c.setdefault("accent", DEFAULT_ACCENTS[i % len(DEFAULT_ACCENTS)])

    # A unit that names itself should appear in the table, or it will enumerate
    # on the host and bind to nothing.
    me = cfg["device"]["usb_label"]
    if len(cursors) > 1 and me not in seen["match"]:
        raise ValueError(
            "device.usb_label %r matches no [[cursor]] entry. This unit would "
            "enumerate on the host and never be assigned a cursor. Known "
            "labels: %s" % (me, ", ".join(sorted(seen["match"]))))
    return cfg


def cursor_for(cfg, usb_product_string):
    """Host-side lookup: USB product string -> cursor entry, or None."""
    for c in cfg.get("cursor") or []:
        if c["match"] == usb_product_string:
            return c
    return None


def settings_toml(cfg):
    """Render the CircuitPython settings.toml lines for THIS unit.

    boot.py reads its identity through os.getenv(), which CircuitPython backs
    with settings.toml -- that is the native mechanism and is always present,
    whereas a full TOML parser in boot.py is not. Generating it from the same
    source of truth is what stops the two files drifting apart.
    """
    d = cfg["device"]
    return ('GAZE_UNIT_NAME = "%s"\nGAZE_USB_LABEL = "%s"\n'
            % (d["name"], d["usb_label"]))


def validate(cfg):
    validate_cursors(cfg)
    t = cfg["breath"]["thresholds"]
    if not (t["hard_sip"] < t["soft_sip"] < 0 < t["soft_puff"] < t["hard_puff"]):
        raise ValueError(
            "breath thresholds must satisfy hard_sip < soft_sip < 0 < "
            "soft_puff < hard_puff; got %r" % (t,))
    if cfg["breath"]["hold_ms"] <= cfg["breath"]["debounce_ms"]:
        raise ValueError("hold_ms must exceed debounce_ms")
    s = cfg["screen"]
    if s["width_mm"] <= 0 or s["viewing_distance_mm"] <= 0:
        raise ValueError("screen geometry must be positive -- angular error "
                         "is meaningless without it")
    return cfg


def px_per_mm(cfg):
    return cfg["screen"]["width_px"] / float(cfg["screen"]["width_mm"])
