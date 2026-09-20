# Project context for Claude Code

Read this before proposing changes. It records decisions that were made for
reasons, so you don't spend the session rediscovering them.

## What this is

A measurement harness for adding eye tracking to a sip-n-puff assistive device
on an Arduino UNO Q. Deadline **30 Sep 2026**, contest entry (DigiKey/Arduino
Dream Lab, #UNOQDreamLab on maker.io). It is deliberately **not** a working eye
tracker — it exists to produce three numbers (fps, angular error, implied
target size) that decide the rest of the design.

Hardware: UNO Q 4GB (QRB2210, 4x Cortex-A53 @ 2.0 GHz, Adreno GPU, **no NPU** —
inference is CPU-bound). Logitech C920x on USB. A separate CircuitPython board
does breath sensing over I2C and is the USB HID endpoint.

## Run order — each gates the next

```
./bin/probe          # go/no-go: platform, runtimes, model, camera, controls
./bin/bench --sweep  # fps vs inference input size
./bin/calibrate      # angular error, and the UI target size it implies
pytest tests/ -q     # 85 tests, no hardware needed
```

Don't skip ahead. A bench run before `probe` reports clean controls measures a
camera problem, not the pipeline.

## Decisions that are load-bearing — do not "simplify" these

**The breath board stays the HID endpoint.** The UNO Q is a sensor that streams
gaze coordinates over UART; the CircuitPython board fuses breath + gaze and
emits HID. This keeps the eye tracker a bolt-on for people who already built
the sip-n-puff, rather than a rewrite that orphans existing builds. Moving HID
to the UNO Q would be tidier and is wrong.

**No multi-puff gesture on the fast path.** Recognising triple-puff means
waiting after *every* puff to see if another follows, which taxes every
ordinary click forever. Sequences live behind a long-hard-sip prefix instead.
`tests/test_gesture.py::test_click_latency_is_only_debounce` enforces this — if
you find yourself adding a timeout to the IDLE path, that test is telling you
not to.

**`mediapipe>=1.0.0`, never relax the pin.** 1.0.0 is the first release with a
`manylinux_2_28_aarch64` wheel. 0.10.x has none, and pip will silently fall
through to a source build that will not finish on this board. Keep the pin even
though MediaPipe cannot execute here — `ai-edge-litert` is what actually runs,
and the `.task` bundle it reads is still the MediaPipe artifact. But do not
spend time trying to make the wheel work: the blocker is the CPU's instruction
set, not the packaging, and no version of it will help.

**Camera controls are applied AFTER stream start.** The C920 family resets UVC
controls at `VIDIOC_STREAMON`, silently. `camera.py` opens the capture,
discards warmup frames, then applies controls, then reads them back to verify.
Reordering this to the "obvious" sequence breaks it with no error anywhere.

**Cursor glyphs must be unique, not just accent colours.** Two cursors
distinguishable only by colour fail for a colourblind user. `config.py` rejects
duplicate glyphs even when accents differ. This is an assistive device; the
check stays.

**Anchor weight decays.** Calibration anchors are a prior, and a prior must be
overwhelmable by evidence. A fixed weight stalls drift correction at ~40% —
this was found by a test, not by reasoning. See the comment block in
`calib.py`.

<!-- BEGIN glasses-fiducial -->
**Glasses-rim head pose: the rims ARE the fiducial.** Round lensless party
glasses, nothing printed, cut or glued on. A circle projects to an *exact*
ellipse under perspective and no other outline does, so every departure from
circular is pure pose information and the inversion is closed form. A wayfarer
or cat-eye outline is already non-circular, so its shape and its perspective
are entangled and you would need a contour template per production batch. Two
rims also resolve the planar-marker yaw ambiguity: both lie in one plane, so
the rig's x-axis must be perpendicular to the shared normal.

Already rejected, do not re-propose: wayfarers + printed ArUco tabs (no flat
area big enough, ~600 glue joints across 200 pairs, and a tab that rotates
silently corrupts the geometry); cat-eye + rhinestones (rhinestones are
mirrors -- the glint moves with the *light*, not the object -- and 2-3 mm is
about 5 px); QR codes (built for a data payload, corners not optimised for
pose).

Four traps in `spike/frame_fiducial.py`. Each is commented in place; none of
them fails loudly, which is why they are here:

- **(a) OpenCV's ellipse angle is relative to whichever axis it called
  "height".** `cv2.fitEllipse` returns full axis lengths as the
  `(width, height)` of a rotated box, so when the major axis is the *height*
  one its direction is `angle + 90`, not `angle`. Backwards, this transposes
  every tilt by 90 degrees and reads as plausible-but-wrong pose rather than
  as an error.
- **(b) Distance comes from the MAJOR axis.** The major axis is the tilt
  *axis*, so it is unforeshortened: `Z = f * radius_mm / semi_major_px`. This
  makes distance immune to head rotation -- measured max error 1.20 mm across
  a 75-pose sweep.
- **(c) Yaw comes from the DEPTH DIFFERENCE, not from eccentricity.**
  `yaw = -asin((z_right - z_left) / separation_mm)`. Deriving yaw from the
  axis ratio carries a systematic perspective bias of a couple of degrees,
  because `b/a = cos(tilt)` holds exactly only for a circle centred on the
  optical axis. `test_yaw_within_half_a_degree` is what pins this.
- **(d) Pitch sign is geometrically degenerate, and the gate is on MEASURED
  YAW -- never on a confidence score.** Both rim centres lie *on* the rig's
  x-axis and pitch rotates *about* that axis, so at zero yaw, tilting up and
  tilting down produce mathematically identical rim geometry. The information
  is not in the image and no filtering recovers it. Below
  `YAW_MIN_FOR_PITCH_SIGN_DEG` the pose is flagged `pitch_ambiguous` and the
  sign may come from `pitch_hint_deg` -- **one bit only, never the
  magnitude**. Do not gate on how well separated the candidate normals are: a
  separation score is not a correctness score.

**Detection is by SHAPE, never by colour.** Five rim colours and a hall whose
lighting drifts all day means any colour threshold that works at setup fails
after lunch. Find the ellipse geometrically, then read colour from inside it
purely as a visitor-identity label.

**`RigSpec` must be MEASURED, not assumed.** A 1 mm error in `radius_mm` is a
~4% error in every distance this module reports, silently. `RigSpec.trusted`
stays False until `measured_n >= 5`.

**CALIPERED 2026-09-19** (supersedes the photo-derived values): outer diameter
**50.0 mm**, inner **44.0 mm**, rim 3.0 mm, centre-to-centre separation
**61.5 mm**.

The separation is **not** the 67–75 mm that was estimated from the 137 mm frame
width — that estimate was 15.4% high, and the 71.0 placeholder built on it made
the pair test hunt for a separation/radius of 2.84 when the truth is 2.46. It
was scoring every genuine pair as a poor match. Measure this number; do not
derive it from the frame width.

It was measured twice over the two INNER circles so it checks itself: closest
inside points 18 mm = sep − inner_d, farthest inside points 105 mm =
sep + inner_d, giving inner_d = 43.5 and sep = 61.5 from **both** readings —
and that 43.5 agrees with the separately calipered 44.0 to 0.5 mm. Distance
needs the radius alone and was never affected.

The product photo is labelled 1.85 in = 47.0 mm and that is the **mid-rim**
diameter, not the outer — scaling off it gave 23.5 where the truth is 25.0.
Record the **spread over ten pairs**, not one pair: ±0.5 mm is 6.1 mm of
distance error at 600 mm, ±1.0 mm is 12.1 mm.

**The annulus ratio is the identity check.** The rim is a ring, so Canny
returns two concentric ellipses per lens and their ratio is fixed at
50.0/44.0 = **1.1364**. Requiring it (±6%) rejects almost everything that is
not a lens — coffee lid 1.060, lanyard grommet 1.350, CD 8.000 — and it
answers the question a single ellipse cannot: **which edge is this?** Inner
mistaken for outer is a 13.6% scale error, 82 mm at 600 mm.

**Resolving the two edges needs ~4 px of radial separation, so rim detection
runs at 1920, not 640.** A 3 mm rim subtends 6.8 px at 1920, 3.4 at 960 and
2.3 at 640, where the edges merge. `ring_pair()` rejects pairs closer than
`MIN_RING_SEPARATION_PX` because accepting a merged pair fabricates confidence
in a radius that is really the midline. MEASURED: `bin/rimcheck` at 1280
reported an implied radius of 23.71 mm when the mid-rim radius is 23.50 — it
had been fitting the midline the whole time.
<!-- END glasses-fiducial -->

<!-- BEGIN camera-intrinsics -->
**Calibrate the camera before believing any distance.** Every distance here is
`f * size / pixels`, so an error in `f` is a proportional error in all of it —
rim distance, marker distance, and the `t_z` feature feeding the gaze mapping.
A real C920 differs from its spec-sheet 70.4° by a few percent, and that is a
systematic error **larger than the difference between any two fiducial designs**
you might argue about.

```
python3 tools/calibrate_camera.py capture    # SPACE keeps a frame, q finishes
python3 tools/calibrate_camera.py solve      # -> camera_intrinsics.json
```

Target RMS reprojection **under 0.5 px over 20 frames**. Capture rules that
matter more than frame count: **tilt 30–45° in both axes** (face-on views
cannot separate focal length from distance — you get a confident, wrong `f`);
push the board into **all four corners** (distortion is largest there); keep
the board flat and rigid; hold still. **If `fx` and `fy` differ by more than
2%, you did not tilt enough** — `Intrinsics.fx_fy_agree` checks this.

`spike/intrinsics.py` loads the real file when it exists and **warns loudly**
when it falls back to the assumed FOV. Do not silence that warning; fix the
cause. `Intrinsics.calibrated` is False for the fallback so nothing can mistake
a guess for a measurement.

**Scale intrinsics with resolution.** `fx, fy, cx, cy` are all in pixels and
all scale linearly with width, so a set measured at 1920 is wrong by 1.5× if
you infer at 1280. `Intrinsics.for_size()` does it; forgetting is a silent
proportional error in every distance.

**Pass real `dist_coeffs` to `solvePnP`, not zeros.** At 78° diagonal the
corner distortion is not small and the eye landmarks are not near the centre.

**`spike/rig_geometry.py` is GENERATED and is y-DOWN.** OpenCV convention:
+x right, +y **down**, +z away from camera. Physical "up" on the plate is
negative y. Getting that backwards **inverts pitch while looking entirely
plausible** — the single easiest error to make here. Do not hand-edit the file.

**The marker board is the ruler, not the product.** It exists to judge the
cheap methods (rims, bare face mesh) against a pose you trust. Solve over the
whole board rather than per-marker: four markers spanning 156 × 120 mm of
corner spread beat any single 30 mm marker, and the board's non-collinear
layout makes **pitch directly observable with no hint and no gate** — which is
precisely what the rims cannot do. `reproj_px` above ~1 px means the geometry
or the intrinsics are wrong; it is the best single diagnostic available.

**OpenCV moved the ArUco API** — 4.7 added `cv2.aruco.ArucoDetector`, 4.13
removed the free `detectMarkers`. `marker_board.make_detector()` binds at
runtime; do not hardcode either form. And **turn on
`CORNER_REFINE_SUBPIX`** — it is not the default, and without it you localise
corners to whole pixels and throw away most of the precision the rig exists to
provide.
<!-- END camera-intrinsics -->

## Conventions

- **No sklearn, no pandas.** Ridge regression is thirty lines of `lstsq`, and
  resident set matters on a board that also runs a GUI.
- **`spike/gesture.py` must stay CircuitPython-compatible** — it is copied to
  the breath board verbatim. No dataclasses, no typing, no enum, no f-string
  debug specifiers.
- **Report percentiles, not means.** A pipeline averaging 20 fps that stalls to
  4 fps every other frame feels broken; the mean hides it. p95 latency and p5
  fps are the numbers that matter.
- Tests must run without hardware. Anything needing a camera goes in `bin/`.

## Verification status — be careful here

**Tested (85 passing):** `oneeuro`, `gesture`, `protocol`, `calib`, `features`,
`config` identity validation.

**Verified on hardware 2026-08-08:** `camera.py` (all six C920 controls survive
STREAMON with `warmup_frames = 8`), `bin/probe` (exits 0), and
`backends/litert_backend.py` — 10/10 geometry checks against a real face via
`bin/facecheck`. See RESULTS.md.

**DEAD ON THIS BOARD:** `backends/mp_backend.py`. MediaPipe's prebuilt aarch64
wheel is compiled with ARMv8.1 LSE atomics; the QRB2210 is ARMv8.0 and aborts
with SIGILL the moment native code runs. `import mediapipe` still *succeeds* —
the .so is loaded lazily — so never test availability by importing. Use
`backends.mediapipe_runs()`, which smoke-tests in a subprocess, because a
SIGILL cannot be caught with `try/except`. LiteRT is the primary path now, not
the contingency.

**Not yet run:** `bin/bench`, `bin/calibrate` — Gates 1b and 1c.

## Board-specific gotchas

- CPU governor defaults to `powersave` on some images. Set `performance` before
  benchmarking or your fps numbers are meaningless.
- Stop Arduino App Lab before benchmarking — it competes for RAM and CPU.
- Root partition is 10 GB regardless of variant. `df -h /` before big installs.
- The board requests 5V @ 3A. Undervoltage shows up as random instability that
  looks like a software bug. Check `dmesg | grep -i usb` when things are weird.
- `pip` needs `--break-system-packages` on this Debian.

## Keep RESTART.md current

This machine has crashed mid-session more than once. `RESTART.md` holds the
state a new session needs to pick up: what gate is done, what is next, and how
to get the board talking again. **Update it at the end of every session and
after every gate** — it is only worth anything if it is not stale.

## When measurements come in

Write fps, p95 angular error, and target size into `RESULTS.md` as you get
them. They pick the path (see `PLAN.md` § the Sunday-night fork) and you will
not remember them in September.

**Keep every calibration run.** Accuracy-over-time with and without online
recalibration is the strongest figure this project can produce, and the
"without" arm can only be recorded once — before anything is tuned.
