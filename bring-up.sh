#!/usr/bin/env bash
# UNO Q bring-up for the gaze project.
#
# Self-contained: does NOT need the project tree. Run it first on a fresh
# board, then drop the project in and run ./setup.sh && ./bin/probe.
#
#   bash bring-up.sh          # do it
#   bash bring-up.sh --check  # report only, change nothing
#
# Idempotent. Safe to re-run.

set -uo pipefail
CHECK_ONLY=0
[ "${1:-}" = "--check" ] && CHECK_ONLY=1

if [ -t 1 ]; then G=$'\e[32m'; R=$'\e[31m'; Y=$'\e[33m'; D=$'\e[2m'; B=$'\e[1m'; N=$'\e[0m'
else G=; R=; Y=; D=; B=; N=; fi

FAIL=0; WARN=0
hdr(){ printf '\n%s=== %s%s\n' "$B" "$1" "$N"; }
ok(){   printf '  %sPASS%s %s\n' "$G" "$N" "$1"; }
bad(){  printf '  %sFAIL%s %s\n' "$R" "$N" "$1"; FAIL=$((FAIL+1)); }
warn(){ printf '  %sWARN%s %s\n' "$Y" "$N" "$1"; WARN=$((WARN+1)); }
inf(){  printf '  %s     %s%s\n' "$D" "$1" "$N"; }
run(){ if [ "$CHECK_ONLY" = 1 ]; then inf "would run: $*"; else "$@"; fi; }

# ---------------------------------------------------------------- identity
hdr "board"
inf "arch      $(uname -m)"
inf "kernel    $(uname -r)"
[ -r /etc/os-release ] && inf "os        $(. /etc/os-release; echo "$PRETTY_NAME")"
inf "cpus      $(nproc)"

GLIBC=$(ldd --version 2>/dev/null | head -1 | grep -oE '[0-9]+\.[0-9]+$')
if [ -n "$GLIBC" ]; then
  if [ "$(printf '2.28\n%s\n' "$GLIBC" | sort -V | head -1)" = "2.28" ]; then
    ok "glibc $GLIBC >= 2.28 — the mediapipe aarch64 wheel will install"
  else
    bad "glibc $GLIBC < 2.28 — no mediapipe aarch64 wheel. This is the hard path."
  fi
fi

MEM_MB=$(awk '/MemTotal/{printf "%d", $2/1024}' /proc/meminfo)
inf "memory    ${MEM_MB} MB usable"
if [ "$MEM_MB" -lt 1900 ]; then
  warn "under 2 GB — tight once a GUI runs alongside the vision pipeline"
elif [ "$MEM_MB" -lt 3400 ]; then
  warn "looks like the 2 GB board; the 4 GB variant is recommended for dev"
else
  ok "4 GB variant"
fi

ROOT_AVAIL=$(df -BG --output=avail / | tail -1 | tr -dc '0-9')
inf "rootfs    ${ROOT_AVAIL} GB free (partition is 10 GB on both variants)"
[ "${ROOT_AVAIL:-0}" -lt 3 ] && warn "under 3 GB free on / — pip installs may fail"

# ------------------------------------------------------------------- swap
hdr "swap"
if [ "$(swapon --show --noheadings 2>/dev/null | wc -l)" -gt 0 ]; then
  ok "swap active: $(swapon --show=SIZE --noheadings | tr '\n' ' ')"
else
  # Four A53 cores will happily OOM themselves on a big C++ translation unit,
  # and the failure mode is an unhelpful "Killed" with no traceback.
  warn "no swap — creating 2 G before any heavy install"
  run sudo fallocate -l 2G /swapfile
  run sudo chmod 600 /swapfile
  run sudo mkswap /swapfile
  run sudo swapon /swapfile
  if [ "$CHECK_ONLY" = 0 ] && ! grep -q '^/swapfile' /etc/fstab 2>/dev/null; then
    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
  fi
  [ "$CHECK_ONLY" = 0 ] && ok "swap created and persisted"
fi

# --------------------------------------------------------------- governor
hdr "cpu governor"
GOV_F=/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor
if [ -r "$GOV_F" ]; then
  GOV=$(cat "$GOV_F")
  if [ "$GOV" = "performance" ]; then
    ok "governor already performance"
  else
    warn "governor is '$GOV' — fps numbers measured like this are meaningless"
    if [ "$CHECK_ONLY" = 0 ]; then
      for f in /sys/devices/system/cpu/cpu*/cpufreq/scaling_governor; do
        echo performance | sudo tee "$f" >/dev/null 2>&1
      done
      ok "set performance on all cores (resets at reboot — re-run before benching)"
    fi
  fi
else
  inf "no cpufreq interface exposed; nothing to set"
fi

# ---------------------------------------------------------------- thermal
hdr "thermal"
HOT=0
for z in /sys/class/thermal/thermal_zone*/temp; do
  [ -r "$z" ] || continue
  T=$(( $(cat "$z") / 1000 ))
  [ "$T" -gt 70 ] && HOT=1
  inf "$(dirname "$z" | xargs basename)  ${T} C"
done
[ "$HOT" = 1 ] && warn "already above 70 C at idle — sustained benching will throttle"
[ "$HOT" = 0 ] && ok "temperatures nominal"

# --------------------------------------------------------------- packages
hdr "system packages"
NEED=""
for p in git v4l-utils python3-pip python3-venv libgl1 libglib2.0-0 curl unzip; do
  dpkg -s "$p" >/dev/null 2>&1 || NEED="$NEED $p"
done
if [ -z "$NEED" ]; then
  ok "all present"
else
  inf "installing:$NEED"
  run sudo apt-get update -qq
  run sudo apt-get install -y --no-install-recommends $NEED
  [ "$CHECK_ONLY" = 0 ] && ok "installed"
fi

# ------------------------------------------------------------------ video
hdr "video group"
ME="${USER:-$(id -un)}"
if id -nG "$ME" | tr ' ' '\n' | grep -qx video; then
  ok "$ME is in group video"
else
  warn "$ME not in group video — /dev/video* access needs it"
  run sudo usermod -aG video "$ME"
  [ "$CHECK_ONLY" = 0 ] && warn "log out and back in for this to take effect"
fi

# ----------------------------------------------------------------- camera
hdr "camera"
shopt -s nullglob
VIDS=(/dev/video*)
if [ ${#VIDS[@]} -eq 0 ]; then
  bad "no /dev/video* — check hub power, then try the camera on the board's USB-C directly"
else
  inf "devices   ${VIDS[*]}"
  FOUND_MJPG=0
  for d in "${VIDS[@]}"; do
    if v4l2-ctl -d "$d" --list-formats 2>/dev/null | grep -q "MJPG\|Motion-JPEG"; then
      NAME=$(v4l2-ctl -d "$d" --info 2>/dev/null | awk -F': ' '/Card type/{print $2}')
      ok "$d offers MJPEG  ${NAME:+($NAME)}"
      FOUND_MJPG=1
    fi
  done
  # MJPEG is not optional: YUYV at 1080p30 exceeds USB 2.0 bandwidth and the
  # driver renegotiates you down to something useless without saying so.
  [ "$FOUND_MJPG" = 0 ] && bad "no device offers MJPEG"

  # Which control vocabulary does this kernel speak? uvcvideo renamed these
  # around 5.19 and the project needs to know which set exists.
  for d in "${VIDS[@]}"; do
    CTRLS=$(v4l2-ctl -d "$d" --list-ctrls 2>/dev/null) || continue
    [ -z "$CTRLS" ] && continue
    if grep -q "auto_exposure" <<<"$CTRLS"; then
      inf "$d exposure control: auto_exposure / exposure_time_absolute (modern)"
    elif grep -q "exposure_auto" <<<"$CTRLS"; then
      inf "$d exposure control: exposure_auto / exposure_absolute (legacy)"
    fi
    break
  done
fi

# -------------------------------------------------------------- usb health
hdr "usb health"
UV=$(dmesg 2>/dev/null | grep -ciE "under-voltage|not enough power|cannot enable.*power" || true)
EN=$(dmesg 2>/dev/null | grep -ciE "device descriptor read.*error|unable to enumerate" || true)
[ "${UV:-0}" -gt 0 ] && bad "$UV undervoltage message(s) in dmesg — power the HUB from the PD brick, not the board"
[ "${EN:-0}" -gt 0 ] && warn "$EN enumeration error(s) in dmesg — suspect the cable or hub before suspecting code"
[ "${UV:-0}" -eq 0 ] && [ "${EN:-0}" -eq 0 ] && ok "no power or enumeration complaints in dmesg"

# ------------------------------------------------------------- contention
hdr "contention"
if pgrep -fa "app-?lab|arduino" >/dev/null 2>&1; then
  warn "Arduino App Lab looks like it is running — stop it before benchmarking, it competes for RAM and CPU"
else
  ok "no App Lab process competing"
fi
if command -v gsettings >/dev/null 2>&1 && [ -n "${DISPLAY:-}" ]; then
  # A screensaver firing mid-calibration ruins the run and is baffling.
  run gsettings set org.gnome.desktop.session idle-delay 0 2>/dev/null
  run gsettings set org.gnome.desktop.screensaver lock-enabled false 2>/dev/null
  inf "screen blanking disabled for this session"
fi

# ----------------------------------------------------------------- python
hdr "python"
inf "python    $(python3 --version 2>&1)"
PIPFLAG=""
python3 -m pip install --help 2>/dev/null | grep -q break-system-packages && \
  PIPFLAG="--break-system-packages"
[ -n "$PIPFLAG" ] && inf "pip needs $PIPFLAG on this Debian"
python3 - <<'PY' 2>/dev/null || true
import importlib
for m in ("numpy","cv2","mediapipe","serial"):
    try:
        mod = importlib.import_module(m)
        print("  \033[32mPASS\033[0m %-12s %s" % (m, getattr(mod,"__version__","present")))
    except ImportError:
        print("  \033[2m      %-12s not installed yet (setup.sh will handle it)\033[0m" % m)
PY

# ---------------------------------------------------------------- verdict
hdr "verdict"
if [ "$FAIL" -gt 0 ]; then
  printf '  %s%d blocking issue(s)%s — fix before running setup.sh\n' "$R" "$FAIL" "$N"
  exit 1
fi
if [ "$WARN" -gt 0 ]; then
  printf '  %sclear to proceed, %d warning(s)%s\n' "$Y" "$WARN" "$N"
else
  printf '  %sboard is ready%s\n' "$G" "$N"
fi
cat <<'EOF'

  next:
    ./setup.sh        # python deps, model bundle
    ./bin/probe       # full go/no-go including camera control locking
    pytest tests/ -q  # 85 tests, no hardware needed
EOF
