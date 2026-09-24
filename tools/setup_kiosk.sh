#!/bin/bash
# Make the UNO Q boot straight into the demo menu. Run ON the board.
#
#   tools/setup_kiosk.sh          show what it WOULD do
#   tools/setup_kiosk.sh --apply  do it
#   tools/setup_kiosk.sh --undo   put it back
#
# Two separate things, and they fail independently:
#   1. AUTOLOGIN  -- the display manager logs 'arduino' in with no password
#   2. AUTOSTART  -- the desktop session launches bin/menu
#
# Deliberately NOT a systemd service replacing the desktop: the menu needs a
# real X session (the OpenCV windows, the mouse cursor, xset for blanking),
# and running it as a bare service loses all of that. It also leaves the
# desktop reachable if the menu is killed -- at a faire, a visitor facing a
# black screen is worse than a visitor facing a desktop.

set -u
USER_NAME="${SUDO_USER:-${USER:-arduino}}"
SPIKE="$(cd "$(dirname "$0")/.." && pwd)"
MENU="$SPIKE/bin/menu"
APPLY=0; UNDO=0
for a in "$@"; do
    [ "$a" = "--apply" ] && APPLY=1
    [ "$a" = "--undo" ] && UNDO=1
done
say() { printf '%s\n' "$*"; }
run() { if [ "$APPLY" = 1 ]; then eval "$@"; else say "  would: $*"; fi; }

# ---------------------------------------------------------------- which DM?
DM=""
for d in lightdm gdm3 gdm sddm; do
    systemctl list-unit-files 2>/dev/null | grep -q "^$d.service" && { DM=$d; break; }
done
[ -z "$DM" ] && say "!! no display manager found (lightdm/gdm/sddm). Autologin skipped."
say "user: $USER_NAME   display manager: ${DM:-none}   menu: $MENU"
[ -x "$MENU" ] || say "!! $MENU is not executable"

# ---------------------------------------------------------------- autologin
case "$DM" in
  lightdm)
    CONF=/etc/lightdm/lightdm.conf.d/60-autologin.conf
    if [ "$UNDO" = 1 ]; then run "sudo rm -f $CONF"
    else
      say "autologin -> $CONF"
      run "sudo mkdir -p $(dirname $CONF)"
      run "printf '[Seat:*]\nautologin-user=$USER_NAME\nautologin-user-timeout=0\n' | sudo tee $CONF >/dev/null"
    fi ;;
  gdm3|gdm)
    CONF=/etc/gdm3/daemon.conf
    say "autologin -> $CONF  (AutomaticLoginEnable)"
    if [ "$UNDO" = 1 ]; then
      run "sudo sed -i '/^AutomaticLogin/d' $CONF"
    else
      run "sudo sed -i '/^\\[daemon\\]/a AutomaticLoginEnable=true\nAutomaticLogin=$USER_NAME' $CONF"
    fi ;;
  sddm)
    CONF=/etc/sddm.conf.d/60-autologin.conf
    if [ "$UNDO" = 1 ]; then run "sudo rm -f $CONF"
    else
      run "sudo mkdir -p $(dirname $CONF)"
      run "printf '[Autologin]\nUser=$USER_NAME\nSession=xfce\n' | sudo tee $CONF >/dev/null"
    fi ;;
esac

# ---------------------------------------------------------------- autostart
DESKTOP="$HOME/.config/autostart/unoq-demo-menu.desktop"
if [ "$UNDO" = 1 ]; then
    run "rm -f '$DESKTOP'"
else
    say "autostart -> $DESKTOP"
    run "mkdir -p '$(dirname "$DESKTOP")'"
    # A short delay: the menu opens a fullscreen window, and doing that before
    # the window manager is up leaves it undecorated and unfocusable.
    run "cat > '$DESKTOP' <<DESK
[Desktop Entry]
Type=Application
Name=UNO Q demo menu
Exec=bash -lc 'sleep 6; exec python3 \"$MENU\"'
X-GNOME-Autostart-enabled=true
Terminal=false
DESK"
fi

say ""
if [ "$APPLY" = 1 ]; then
    say "applied. Reboot to test: the board should log in and show the menu."
    say "To get a desktop back: tools/setup_kiosk.sh --undo, or press Q then Y."
else
    say "DRY RUN -- nothing changed. Re-run with --apply."
fi
