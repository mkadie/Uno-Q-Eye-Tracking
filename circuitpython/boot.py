"""Breath board USB identity + interface trimming. Runs before code.py.

Two jobs:

1. NAME THIS UNIT so a USB host can tell it from its sibling. Two gaze mice of
   the same build are indistinguishable by descriptor -- same VID, same PID,
   same product string -- so a host enumerating both binds cursor A and cursor
   B in whatever order it happens to, and they swap between reboots. Setting a
   distinct product string here fixes it.

   Note we vary the product STRING only, never VID/PID. Inventing a vendor ID
   means squatting on somebody else's registered number and buys nothing the
   string does not.

2. OPTIONALLY trim the composite device down to HID-only. A CircuitPython board
   normally enumerates as HID + CDC serial + mass storage, and some USB host
   stacks handle multi-interface devices poorly. Trimming makes this look like
   an ordinary mouse.

Identity comes from settings.toml via os.getenv(), which is CircuitPython's
native mechanism and always available -- unlike a full TOML parser, which is
not. Generate settings.toml from the project config with:

    python3 -c "import sys; sys.path.insert(0,'.'); from spike import config; \
print(config.settings_toml(config.load('config.toml')), end='')" \
> circuitpython/settings.toml

    settings.toml
    -------------
    GAZE_UNIT_NAME = "left"
    GAZE_USB_LABEL = "Gaze Mouse L"
"""

import os

import board
import digitalio
import storage
import supervisor
import usb_cdc
import usb_hid

# --------------------------------------------------------------- identity

UNIT = os.getenv("GAZE_UNIT_NAME") or "primary"
LABEL = os.getenv("GAZE_USB_LABEL") or "Gaze Mouse"

# Manufacturer and product only. Leaving vid/pid alone keeps us on Adafruit's
# registered IDs, which is both correct and what existing udev rules expect.
supervisor.set_usb_identification(manufacturer="OpenAT", product=LABEL)

# ------------------------------------------------------------ safety pin
#
# Ground SAFE_PIN at boot to keep the serial console and the CIRCUITPY drive.
#
# This guard is not optional. If boot.py disables the USB drive and anything
# below is wrong, you can no longer edit boot.py to fix it -- the only recovery
# is a full erase and reflash, losing whatever was on the board. One jumper
# buys back the ability to undo your own mistake.

SAFE_PIN = board.D0

_safe = digitalio.DigitalInOut(SAFE_PIN)
_safe.switch_to_input(digitalio.Pull.UP)
dev_mode = not _safe.value          # pin grounded -> stay editable

# Only trim interfaces when a host actually needs it. Set GAZE_HID_ONLY = 1 in
# settings.toml once you have confirmed your host stack is unhappy with the
# composite device -- do not do it pre-emptively, because you lose the console
# you debug with.
hid_only = str(os.getenv("GAZE_HID_ONLY") or "0") == "1"

if hid_only and not dev_mode:
    usb_cdc.disable()
    storage.disable_usb_drive()

usb_hid.enable((usb_hid.Device.MOUSE,))

print("boot: unit=%s label=%r hid_only=%s dev_mode=%s"
      % (UNIT, LABEL, hid_only, dev_mode))
