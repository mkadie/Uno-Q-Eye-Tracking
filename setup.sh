#!/usr/bin/env bash
# Bootstrap the spike on the UNO Q. Run once, then `bin/probe`.
set -euo pipefail

cd "$(dirname "$0")"
echo "=== UNO Q gaze spike setup"
echo "arch: $(uname -m)   python: $(python3 --version)"

# --- swap ------------------------------------------------------------
# Even on the 4GB board, add swap before the first heavy pip build. Four A53
# cores will happily OOM themselves on a large C++ translation unit, and the
# failure mode is an unhelpful "Killed" with no traceback.
if [ "$(swapon --show --noheadings | wc -l)" -eq 0 ]; then
  echo "--- no swap active; creating 2G swapfile (sudo)"
  sudo fallocate -l 2G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile
  sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

# --- system deps -----------------------------------------------------
echo "--- apt packages"
sudo apt-get update -qq
sudo apt-get install -y --no-install-recommends \
  v4l-utils python3-pip python3-venv libgl1 libglib2.0-0

# --- python ----------------------------------------------------------
echo "--- python packages"
# mediapipe >= 1.0.0 is required: it is the first release with an aarch64
# manylinux wheel. 0.10.x published only macOS arm64 and x86_64, which is why
# so many people believe MediaPipe does not run on ARM64 Linux.
python3 -m pip install --break-system-packages --upgrade pip
python3 -m pip install --break-system-packages -r requirements.txt

# --- models ----------------------------------------------------------
MODEL=models/face_landmarker.task
if [ ! -f "$MODEL" ]; then
  echo "--- downloading face_landmarker bundle"
  mkdir -p models
  curl -fSL -o "$MODEL" \
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task"
fi

# The .task bundle is a zip. Unpacking it gives the raw .tflite files that the
# LiteRT contingency backend needs, so do it now rather than at 2am.
if [ ! -d models/bundle ]; then
  echo "--- unpacking bundle for the LiteRT fallback path"
  python3 - <<'PY'
import zipfile
z = zipfile.ZipFile("models/face_landmarker.task")
print("  contents:", z.namelist())
z.extractall("models/bundle")
PY
fi

chmod +x bin/probe bin/bench bin/calibrate

echo
echo "=== done. Next:  ./bin/probe"
