# Project context for Claude Code

Read this before proposing changes. It records decisions that were made for
reasons, so you don't spend the session rediscovering them.

## What this is

A measurement harness for adding eye tracking to a sip-n-puff assistive device
on an Arduino UNO Q. Deadline **30 Sep 2026**, contest entry (DigiKey/Arduino
Dream Lab, #UNOQDreamLab on maker.io). It is deliberately **not** a working eye
tracker — it exists to produce three numbers (fps, angular error, implied
target size) that decide the rest of the design.

Hardware: UNO Q 4GB (QRB2210, 4x Cortex-A53 @ 2.0 GHz, **Adreno 702 GPU**,
**no NPU**). Logitech C920x on USB. A separate CircuitPython board
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

**But run the edge detector on `max_gradient()`, not on luminance.** MEASURED
2026-09-20: an orange rim against brightly lit skin is close to isoluminant,
and in grayscale the right lens was **never found in any frame of a whole
session**. The left one survived only because it happened to sit against the
dark eye socket. Taking the per-pixel MAX gradient across B, G, R, a\* and b\*
took it from 2 candidates and one lens to 7 candidates and both lenses, and
the pair test from reject to accept.

This does **not** violate the rule above, and the distinction is the point: a
threshold picks a colour and a cut, so it is tuned at setup and drifts by
lunchtime. Max gradient picks no colour and has no cut — "an edge in any
channel is an edge" is equally true of all five rim colours and of a hall
whose lights change. The ellipse is still found geometrically.

**Use `find_rims_hough()`, not `find_rims()`, on a real face.** MEASURED
2026-09-20: `findContours` cannot deliver a rim from a photograph. The outline
is present at the right size and the right place — plainly visible in the edge
image — but it arrives broken into arcs AND fused with the brow and hair edges
that touch it, so no connected component is ever a ring. The best-scoring
contour in the whole frame was the **eye**. Morphological closing is the usual
answer and is unavailable here: a 3x3 close bridges the ~7-10 px rim gap and
destroys the annulus outright (`close_px=3` left 0 surviving candidates where
`close_px=0` left 3). `find_rims()` is kept for synthetic geometry and clean
images. The working path is Hough centres, then `ring_radii()` (radial
profile, median over 180 angles, so a gap costs a few angles and the median
does not move), then `ring_ellipse()`.

**Rank candidate pairs by SPAN RESIDUAL, never by ratio or size error.** Both
of those are cheap for clutter to satisfy — any two roundish blobs at roughly
the right spacing pass — so ranking by them ranks by how easy the test is to
fake. At 450 mm a spurious background pair beat the real rims 0.122 to 0.126
and the ladder read 353 mm against a board at 457. Span residual compares the
depth implied by the separation against the depth implied by the radii, so it
is a measurement the pair did not get to choose. Also gate on the geometric
depth bound `|z_r - z_l| <= separation_mm * sin(max_yaw)`, which scales with
distance where a fixed size fraction does not.

**The annulus is a WEAKER filter than it sounds.** At 450 mm all twelve Hough
candidates passed the 1.1364 +/- 6% ratio check, because `ring_radii` searches
peak pairs across a +/-45% radius span and can nearly always find one. Do not
treat "annulus formed" as evidence of a correct lock; it stayed at 100% in
every lighting condition including the ones that produced garbage.

**THE RIMS DO NOT MEASURE YAW, and this is not fixable by tuning.** MEASURED
2026-09-20 against the board on the forehead: gain **0.198**, correlation
**0.138**, rms error 22.9 deg — no signal, from frames whose distance is good
to millimetres. Yaw is read as a *difference of two radii*, and at 570 mm a
20 deg turn moves them apart by **2.2 px** while measured fit noise is
**4.2 px**. SNR 0.53. Reaching +/-5 deg needs the pair good to 0.56 px, about
7x better than achieved. Do not re-attempt this by filtering, seeding or
smoothing — the information is not in the image.

This *adds to* trap (c) rather than contradicting it. Eccentricity-derived yaw
does carry a couple of degrees of systematic bias, as stated — but 2 deg of
bias beats 19 deg of noise, and the depth-difference path trap (c) recommends
is what failed. **Untried and worth measuring: yaw from the MEAN AXIS RATIO of
the two rims**, which are coplanar and so should agree, averaging the per-rim
noise down.

**The rims give DISTANCE, not orientation.** Head rotation must come from the
marker board, the face mesh, or an accepted ~2 deg eccentricity bias. The gaze
mapping's `t_z` feature is fed by distance and is unaffected.

**Rim detection needs its own exposure.** `[camera] exposure = 156, gain = 0`
is a GAZE setting — short, so a saccade does not smear — and it left the face
at mean 20 with the rim edges under the noise floor. Use `rim_exposure = 312`,
`rim_gain = 192`. The trap: exposure 1250 also *reads* as well exposed (face
mean 113) and is worse than useless, because 125 ms of integration smears the
rim and the lens that was detected at 156 vanishes from the candidate list
entirely. Brighter and blinder at once. **Fix darkness with gain, not time** —
gain costs a 50 mm rim far less than it would cost an 8 px iris.

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


**No NPU, but there IS a GPU and it already has drivers.** CHECKED against
Qualcomm's own product brief 2026-10-03, because "inference is CPU-bound"
used to be written here as though it were a hardware fact. It is a choice.

- **There is no NPU.** The brief lists "AI Performance: Hexagon Processor,
  Adreno 702" and says inference runs "on-device ... **via CPU and GPU**".
  The Hexagon on this part is the **always-on sensor/audio DSP**, not a
  tensor accelerator -- no HVX/HMX, no TOPS figure. On this board it is not
  even exposed to userspace: **no `/dev/fastrpc*`, `/dev/adsprpc`, or
  `/dev/cdsprpc`**, and no QNN or SNPE runtime anywhere. There is no driver
  to fix; there is no path at all without Qualcomm's proprietary stack.
- **The GPU is real and working.** `/dev/dri/renderD128`, `msm_dpu` with
  `a702_sqe.fw` loaded, Mesa 25.2.6. **OpenCL 3.0 via rusticl** (`clinfo`
  reports device `FD702`, 844 MHz, fp16 yes, fp64 no, **1 compute unit**)
  and **Vulkan via turnip** (`Turnip Adreno (TM) 702`). OpenCV is even built
  with OpenCL and reports `useOpenCL: True`.

**BUT DO NOT GO AND PUT THE NEURAL NET ON IT.** MEASURED 2026-10-03, on the
`performance` governor:

| stage | per frame |
|---|---|
| USB grab, no decode | **37.8 ms** (26.4 fps) |
| **MJPEG decode** | **28.9 ms** |
| face-mesh inference | **10.7 ms** (93.6 fps alone) |

**Inference is the cheapest part of the pipeline.** Decode costs 3x what it
does. Moving the net to the GPU is optimising the 10.7 ms and leaving the
28.9 alone.

**The frame rate is QUANTISED, and that is the whole story.** `read()`
measures **66.7 ms** -- exactly 2 x the camera's 33.3 ms frame interval.
Decode (28.9) plus inference (10.7) is 39.6 ms, about **6 ms over budget**,
so every frame misses its slot and waits for the next one. Throughput halves
to 15 fps. **Get total per-frame work under 33 ms and the rate roughly
doubles**; shaving 6 ms is worth more than any amount of GPU work.

**Venus cannot help.** `/dev/video3` is a real hardware video decoder but it
accepts **H264, VP9, HEVC only** -- not MJPEG. And the C920 on this kernel
offers only YUYV and MJPG, so there is no H.264 stream to hand it.

**YUYV is a real alternative at 640x480 and a trap at 720p.** MEASURED:

| format | grab | read | decode/convert |
|---|---|---|---|
| MJPG 1280x720 | 37.8 ms | 66.7 ms (15.0 fps) | 28.9 ms |
| YUYV 1280x720 | 100.1 ms | 100.3 ms (**10.0 fps**) | 0.3 ms |
| MJPG 640x480 | 38.8 ms | 66.9 ms (14.9 fps) | 28.1 ms |
| YUYV 640x480 | 46.8 ms | 47.6 ms (**21.0 fps**) | 0.8 ms |

720p YUYV advertises 30 fps in its descriptor and delivers **10** -- USB 2.0
cannot carry 55 MB/s, so believe the measurement and not the descriptor. At
640x480 YUYV beats MJPEG outright, 21.0 fps against 14.9, and hands back
27 ms of CPU.

**The GPU governor was never pinned.** `/sys/class/devfreq/5900000.gpu` runs
`simple_ondemand` and idles at **355 MHz of 844**. Only the CPU governor was
ever set. If the GPU is ever used for anything, pin this too.

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

**Tested (174 passing):** `oneeuro`, `gesture`, `protocol`, `calib`, `features`,
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

**GATE 1c BARE-FACED, 2026-09-21: 3.27 deg mean / 5.56 deg p95** (26 held-out
points, 25 calibration points, ridge from blocked CV on training data only).
**That is PLAN.md Path B, not Path C** — the project had been on Path C since
run 7 and no hardware changed. In pixels, immune to the viewing-distance
question: 477 px -> 164 px.

Two fitting bugs got it there, neither visible in the training error:

- **`points = 9` was never enough FOR THE DEGREE-2 MODEL.** 66 parameters, 9
  points, trains on 8. 9 points gave 8.4-8.5 deg where 25 gave 2.34 on the
  same session and the same 26 validation targets. `config.toml` now says 25.
  **Read this together with the model finding below** -- with the linear
  model, 9 points is fine (3.49 deg) and the long grid is not worth it.
- **`ridge = "auto"` used leave-one-out CV, which under-regularises here.**
  Calibration samples are collected over ~112 s and are temporally
  correlated, so LOO leaves a held-out point's own time-neighbours in the
  training set and it is predicted partly from itself. Measured: LOO chose
  0.215 -> 11.97 deg, blocked 5-fold chose 46.4 -> 2.53 deg, oracle 2.22.
  `_cv_ridge` now uses **contiguous blocked folds**, and they must stay
  contiguous in COLLECTION order -- strided folds reproduce the LOO failure
  while looking like k-fold.

**The overfitted runs reported training errors of 0.16 and 0.40 deg** -- the
worse they overfitted, the better they looked. Never judge a calibration by
its training error; `auto` picked 100, 10, 1 and 0.1 across four runs of the
same subject at the same task.

**THE 7-PARAMETER LINEAR MODEL BEATS THE 66-PARAMETER DEGREE-2 POLYNOMIAL AT
EVERY POINT COUNT TRIED.** MEASURED 2026-09-21, scored on the same 26 held-out
targets:

| calibration points | `LinearMapper` (7 par) | `GazeMapper` poly2 (66 par) |
|---|---|---|
| 9 | **3.49 deg** | 8.37 deg |
| 25 | **3.01 deg** | 3.27 deg |

`LinearMapper` uses six features -- both iris x/y, yaw, pitch -- plus a bias.
Dropping `roll`, `t_x`, `t_y`, `t_z` and every quadratic term costs nothing
measurable and buys a model that cannot overfit a short grid. **9 points plus
linear is within half a degree of a 25-point fit at a third of the sitting**,
which is the whole argument for a short grid in a faire queue.

This reframes the headline above: 3.27 deg came from 25 points plus the
blocked-CV fix, but **3.49 deg was available all along** from 9 points and a
linear fit. The blocked-CV work was still necessary -- it is what makes poly2
safe at 25 points -- but poly2 probably should not be the default.

**The spike still defaults to poly2 above 16 points.** The bunny game has been
switched to linear for any grid it will present. Changing the spike deserves
its own fresh run rather than a refit, since every number above comes from
data collected for a different model. Do not reach for more model before more
light, more points, or a better seating distance.

**Do not choose the ridge by sweeping it against the validation set.** That is
what the held-out set exists to prevent. Doing it produced two
attractive-looking numbers on 2026-09-21 (5.63 and 2.91 deg) that are **not
accuracy**; the 3.27 deg figure is a fresh run whose penalty came from
training data alone.

**`viewing_distance_mm` is 504, not the 584 it said for months.** Every
angular error scales directly with it, so 584 inflated every degree figure by
16%. Degrees from different sittings are not comparable without each
sitting's distance -- **measure it every sitting, and prefer pixels when
comparing across sittings.**

**Verified on hardware 2026-09-20** against the marker board in the same
frames: rim **distance** works — 100% detection and 3.7 mm error IQR at
550 mm, 12.1 mm median IQR across a 450-700 mm ladder. The ~22 mm bias is the
board sitting behind the lens plane, **not** a radius error: six rungs
separate those hypotheses (constant 7.7 mm rms vs proportional 9.6 mm rms), so
`radius_mm = 25.0` stands. **700 mm is near the working limit** — the annulus
gap is 9.1 px at 450 and 5.9 px at 700 against a 4.0 px floor, and detection
falls to 57%. Seat visitors at 500-650. See RESULTS.md.

**Lighting: partial.** Mild backlighting (halo/face 1.21) did not hurt and in
fact gave the best pose rate measured; the annulus never dropped below 100%.
**The daylight/window case is NOT done** and is the one a faire will present.
Judge lighting by the halo around the head, not the frame average, and never
by face brightness — face spanned 91-152 while pose ranged 48-84% with no
ordering between them.

**USE THE RED LAMP. MEASURED 2026-09-23: it makes the gaze point 3.2x
steadier.** Four runs alternating on/off/on/off: 267.5 px (5.35 deg) without,
**82.5 px (1.65 deg)** with, difference +183.7 px with a 95% CI of
[+105, +243] that excludes zero. Run 3 (lamp on, LATER in the session) matched
run 1, so the effect tracks the lamp and not fatigue. Reproduced independently
in the bunny game: fixation scatter -44%, time to acquire -23%.

The lamp is 16 red LEDs plus one 850 nm IR LED. **Red at ~625 nm passes the
C920's IR-cut filter freely**, so the filter objection that applies to a pure
IR lamp does not apply here.

**But the ACCURACY benefit is unproven** -- offset-from-target overlapped
between conditions (235.8, 303.0 with vs 551.4, 297.0 without), because
accuracy is dominated by calibration quality, which varies more between
sittings than the lamp varies it. The claim is narrow: **steadier, yes; more
accurate, unknown.** Steadiness is what dwell selection consumes.

**`iris_contrast` from `bin/irprobe` is the metric that predicts this**, not
brightness: room light alone gave 7.70, room+lamp 15.11.

**GAIN IS A LIGHT METER ONLY BELOW ITS CEILING.** It read 109 in all four
lighting conditions while face brightness varied 5.6x and iris contrast 8.8x
-- pinned at maximum with no headroom. Reading "gain unchanged" as "the lamp
did nothing" would have discarded a lamp that was plainly working. This is the
second time a convenient proxy was trusted past its range; face brightness
failing to predict rim detection was the first.

**Measure fixation steadiness with MANY SHORT fixations, never one long
hold.** MEASURED 2026-09-23: the old `bin/fixate` showed one dot for 15 s and
reported scatter about its single mean. Two runs of the SAME condition gave
153.8 and 276.9 px -- an 80% spread -- because the subject's own ocular drift
over a long hold was being counted as tracker noise (lag-1 autocorrelation
0.60-0.74). On synthetic data with a known answer of 42 px the old statistic
reported 169; the rebuilt one reports 41.

The rebuilt protocol: ~20 fixations of ~1.5 s at varying screen positions,
the first 0.6 s of each discarded as saccade and overshoot, scatter measured
about EACH fixation's own mean, a bootstrap CI on the median, and the A/B
bootstraps the DIFFERENCE rather than printing two CIs and inviting a
comparison by eye. **Alternate conditions and repeat each at least twice** --
one run per condition cannot separate a lamp's effect from the subject tiring.

It also separates two things the old version conflated: per-fixation SCATTER
(steadiness, which light improves) from OFFSET to the dot (accuracy, which
calibration improves).

## Board-specific gotchas

- CPU governor defaults to `powersave` on some images, and **reverts to
  `schedutil` on every reboot**. Set `performance` before ANY timing, not just
  benchmarking: MEASURED 2026-09-23, the full pipeline ran at 7.8 Hz on
  `schedutil` against a camera managing 19.4 fps alone. Timing measured before
  setting it is void.
- **The board's IP changes between boots.** It held 10.42.0.250 for weeks and
  came back as 10.42.0.119, which presents as `No route to host` -- identical
  to a board that failed to boot. `hil` now pings the configured address and,
  if silent, asks every reachable host on the link for its hostname until one
  answers `uno-q`, then rewrites `.hil.env`.
- **The USB speaker's own PCM volume resets to 0% on re-enumeration**, while
  PipeWire still reports its sink at 54%: routed correctly, completely silent.
  The kernel says why -- `Unlikely big volume range (=4096)`, so the device
  misreports its curve and the percentage never reaches it. Address the card
  by NAME (`amixer -c P10S`), never by number: P10S was card 1 one night and
  card 0 the next, swapping with the C920's own microphone.
- **A display that comes up generic at 1024x768 with no EDID** means the
  ANX7625 DisplayPort bridge failed its AUX handshake (`dmesg | grep
  anx7625`). **A warm reboot does not clear it and neither does re-plugging
  the cable** -- only a true power cycle does. MEASURED: 215 AUX failures
  starting 5.4 s after boot, zero after a cold start.
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
