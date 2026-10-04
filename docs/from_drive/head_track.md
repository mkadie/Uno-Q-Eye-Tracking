# head_track.md — add head tracking to the existing Uno Q eye tracker

Instructions for Claude Code, run from the root of the existing eye-tracking repo on the Arduino Uno Q
(Debian, QRB2210, 4 GB). Read this whole file, then read the repo, then propose a plan before editing.

## Goal
Add a **head-tracking input mode** alongside eye tracking. A printed 2-color ArUco tag clipped to glasses
or a hat brim is tracked by the same C920x. It goes through the **same calibration flow the eye tracker
already uses**, trimmed to 5 points, then drives the pointer for **T-Rex Talker** (first test: Talker
running on the Uno Q itself) and later **Bunny Feeding Frenzy**.

## Rules
- **Reuse, don't duplicate.** Use the repo's existing camera setup, calibration UI/sequence, calibration
  storage, smoothing, and pointer-output code. Head tracking should be a new *feature source* feeding the
  existing pipeline, not a parallel app. If a piece doesn't exist in the repo, take it from the reference
  implementation (below).
- Eye mode must behave exactly as before. Mode is selected by a CLI flag (e.g. `--mode eye|head`).
- Do not modify files outside the repo. Ask before adding system packages or udev rules.
- Report measured fps and calibration RMS; don't claim accuracy you haven't measured.

## Reference implementation
`headtrack.zip` (same Drive folder as this file) → `headtrack/unoq/headtrack.py` is a working standalone
version. Borrow from it: `TagTracker`, `Calib`, `OneEuro`, `Link("uinput")`, `lock_camera()`. Its
calibration loop (`App.calibrate`) is the fallback if the repo's own can't be reused.
CAD for the tag is in `headtrack/cad/` (not needed for this task).

## The tag
- ArUco `DICT_4X4_50`, default **ID 0** (IDs 0–3 printed; make it `--tag-id`).
- 4.5 mm cells → 27 mm marker, 33.75 mm tile with white quiet zone. Matte black/white.
- Expect ~6–7 px/cell at 60 cm, 1280×720 on the C920x.

## Feature extraction (head mode)
1. Grayscale frame → `cv2.aruco.ArucoDetector`, `CORNER_REFINE_SUBPIX`.
2. Keep only `--tag-id`. Feature = mean of the 4 corners (image px). Also record side length.
3. **ROI tracking:** after a hit, search a crop of ±2.5 × side around the last center. On 3 consecutive
   ROI misses, fall back to full frame. (Reference: ~3 ms ROI vs ~17 ms full frame on x86; expect ~5–8× on the A53.)
4. Lost tag → hold pointer, no motion, no clicks.

## Calibration (head mode)
- Use the eye tracker's existing calibration sequence and UI, with these parameters for head mode:
  5 points — center first, then corners at 15 %/85 % of screen.
  settle 0.5 s, collect 0.7 s, median of samples, require ≥ 8 samples and per-axis std ≤ 3 px, 2 retries per point.
  Succeed with ≥ 4 of 5 points.
- Model: **affine least squares**, `screen_norm = A @ [u, v, 1]` (2×3). If the repo's eye model is
  polynomial/homography, still use affine for head — head-to-screen is near-linear and 5 points
  over-determine it.
- Store under a **separate key/file from eye calibration** (e.g. `~/.headtrack_cal.json`), with tag id,
  resolution, RMS, feature span px, timestamp.
- If the existing calibration shows its own targets, keep that. If it doesn't, the reference's approach
  works: move the cursor itself to each target and have the user point at it.
- Log RMS (screen fraction) and feature span. A small span is fine — it means high gain for a user with
  limited range of motion; that is intended.
- **Recenter:** 1-point offset update `A[:,2] += target - A @ [u,v,1]`, keeps gain. Hook to whatever
  trigger eye mode uses for recenter/drift, plus `SIGUSR2`. Recalibrate on `SIGUSR1`.

## Output
- First test: Talker runs **on the Uno Q**. Use whatever pointer output eye mode already uses.
  If none exists, use the reference `uinput` virtual absolute mouse (ABS_X/ABS_Y 0..32767, BTN_LEFT/
  RIGHT/MIDDLE, REL_WHEEL — QEMU-tablet shape so libinput treats it as an absolute mouse).
- Smoothing: One Euro (mincut 1.0, beta 0.02) unless eye mode's filter is better-tuned; expose both as flags.
- Click: dwell, `--dwell 1.0` s, radius `--dwell-r 0.03` screen, 0.6 s refractory. (Sip-n-puff clicks
  come later via the RP2350 bridge; don't build that here.)
- If the Talker is fullscreen SDL/pygame on `kmsdrm` (no desktop), uinput absolute may not be seen —
  in that case, stop and report; the fix is in-process position injection into the Talker.

## Camera
- Same device/resolution as eye mode; default 1280×720 MJPG 30 fps.
- Lock focus/exposure/WB via `v4l2-ctl` (reuse eye mode's lock if present — the tag needs it just as much).
- If sustained fps < 25, try 960×540 and report both numbers.

## CPU budget (Talker + Piper share the board)
- `cv2.setNumThreads(1)`; run the tracker pinned to one core (`taskset -c 3`); Piper `--threads 3`.
- Report tracker CPU % and fps with Piper speaking.

## Acceptance
1. `--mode eye` unchanged (run its existing tests / a manual cal).
2. `--mode head --preview`: tag box drawn, fps printed, ≥ 25 fps.
3. Head calibration completes in ≤ 10 s, RMS printed, file saved separately from eye cal.
4. Pointer reaches all 4 screen corners; SIGUSR2 recenter works; dwell click selects a Talker cell.
5. Covering the tag freezes the pointer; uncovering resumes within 3 frames of reacquire.
6. Summarize: files changed, flags added, measured fps / RMS / CPU.
