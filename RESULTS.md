# Maker Faire, 2026-09-27 — 137 visitors, 2732 throws

The first data from people who are not the developer. `analyse_study.py` over
`study_data/bff_gaze_study.jsonl`.

| | |
|---|---|
| sessions / throws | **137 / 2732** |
| valid after auto-flags | 1478 (**54%**) |
| accuracy p50 / p95 | **6.26 deg / 20.60 deg** |
| worst | 49.16 deg |
| bias | -6.3, 2.7 px |
| scatter about the bias | x 88 px, y 62 px |
| seating p50 | 495 mm (p5-p95 394-637) |

**6.26 deg is the honest headline, not 3.27.** One practised subject who knows
to hold still is not the population, and the gap between those two numbers is
the size of that difference.

**Accuracy decays with movement away from the calibration distance.** Stayed
put (|d| <= 18 mm): 5.30 deg (n=735). Moved: 8.93 deg (n=736). **Half of all
visitors moved.** Recalibrate on a shift; do not read this decay as tracker
noise.

**The error is bias/drift-dominated, not jitter.** Per-throw fixation scatter
24 px p50 against an error scatter of 88 x 62 px -- ratio **0.22**. Averaging
over a dwell will NOT rescue it. The gain has to come from calibration, not
filtering, which is the opposite of what the steadiness result suggests alone.

**The auto-flags dropped 43% of throws and moved p50 by only -0.46 deg.** A
filter eating a third of the data while barely changing the answer is largely
measuring itself. `head_turned` 538, `face_lost` 511, `head_pitched` 348,
`bad_distance` 302. Median error of EXCLUDED throws was 7.08 vs 6.26 kept --
close enough that the flags are not separating good from bad very sharply.
Read the counts as a description of a faire crowd, not of the tracker.

**One row has dist_mm = -509.5 and is NOT flagged.** A physically impossible
seating distance reached the summary. One row in 1964 changes nothing, but a
guard that misses a *negative* distance will miss a merely wrong one, and
those do not announce themselves.

**The log was crash-damaged and nearly unreadable.** Line 1633 came back with
234 NUL bytes spliced in front of it -- ext4 had allocated the block but the
write never landed. `json.loads` died on it and took all 137 sessions with
it. Stripping the NULs recovers the line intact, so nothing was lost, but
`analyse_study.load()` now skips unparsable lines and **prints the count**.

**Not yet done:** per-visitor breakdown, learning within a session, and
whether 9 points + linear held up in a queue.

# Results

Measurements from the actual board. Written as they arrive, because by
September nobody remembers why `focus` is 30.

Hardware: UNO Q 4 GB (QRB2210), Logitech C920x, Debian 13 trixie, kernel
6.16.7, glibc 2.41, Python 3.13.5. CPU governor `performance`, all 4 cores at
2016 MHz. Screen 1920x1080, active area 338 x 190 mm, eye-to-screen 584 mm.

**Scale, for reading everything below:** 0.1759 mm/px, and at 584 mm
**1 deg = 10.2 mm = 58 px**.

---

## The headline finding: MediaPipe cannot run on this board

**2026-08-08.** The prebuilt `mediapipe` 1.0.0 aarch64 wheel is compiled with
ARMv8.1 **LSE atomics**. The QRB2210's core is ARMv8.0 and has none, so the
library aborts the process with SIGILL the instant native code executes.

```
/proc/cpuinfo Features:  fp asimd crc32        <- no "atomics"
CPU architecture:        8
mediapipe smoke test:    killed by signal 4 (SIGILL)
```

`import mediapipe` **succeeds**, because `libmediapipe.so` is loaded lazily.
Only execution fails. Any check that tests importability reports a healthy
backend that will kill the program on the first frame containing a face.

This invalidates the conclusion in README.md § "The ARM64 question, resolved".
That section is right that the wheel *installs* -- glibc 2.41 is far past the
2.28 the manylinux tag needs -- and wrong that installing implies running.
**Installability and executability are different questions on ARM.**

Consequence: `backends/litert_backend.py`, written as the contingency and
shipped unverified, is now the primary and only path. See REPLICATION.md.

---

## Gate 0 -- `bin/probe` exits 0

| Check | Result |
|---|---|
| Platform | aarch64, glibc 2.41, 3.58 GB usable, 4 cores |
| MJPEG on `/dev/video0` | yes (required; YUYV at 1080p30 exceeds USB 2.0) |
| **C920 control locking** | **all 7 controls verified after STREAMON** |
| Backend | litert (mediapipe unavailable, reason reported) |
| Capture | 1920x1080 |

The C920 `VIDIOC_STREAMON` reset -- the trap `camera.py` is built around -- is
handled correctly on real hardware. `exposure_time_absolute`, `focus_absolute`,
`auto_exposure`, `focus_automatic_continuous`, `gain` and
`white_balance_automatic` all read back at their requested values after stream
start, with `warmup_frames = 8`. No need for the 15 that PLAN.md's Gate 0 table
suggests as the fallback.

### C920 exposure is quantised to EV stops while streaming

Not documented anywhere obvious, and it looks exactly like the STREAMON reset
the whole camera module exists to defeat -- so the natural response is to raise
`warmup_frames`, which cannot ever fix it.

With **no stream open**, every value sticks: 100, 156, 200, 250, 300, 400.
While **streaming**, the same writes land on a ladder:

| requested | actual | | requested | actual |
|---|---|---|---|---|
| 50 | 38 | | 250 | **156** |
| 100 | 77 | | 300 | 312 |
| 156 | 156 | | 500 | 312 |
| 200 | **156** | | | |

`39, 78, 156, 312, 625, 1250, 2500` -- factor-of-two steps, one EV apart, with
anything in between floored to the stop below. The control advertises
`min=3 max=2047 step=1`, and its default is 250, so nothing about the interface
hints at it.

The configured `exposure = 250` was therefore silently running at 156 the whole
time. Now set to **156** explicitly. 312 (~31 ms) is the next stop up and is
close to the entire 33 ms frame at 30 fps, which invites motion blur on a fast
gaze shift, so 156 is the right bright-room choice.

Separately, `exposure_dynamic_framerate` was found set to **1** (its default is
0). That control lets the camera shorten exposure on its own to hold frame
rate, overriding manual exposure. `camera.py` now forces it to 0 before writing
the exposure value.

---

## Camera truth -- focus swept against iris sharpness

`bin/facecheck --step 5 --frames 5`, subject seated at 584 mm. Metric is
variance of the Laplacian restricted to the iris neighbourhood, not the whole
frame -- a full-frame focus metric mostly measures the background.

| focus | sharpness | | focus | sharpness |
|---|---|---|---|---|
| 5 | 16.2 | | 40 | 21.5 |
| 20 | 12.7 | | 55 | 10.4 |
| 25 | 13.7 | | 70 | 6.3 |
| **30** | **25.7** | | 85 | 5.2 |
| 35 | 25.6 | | 100 | 4.8 |

**`focus_absolute = 30`**, flat to 35. Better than the far end by 5.4x. Face
detected on 5/5 frames at all 21 values swept, so the sweep measures sharpness
rather than detection reliability.

**Iris radius: 13.2 px.** This is the optical resolution the entire project
rests on. Comfortably above the ~5 px point where PLAN.md path C (narrower lens
/ Arducam M12) would become the argument. The C920's 78 deg lens is adequate at
this distance.

---

## Backend verification -- 10/10

`bin/facecheck` against a real face, at focus 30:

```
OK   landmarks inside frame                        100.0%
OK   478 landmarks (refined, has iris)             478
OK   eyes above nose tip                           eye y=458  nose y=528
OK   nose above chin                               nose y=528 chin y=704
OK   forehead above eyes                           brow y=344
OK   interocular / face height in 0.30-0.75        0.429
OK   right iris ring circular (cv<0.25)            0.079
OK   right iris diameter / eye width in 0.25-0.95  0.419
OK   left  iris ring circular (cv<0.25)            0.082
OK   left  iris diameter / eye width in 0.25-0.95  0.418
detector score 0.869
```

These are geometry assertions, not a visual check, because the failure mode
this backend was most likely to have is landmarks that are individually
plausible and collectively wrong -- a bad ROI inverse still yields 478 points
inside [0,1], it just does not arrange them like a face.

Reference frames from the sweep are saved on the board at `ref_frames.npz`
(44 arrays), so backend changes can be re-checked offline without a sitting.

---

## Preliminary latency -- NOT the bench result

Measured incidentally by `facecheck` on **full 1920x1080 frames**, which is not
how the pipeline runs. `bin/bench` downscales first; these are an upper bound.

| stage | ms |
|---|---|
| detector | 13.5 |
| landmark | 36.2 |
| **total** | **49.7 (~20 fps)** |

Raw model timings alone, on noise, 4 threads:

| model | p50 | p95 |
|---|---|---|
| `face_detector.tflite` (128x128) | 7.3 | 8.8 |
| `face_landmarks_detector.tflite` (256x256) | 24.4 | 25.4 |
| combined | ~31.7 (~31 fps ceiling) | |

So roughly 18 ms per frame is currently going into letterboxing and
`warpAffine` on a 1080p frame. Downscaling before `detect()` should recover
most of it. **Gate 1b needs the real sweep before any of this is trusted.**

---

## Gate 1b -- `bin/bench` : p50 18-25 fps, p5 14.2

Subject seated at ~584 mm, App Lab and dockerd stopped, governor `performance`.

### Before and after

| | before | after |
|---|---|---|
| fps p50 | 11.5 | **18.0-24.6** |
| fps p5 | 10.6 | **14.2** |
| detect rate | 100% | 100% |
| capture_ms | 30.5 | 11.7 |
| detect_ms | 11.0 | 0.4 |
| resize_ms | 6.7 | 1.2 |

Six changes, each measured rather than assumed:

1. **Threaded capture.** 30.5 ms per frame was spent inside `cap.read()` --
   exactly 1/30 s. Not work; the pipeline standing still waiting for the
   sensor. A single-slot newest-wins grabber overlaps it. Deliberately never
   returns a duplicate frame: that would let the benchmark report throughput
   the camera is not delivering.
2. **ROI tracking.** The detector ran on every frame. MediaPipe's own graph
   detects once then derives each ROI from the previous frame's landmarks,
   re-detecting only on loss. `detect_ms` p50 is now 0.0. The tracking scale is
   self-calibrated from the detector path rather than hardcoded -- a constant
   there would frame the face slightly differently and the landmark model,
   trained on one framing, would silently degrade the longer tracking ran.
3. **720p capture, not 1080p.** The original "capture wide, crop later"
   reasoning is sound but did not describe this pipeline: the frame was
   downscaled *before* the backend, and the backend cropped from the downscaled
   copy, so the 1080p pixels were discarded before anything used them -- while
   their MJPEG decode cost was paid every frame.
4. **3 inference threads, not 4.** Four threads on four cores starved the
   MJPEG decode in the capture thread, so the pipeline waited on a camera it
   had just outrun. 4thr 18.0 fps, 3thr 23.2 fps.
5. **`input_size = 1280`, i.e. no downscale at all.** Both models have FIXED
   input sizes -- 128 detector, 256 landmark -- so downscaling first buys *no
   speed whatsoever*; it only discards detail before the 256 crop.
   `input_size` is an accuracy knob on this backend, not a speed knob, which
   means Gate 1b's "pick the largest input_size whose p5 stays above 15" does
   not apply as written. Setting it to the capture width makes the resize a
   no-op (11.8 -> 1.1 ms) *and* crops from full-resolution pixels. Faster and
   sharper at once.
6. **`num_threads` never reached the backend.** `backends.create()` dropped
   `**kw`, so config was ignored and the default 4 always won.

### Why p5 is stuck at 14.2, and why the bar cannot be met

p5 did not move for *any* configuration tried -- thread count, resolution,
`REDETECT_EVERY`, input size. It sits at 14.1-14.4 throughout. That stability
is the finding.

**15.0 fps is exactly two camera frame periods** (2 x 33.3 ms = 66.7 ms). At
30 fps, frame completion times quantise to 33 / 67 / 100 ms. A frame that
misses its period waits for the next one and lands at exactly 15.0 fps or
worse. So p5 >= 15 requires that 95% of frames complete within roughly ONE
period.

The 256x256 landmark model costs **36-37 ms on its own** -- already above the
33.3 ms period, before capture, features or anything else. One frame per period
is therefore arithmetically impossible on this board with this model.

**30 fps is this C920's maximum at 720p MJPG** (checked:
`--list-frameintervals` offers 30/24/20/15/10/7.5/5). A faster camera would
raise the ceiling; nothing in software will.

So Gate 1b's threshold is not merely unmet, it is unmeetable as written. The
honest statement is: **sustained p50 of 18-25 fps, with a 5% tail at 14.2 fps
caused by camera frame quantisation, not by compute stalls.** Run-to-run p50
varies 18.0-24.6 depending on lighting and pose.

### Fork implication (PLAN.md § the Sunday-night fork)

On the fps criterion this is **Path B** (fps >= 15), and by p50 it touches
Path A (>= 20) on good runs. The fork now depends entirely on the angular
error from Gate 1c.

### Saved on the board

| file | what |
|---|---|
| `bench_baseline.json` | the pre-optimisation truth, 11.5 fps |
| `bench_tracked.json` | threading + tracking only |
| `bench_optimised.json` | the 320/480/640 sweep at 720p |
| `bench_final.json` | final config, 250 frames |

All four pulled to `board_artifacts/` on the dev machine 2026-08-16, along with
`soak.log` / `soak.done` / `load.log`. `ref_frames.npz` (39 MB) is still
board-only.

---

## Gaze in a real application, 2026-09-16 — the vertical axis is unusable

Bunny Feeding Frenzy was wired to the gaze pipeline and played on the board.
Running a real application turned out to be a better measuring instrument than
any of the bench tools, because it exercises the mapping continuously for
minutes at a time instead of for one 25-point sitting.

**The finding.** From the game's own telemetry, comparing where the gaze said
the player was looking against where the bunny actually was:

```
session A:  gaze mean y = 180, 189, 183       bunnies at y ~130-160
session B:  gaze mean y =  51,  48, 3, 4, 1   bunnies at y ~148-165
```

The vertical aim pins to the BOTTOM of the screen in one session and the TOP in
the next, then clamps at the edge. That is not drift -- drift is monotonic and
was separately measured at r(time, error) = +0.57 -- it is an essentially
ARBITRARY fit, landing somewhere different each calibration.

It corroborates, from an entirely independent direction, the correlation
already measured on the calibration data:

| axis | predicted-vs-true correlation |
|---|---|
| horizontal | **r_x = 0.78 - 0.90** |
| vertical | **r_y = 0.22** |

There is almost no vertical signal to fit, so the vertical half of every
mapping in this project has been close to noise. Horizontal has been working
the whole time.

**What follows from it.** Stop fitting the axis that does not work. Steer with
gaze-x and pin y to the target band. In the game the bunny spawn band is 26 px
tall out of 240, so discarding y costs nothing there -- and for the AAC grid in
`PLAN.md` it argues for **wide, short cells** rather than a square grid, which
is a design consequence, not a workaround.

This is specified and NOT yet implemented.

### Secondary findings, all measured in play

- **A degree-2 polynomial cannot be fitted from a short calibration.** 9 points
  against 66 parameters extrapolated to spans of **355,000 px** on a 320 px
  screen once the head left the calibration manifold. A 7-parameter linear fit
  is bounded and stable. This is the same over-parameterisation seen in Gate 1c,
  now visible in seconds rather than inferred.
- **Ridge on unstandardised features crushes the fit** -- training error 108 px
  and a predicted range of 27 px against a 243 px target. `calib.py` already
  documented this in `_moments()`; the lesson had to be learned twice.
- **Targets must be larger than the error.** The bunny was 3.7 deg against a
  5-8 deg error. Enlarged to 7.4 deg.
- **The screen is a usable face lamp.** Calibration now runs white-on-dark
  inverted and play carries a white border, because face brightness was
  measured at 21 under room light against the 90-140 the landmark model wants.

Full detail, including the traps that cost time, is in the game's own
`GAZE.md`.

---

## Full-res ROI crop — TRIED 2026-08-16, made things WORSE. Reverted.

The lead from run 7 was that iris resolution was the binding constraint: 8.3 px
at 1280x720 against 13.2 px measured at 1920x1080, with vertical gaze signal
nearly absent (`r_y` = 0.22). `config.toml` already named the fix -- crop the
face ROI from the full-res frame while detecting on a small one -- so it was
implemented (`litert_backend.detect(rgb, full=...)`) and measured.

**It does not work, and the reason is worth keeping.**

| | run 7: 720p, crop from same frame | run 8: 1080p, full-res crop |
|---|---|---|
| iris radius | 8.3 px | **10.0 px** |
| **raw iris-vs-target corr, x** | **0.902** | **0.664** |
| **raw iris-vs-target corr, y** | **0.622** | **0.545** |
| validation error | 8.2 deg | **18.2 deg** |
| face detection rate | 100% | **55%** |
| fps p50 | 23 | 14.8 |

The middle two rows are the measurement that matters: that is the **raw feature
signal**, computed before any fit, so it cannot be blamed on ridge, capacity or
drift. More iris pixels produced a *worse* gaze signal.

**Why**, and it is in the backend's own comments: the landmark model is trained
on ALIGNED faces, and the ROI is derived from the **downscaled detection
image**. Cropping from 1920 magnifies any ROI centring error 3x, so the face
lands mis-centred in the 256x256 crop. Sharpness went up, alignment went down,
and alignment matters more. The detection rate collapse (100% -> 55%) is the
same cause: a face at 701 mm is small in a 640-wide detector input.

**Do not retry this without first making the ROI itself more precise** -- e.g.
run the detector at full res too (expensive), or refine the ROI with a second
landmark pass before the final crop. The `full=` parameter is kept, tested
(`tests/test_fullres_crop.py`, 5 tests) and unused; a plain `detect(rgb)` is
byte-identical to before.

### Separately: the seated distance is wrong in config

`bin/bench` reports **median face distance 701 mm**, while `config.toml` says
`viewing_distance_mm = 584`. Angular error scales with that distance, so every
degree figure in the Gate 1c section is roughly **17% too large** (584/701).
That does not change any conclusion -- Path C at 5.1 deg is still Path C at
4.3 deg -- but it must be fixed before a number is published. Either sit at
584 mm as the config assumes, or re-measure and update `[screen]`.

---

## Gate 1c run 7 — AUTHORITATIVE. Runs 1-6 were confounded.

**Read this before anything below it.** Runs 1-6 presented both grids in raster
order, which made elapsed time collinear with target y (**r = +0.981** in the
calibration block). Under that confound "the head drifts over time" and "the
head follows the target down the screen" are the same measurement, and every
correlation involving head pose or time was inflated. `bin/calibrate` now
randomises presentation order (`--seed`, saved with the run; `--raster` only to
reproduce the old runs). Run 7 is the first clean measurement.

Confound gone: r(time, target y) **+0.981 -> -0.127** (calibration),
**+0.741 -> -0.333** (validation).

### The numbers, cleanly measured

25-point calibration, 26-point validation, chin rest, randomised order,
`ridge = "auto"` (CV chose 31.6).

| clicks of online recalibration | held-out mean | p95 |
|---|---|---|
| 0 | 8.22 deg | 16.54 deg |
| 1 | 7.37 | 14.94 |
| 3 | 6.11 | 12.02 |
| 8 | 5.58 | 10.29 |
| 16 | 5.48 | 8.86 |
| 20 | **5.12** | **7.95** |
| **chance** | **7.78** | **11.94** |

**Uncalibrated-by-clicks accuracy is at chance (8.22 vs 7.78).** Online
recalibration improves it monotonically and plateaus around **5 deg mean /
8 deg p95** by 20 clicks.

### Corrections to what runs 1-6 appeared to show

- **`r_x = 0.997` was an artefact.** Honest value on clean data: **0.784**.
  Under raster order, predictions driven by head pose correlated with targets
  ordered by position, which tracked time -- inflating it.
- **"2.42 deg after rescaling" was inflated by the same confound** and by
  fitting 2 parameters on 6 points. It is not a real accuracy figure.
- **Vertical gaze is very weak: `r_y = 0.221`**, slope 0.56. Horizontal carries
  most of what signal exists (`r_x` 0.784, slope 0.89).

### What IS now established

- **Drift is real and, for the first time, measurable.** With position
  decorrelated: r(time, `t_y`) = **+0.854**, r(time, `t_z`) = -0.813, and
  crucially **r(time, error) = +0.565**. The head moves monotonically over a
  ~3 minute session and the error grows with it. That is a clean drift
  measurement, impossible under the old raster design.
- **Online recalibration works directionally** -- 8.22 -> 5.12 deg over 20
  clicks, monotonic. The project's central design bet is supported in
  *direction*, though not to a usable absolute level yet.

### Where this leaves the fork

**On PLAN.md's criteria this is Path C** (error > 3.5 deg): "Do not build on
this. Diagnose first." Even 20 clicks of online recalibration plateau at
~5 deg, and the p95 of 7.95 deg implies a minimum reliable target far larger
than an AAC cell.

The strongest remaining lead is **iris resolution**, and `config.toml` already
names the fix: iris radius is **8.3 px** at the current 1280x720 capture,
against **13.2 px** measured at 1920x1080 on 2026-08-08. Gate 1b moved capture
to 720p for fps. The config comment spells out the untried option:

> If Gate 1c wants sharper irises, the fix is to crop the face ROI from the
> FULL-RES frame while detecting on the small one. Then, and only then, go back
> to 1080p.

That is the next experiment, and it is a real one: it would recover iris pixels
without paying the full 1080p pipeline cost. The near-absent vertical signal
(`r_y` = 0.221) is exactly what too-few iris pixels looks like, since vertical
iris excursion is the smaller of the two and is further cut by eyelid occlusion.

---

## Gate 1c run 5 — SUPERSEDED (confounded by raster order; see run 7)

**Run 5 (chin rest, drift-instrumented) settles it.** The tracker sees gaze
clearly; the fit then squashes its own output toward the screen centre, and
because the centre is exactly what "chance" predicts, an excellently-ordered
prediction scores like a blind one.

Reported validation: **14.41 deg mean / 21.32 deg p95**. Now the diagnosis.

### The evidence, in the order it forced the conclusion

**1. Drift is real, tiny in millimetres, and AMPLIFIED by the fit.** The
instrumentation added this session says the gap between blocks was **5 s**, not
minutes -- yet head pose still moved 2.05 sd in `t_y`. In absolute terms the
chin rest held the head to **~3 mm sd** and it then shifted **~6 mm**. Six mm at
584 mm is ~0.6 deg of geometry, so it cannot produce 14 deg *directly*. But the
fit leans on head-pose features (`t_y` correlated +0.93 with target y in run 2),
so a 6 mm pose change drags the whole mapping with it. **Small in millimetres,
large in degrees.** Neither "drift is the cause" nor "drift is too small to
matter" is correct on its own.

**2. The model ranks the held-out points nearly perfectly.**

| axis | predicted vs true |
|---|---|
| x | **r = +0.992** |
| y | r = +0.802 |

**3. But its output is compressed ~2.5x.** True x spans 153..1344 px; predicted
x spans 847..1317. The predictions are squeezed into the middle of the screen.

**4. Rescaling recovers almost everything.**

| | mean | p95 |
|---|---|---|
| as fitted | 6.66 deg | 12.48 deg |
| after an optimal per-axis rescale | **2.42 deg** | **3.87 deg** |
| chance | 7.84 deg | 12.54 deg |

`r_x = 0.99` holds at *every* ridge value from 1e-6 to 1, so the signal is not
a ridge artefact. What ridge changes is the gain: slope 0.80 at 1e-6 (correct
scale, noisy) through 2.69 at 1e-2 (lowest error, badly compressed) to 174 at
1.0. The fit is trading scale for variance and losing both ways.

**Caveat, stated plainly:** the 2.42 deg figure fits 2 parameters per axis on
6 validation points. It is optimistic and is an *upper bound on how much of the
error is scale rather than noise* -- not a Gate 1c result. The robust part is
`r_x = 0.992`, which needs no fitting.

### What this means

- **Not the camera, the backend, the features, the point count, or head
  motion.** All were ruled out across five sittings; see below.
- **It is the regression.** Ridge penalises the polynomial coefficients, which
  sets the output gain, while the unpenalised bias holds the centre -- so
  regularisation shrinks predictions toward the middle of the screen. With 25
  points against 66 parameters there is no ridge value that is simultaneously
  well-scaled and low-variance.
- **Vertical is genuinely weaker than horizontal** (r 0.80 vs 0.99), which is
  expected: eyelid occlusion and a shorter vertical iris excursion.

### The fix was implemented, and it was only PART of the story

Standardised ridge + CV-selected penalty are now in `calib.py` (`_moments`,
`_solve`, `ridge="auto"`). Evaluated on run 5's real held-out block:

| fit | ridge | mean | p95 | slope x | r_x |
|---|---|---|---|---|---|
| shipping default | 0.001 | 15.22 | 24.20 | 0.59 | 0.644 |
| standardised | 0.1 | 13.68 | 21.29 | 0.79 | 0.944 |
| standardised + auto | 10 (CV) | **12.58** | 18.84 | 0.67 | **0.997** |
| chance | -- | 7.84 | 12.54 | -- | -- |

**Honest verdict: standardising helped, but nowhere near enough.** 15.22 ->
12.58 deg is real and the ordering became near-perfect (r_x 0.644 -> 0.997),
but the result is still worse than chance. The "wrong gain" diagnosis was
correct about the *symptom* and incomplete about the *cause*.

### What is actually going on: drift is an AFFINE error, and it is correctable

`r_x = 0.997` with `slope_x = 0.67` says the mapping is right up to an affine
transform -- the ordering is essentially perfect and the scale/offset is wrong.
That is exactly the shape of error a **6 mm head shift** produces, and run 5
measured that shift directly (`t_y` moved 2.05 sd between blocks, 5 s apart).
Random noise does not look like this; a systematic pose change does.

An affine error needs very few points to correct -- which is precisely what
online recalibration does. Feeding validation points back as confirmed clicks:

| clicks | held-out mean error |
|---|---|
| 0 | 12.58 deg |
| 1 | 8.52 deg |
| 2 | 7.01 deg |
| 3 | **6.18 deg** |
| chance | 7.84 deg |

Monotonic, and it beats chance from two clicks. **This is the project's central
design bet -- that online recalibration is what makes a cheap tracker usable --
and it is now supported by measurement rather than argument.** It is also the
strongest evidence so far that the accuracy-over-time figure PLAN.md wants is
worth producing: the "without" arm really is bad, and clicks really do fix it.

**What is still NOT established:** an absolute accuracy figure. 6.18 deg after
3 clicks is measured on 3 held-out points, and the trend has not been followed
to convergence. Gate 1c still has no number, and none of the above should be
quoted as one.

### Superseded: the original "just standardise it" recommendation

*(Kept for the record -- this was written before the fix was measured. It was
right that the penalty was misallocated, wrong that it was the whole cause.)*

Standardise the features (z-score) before the ridge solve, and choose the
penalty by cross-validation rather than the fixed `ridge = 0.001`. The current
scaling in `features.extract` (`t/100`, `t_z/1000`) is a hand-set approximation
of exactly this, and its own comment says why it matters: without it "the ridge
penalty would fall almost entirely on the eye terms". The measurement above says
that is still happening.

**This is tuning, so it interacts with the one-shot baseline rule** (PLAN.md
Evening - First accuracy number). The judgement call, for the record: a baseline
of "the fit mis-scales its own output" is not the "without online
recalibration" arm -- it is a defect that would make the *with* arm look good
for the wrong reason. Fix the gain first, then record both arms against a
mapping that works. Runs 1-5 are all kept regardless.

**Update after implementing it:** the gain defect was real but secondary. The
dominant term is drift-induced affine error, and the "without recalibration"
arm is *supposed* to capture exactly that. So the baseline is now recordable
honestly -- against the standardised fit, which no longer has the coefficient
-scaling defect confounding it.

---

## Gate 1c runs 1-4 — the road to that conclusion

**Four sittings.** The headline is not an accuracy number, it is a mechanism:
**within a calibration block the tracker is good (2.7 deg); across a few
minutes it collapses (11.6 deg).** That gap is drift, and it is the exact thing
online recalibration exists to fix. See "What run 4 changed" below.

| run | grid | protocol | val mean | val p95 |
|---|---|---|---|---|
| 1 | 9 pt | normal | 16.49 deg | 27.79 deg |
| 2 | 25 pt | normal | 15.21 deg | 19.32 deg |
| 3 | 25 pt | "hold head still" (not achieved) | 8.97 deg | 13.90 deg |
| 4 | 25 pt | **chin rest** | 11.64 deg | 18.65 deg |
| 5 | 25 pt | chin rest + drift instrumentation | 14.41 deg | 21.32 deg |
| -- | -- | **chance (predict centroid)** | **7.84 deg** | **12.53 deg** |

**Read these with run 5's finding above:** the validation column is dominated by
the fit compressing its own output toward the screen centre, which is why every
row sits near chance regardless of protocol. The ordering information is intact
(`r_x = 0.99`); the gain is not.

The validation column is the harness's separate grid, collected minutes after
the calibration block. Chance is computed on that same grid, so it is
like-for-like. **On that measure every run is at or worse than chance** -- but
that is a statement about the *stale* mapping, not about the pipeline.

### What run 4 changed -- the chin rest worked, and that is what proved it

Head translation range across the grid:

| run | tx | ty | tz |
|---|---|---|---|
| 2 normal | 5.6 | 32.9 | 37.9 mm |
| 3 "head still" | 20.4 | 30.3 | 23.3 mm |
| **4 chin rest** | **8.8** | **12.3** | **22.3 mm** |

With the head mechanically fixed the eyes had to do the work, and the gaze
signal strengthened exactly as it should: `lx` vs target x **-0.904** (was
-0.827), `ly` vs target y **+0.807** (was +0.479), and the `ly` feature range
quadrupled, 0.0286 -> 0.1232.

**Better input, worse validation, best-ever training error (1.17 deg).** That
combination is not a head-pose problem and not a capacity problem. It is the
mapping going stale between blocks.

### Leave-one-out on run 4 -- what the pipeline can actually do

LOO holds out points from *within* the calibration block, so it measures the
tracker with a **fresh** mapping:

| model | params | LOO mean | LOO p95 |
|---|---|---|---|
| degree-1, all 10 feats | 11 | **2.73 deg** | 7.75 deg |
| degree-2, iris+yaw+pitch | 28 | 3.36 deg | **6.73 deg** |
| degree-2, all 10 (CURRENT) | 66 | 3.07 deg | 8.37 deg |
| chance | -- | 9.43 deg | 14.43 deg |

**2.73 deg mean is Path B territory** (PLAN.md: fps >= 15 and error 2.0-3.5).
So the hardware, the camera, the backend and the features are all good enough.

Two secondary findings, neither acted on yet:

- **Degree-1 (11 params) beats the current degree-2 (66) on this data.** 66
  parameters against 25 points was always thin. Changing it is tuning, so it
  waits until the baseline arm is recorded.
- The best p95 (6.73) comes from dropping the translation features, consistent
  with them carrying drift rather than gaze.

### So what is the Gate 1c number?

Arguably **run 4 IS the baseline**: 11.64 deg mean / 18.65 deg p95 is what a
fixed mapping with no online recalibration is worth after a few minutes. That
is the "without" arm the whole accuracy-over-time figure needs, and PLAN.md
says it can only be recorded once. It is unflattering because the honest
version of that arm *is* unflattering.

**But do not write it into the fork yet.** The harness does not save the
validation block's feature vectors, so drift cannot be quantified directly --
we infer it from the LOO/validation gap. Fix that first (below), because a
number this consequential should be measured, not inferred.

### Next, in order

1. ~~Save validation features~~ **DONE 2026-08-16.** `bin/calibrate` now
   writes `vX`, `vy`, `t_cal`, `t_val` into the `.npz` and prints a drift table
   at the end of every run. `GazeMapper.save(**extra)` carries them; `load()`
   ignores them, so the model format is unchanged. 6 tests in
   `tests/test_calib_extra.py`, suite now 96.
2. **Re-run with the chin rest.** The drift table now answers the question
   directly instead of by inference. Only the six head-pose features are drift
   indicators -- the iris features *should* differ between blocks, since the
   two grids point at different places, and a gaze feature that did not move
   would mean the tracker was dead.
3. Only then decide degree-1 vs degree-2, and record the baseline properly.

### Ruled OUT, with evidence -- do not re-derive

- **Not too few points.** 9 -> 25 moved validation 16.49 -> 15.21 deg.
- **Not regularisation.** Ridge swept 1e-4..1e3 by LOO; larger is monotonically
  worse, converging to chance.
- **Not extrapolation.** Five of six validation points lie *inside* the
  calibration grid (0.12-0.88), including dead centre; errors are uniform.
- **Not camera or detection.** `bin/facecheck` 10/10 at the same sitting,
  `bin/probe` exit 0.
- **Not the subject failing to fixate.** `lx` correlates **-0.904** with target
  x under the chin rest.
- **Not head motion alone.** The chin rest halved head translation and
  validation still did not improve.

Artifacts: `board_artifacts/cal_2026-08-16_run{1,2,3,4,5}*.npz`, all kept per
CLAUDE.md. Raw calibration points (`aX`, `ay`) are in each, so any re-analysis
below can be redone without another sitting.

### Does this fork the project?

**Not yet, and it is no longer looking like Path C.** With a fresh mapping the
pipeline measures **2.73 deg** (LOO, run 4), which is Path B. What is unresolved
is how fast that mapping goes stale -- a drift question, which is the part of
the project online recalibration was designed for, not a viability question.
Record the drift number properly (see "Next, in order") before writing anything
into the fork.

---

## Stability soak 2026-08-16 — PASSED

The re-run, with the two arms genuinely concurrent. **This is the one that
counts**; the 2026-08-09 attempt below was void.

| criterion | result |
|---|---|
| both arms overlapping | **45 min**, 15:12:50 → 15:57:50 host time |
| inference arm alive | `inf=1` across **39 consecutive** 60 s samples |
| camera errors | `err=0` throughout |
| board reachable | **0** ping failures |
| SoC temperature | 59–61 °C, flat; fell to 56 °C when load ended |
| **new `crash` in `last -x reboot`** | **none** — uptime spans the window |

The inference arm ended by completing its 2700 s, not by dying. Contrast
2026-08-09, where it stopped at 656 s and three crash boots bracketed it.

`soak.done` is absent because the bench arm was stopped deliberately at 18 of 30
runs once the window closed, to free the camera for `bin/facecheck`. The bench
arm logged **0 tracebacks** across those 18 runs.

Evidence: `board_artifacts/soak_watch_2026-08-16.log`,
`board_artifacts/soak.log.2026-08-16`. See `board_artifacts/README.md`.

**What made the difference** was not the board — it was finding that
`config.toml` pointed at `/dev/video0`, which on this boot is the Qualcomm Venus
decoder rather than the C920. See "Camera device path" below.

### Backend re-verified after the camera.py change — 10/10

`bin/facecheck --no-sweep`, subject seated, at `focus_absolute = 30`:

```
score 1.000   detect 0.0 ms  landmark 46.8 ms  total 47.2 ms
iris radius 6.3 px
BACKEND VERIFIED against a real face  (10/10 geometry checks)
```

All ten geometry checks pass with the by-id device path in `config.toml`, so
symlink resolution works end to end on hardware. Focus recommendation came back
**30**, unchanged, so the MEASURED value stands.

### Camera device path — /dev/videoN is not stable

`config.toml` held `/dev/video0`. On the 2026-08-16 boot that is the **Qualcomm
Venus video decoder**; the C920 was on `/dev/video2`. It genuinely was video0 on
2026-08-08 — the codec driver and USB enumeration race for the low numbers.

This is what voided the 2026-08-09 soak, and it is a nasty failure because it is
fast and silent: every `bin/bench` died instantly, so 15 iterations "completed"
in ~20 s and wrote `soak.done = FINISHED`, indistinguishable from a pass.

Fixed: `camera.py` resolves symlinks (`os.path.realpath`) and matches
`/dev/videoN` strictly instead of scraping digits — the old code turned a by-id
name into index **4046920163030**. `config.toml` now uses the stable by-id path.
Covered by `tests/test_camera_device.py`, 5 tests, no hardware. Suite: **90**.

### `gain` tracks room brightness -- probe is a light meter

Chased because `bin/probe` began failing with `BAD gain want=0 got=109` while
the other six controls stuck, contradicting the 2026-08-08 record. Resolved by
experiment the same day:

| room | probe runs | `gain` reads | probe verdict |
|---|---|---|---|
| dim (ambient, ~16:00) | 3 | **109** every time | 1 blocking issue |
| bright | 2 | **0** | `all controls survived stream start`, **exit 0** |

The C920 raises gain on its own in low light **despite `auto_exposure` reading
`1 (Manual Mode)` and `exposure_time_absolute` holding at 156**. Not a
control-ordering bug; `warmup_frames = 8` stands. Not the camera.py change
either -- `realpath` is a no-op on a plain node and six controls share the path.

Idle, the control always accepts the write (`--set-ctrl gain=0` -> reads 0), so
it is the streaming path that raises it.

**Consequences, which matter more than the bug did:**

- `bin/probe` doubles as the **light check**. Run it before any sitting; a
  `BAD gain` is the room being too dark, not a fault.
- Every number in this file was measured at gain 0. Match that or comparisons
  are invalid.
- The "three lighting conditions" item below is now partly predicted: the dim
  arm runs at raised gain, so it measures sensor noise *plus* lighting effects
  on the landmarks. Do not attribute all of the degradation to lighting.

---

## Stability soak 2026-08-09 — DID NOT PASS (superseded)

Not an accuracy measurement, but it gates Gate 1c, so it is recorded here.
The soak's job: prove the board survives 45 min under simultaneous camera +
pipeline + all-core inference load, so a brown-out cannot corrupt the one
baseline calibration that can only ever be recorded once.

| arm | planned | achieved |
|---|---|---|
| `bench` loop ×15 | 15 runs | 15/15, `soak.done` = `FINISHED` |
| all-core inference | 2700 s | **656 s / 22000 invokes, log stops mid-stream** |

**The two arms never overlapped**, so the condition under test was never
created. `soak.log`/`soak.done` last written 03:43:29; `load.log` last written
04:13:45 after 656 s of progress, i.e. it started ~04:02:49 — 19 minutes after
the bench arm had already finished. Back-to-back arms test neither.

**The board then crash-looped.** `last -x reboot` shows boots at 04:12, 04:15
and 04:16 all ending in `crash`, bracketing `load.log`'s final write. The arm
that stresses power is the arm that died, at ~24% of planned duration.

Two cautions on reading this:

- All timestamps are the board's own clock, which is wildly wrong (it booted
  believing it was Aug 10 when the host said Aug 16). *Relative* gaps within one
  boot are still meaningful; absolute times are not.
- **Soak fps is not a bench result.** 14 of the 15 runs sat at p50 ≈ 14.9 fps —
  the no-face path, with `landmark_ms` = 0.0 — against the Gate 1b p50 of 18–25.
  Nobody was seated, by design. Do not quote these as pipeline throughput.

Re-run procedure, with the ordering and mid-run verification that were missing,
is in `RESTART.md` § "The soak test".

---

## Still open

- [x] **Gate 1b** -- done. p50 18-25 fps, p5 14.2 (bar unmeetable, see above)
- [ ] Three lighting conditions: bright, dim, backlit worst case. **Note the dim
      arm runs at raised gain** (see "gain tracks room brightness"), so record
      `gain` alongside the result or the arms are not comparable.
- [ ] **Gate 1c** -- `bin/calibrate`, p95 angular error, implied target size
- [ ] **Baseline calibration saved before any tuning** -- can only be recorded once
- [x] **Stability soak** -- PASSED 2026-08-16 (45 min, both arms overlapping,
      no reboot). The 2026-08-09 attempt was void: camera node had moved.
- [x] **`gain` want=0 got=109** -- RESOLVED 2026-08-16: it is room brightness,
      not a fault. Bright room -> gain 0, probe exits 0. Run `bin/probe` as the
      light check before every sitting.
- [ ] Cause of the unexplained reboot (uptime 25 min, no dmesg USB complaints).
      **Second incident 2026-08-08 17:13:** after the host crash the board came
      back powered (PHY negotiated) but never finished booting -- carrier
      flapped 7x in 2 min, one DHCPDISCOVER, offered .250, no DHCPACK, then
      silent. Two power-shaped incidents now; suspect the 5V/3A supply. Recovery
      procedure in RESTART.md.
      **Still recurring after the hub re-cabling of 2026-08-08 20:05** -- that
      fix is NOT confirmed. Crash-terminated boots since: 8 clustered at
      Aug 8 22:26-22:27, 3 at Aug 9 04:12-04:16 (during the soak), 3 more at
      power-on Aug 16. The board has never recorded a clean shutdown.
- [ ] Can the eMMC be imaged? The whole replication plan depends on it

## 2026-09-19 — rim exposure, and a false annulus worth knowing about

Chasing "why does the rim annulus never form", two things came out that hold
regardless of the glasses.

**Rim detection needs its own exposure.** `[camera] exposure = 156, gain = 0`
is a *gaze* setting: short integration so a saccade does not smear. For rim
pose the target is a 50 mm edge on a slowly-moving head (`detect_every_n = 5`),
and 156/0 left the face at mean 20 — the rim edges were under the noise floor.
Twelve-point sweep of the C920 EV ladder against gain, face-ROI mean:

| exposure | gain 0 | gain 96 | gain 192 |
|---|---|---|---|
| 156  |  21 |  71 | 107 |
| 312  |  43 | 112 | **150** |
| 625  |  62 | 146 | 187 |
| 1250 | 113 | 201 | 228 |

The trap is the bottom-left corner. 1250 reads as a good exposure (mean 113)
and is *worse than useless*: 1250 is 125 ms, the head cannot hold still to
pixel precision that long, and the lens that was cleanly detected at 156
disappears from the candidate list altogether. Brighter and blinder at once.
The fix is **gain, not time** — gain costs a 50 mm rim far less shot noise
than it would cost an 8 px iris. Recorded as `rim_exposure`/`rim_gain` in
`[frame_rig]`.

**The ratio gate alone will accept junk.** At 625/96 a pair fitted
`a = 122.33 / 105.20`, ratio **1.163** against the wanted 1.1364 — inside the
±6 % tolerance, a clean ACCEPT. It was background clutter: arc coverage 0.28
and 0.33, residuals 0.072 and 0.080. A real rim in the same frames sits at
cov 0.94. Ratio says "these two ellipses are concentric and correctly
proportioned", and two sloppy fits satisfy that by accident often enough to
matter, because a bad fit's radius is close to arbitrary.

Fixed: `Ellipse` now carries the `coverage`/`residual` it was fitted with, and
`ring_pair()` refuses a pair whose worse member falls below
`MIN_RING_COVERAGE`. This changes nothing on the `find_rims()` path, which
already gated candidates before grouping — it exists because `ring_pair` is
public and documented as a standalone filter, and called directly it had no
quality floor at all. Enforced only when quality is present, so synthetic
ellipses still pass. Two tests pin both halves; 149 passing.

**Not measured:** the annulus still has not formed on real hardware. The
session's captures turned out to be of ordinary rectangular prescription
glasses, not the round pair — see GLASSES.md on why a non-circular outline
cannot work. The distance ladder (update.md §4.1) is still unrun.

## 2026-09-19 — first rim pose on hardware, and two bugs that were hiding it

Paired run with the marker board held beside the face and the round orange
glasses on, so ground truth and the rim estimate come from the SAME frames.

**The board is an excellent ruler.** 79–100% detection, distance stable to
**±1.0–2.9 mm**. That is the precision the rims have to beat, and it is
measured rather than assumed. `reproj` sits at **1.27–1.47 px**, above the
1 px threshold — most likely the printed board is not at exactly 100% scale.
Measure the 100 mm ruler on the printout; a 3% scale error walks straight
into every distance.

**Bug 1: `close_px = 3` was deleting the rim.** Morphological closing was on
by default to bridge broken outlines. The two edges of a 3 mm rim are ~7 px
apart at 1920, so a 3×3 close *bridges them* — it fuses the ring into one
thick blob whose contour no longer fits an ellipse. Same scene, same frame,
only that line different:

| close_px | candidates surviving cov≥0.40 & res≤0.06 |
|---|---|
| 3 | **0** |
| 0 | 3, including the rim at res 0.044 |

It was deleting the signal it was added to rescue, and silently — the failure
presents as "the rim was not visible". Now defaults to 0. Anything above 0
forfeits annulus mode entirely.

**Bug 2: grayscale cannot see an orange rim on lit skin.** They are close to
isoluminant, so the rim-to-skin boundary barely exists in luminance. The left
lens survived only because it happened to sit against the dark eye socket; the
right lens was **never found in any frame of the session**. Taking the
per-pixel max gradient across B, G, R, a* and b* (`max_gradient()`):

| edge image | survivors | lenses found | pair test |
|---|---|---|---|
| grayscale | 2 | left only | reject |
| max_gradient | 7 | **both** | **ACCEPT** |

This is not the colour thresholding CLAUDE.md rules out, and the distinction
matters: a threshold picks a colour and a cut, so it is tuned at setup and
drifts by lunchtime. Max gradient picks no colour and has no cut — "an edge in
any channel is an edge" is equally true of all five rim colours and of a hall
whose lights change. The ellipse is still found geometrically.

**Also fixed: a square is a perfect ellipse by every gate but residual.** All
four ArUco markers were being reported as flawless rims — `fitEllipse` on a
square contour gives axis_ratio 1.00 and coverage 1.00. Only residual
separates them (markers 0.100–0.106, real rim 0.021–0.044), so `max_residual`
went 0.18 → 0.06. Relevant well beyond the board: a faire is full of screens,
keycaps and picture frames.

**First rim pose on hardware:** pair mode (no annulus) 704.6 ± 14.2 mm against
a board reading of 632.6 mm. Yield is only 5% of frames and the annulus has
still never formed, so this is a proof of life, **not** a measurement. Do not
quote it.

**Still open:** annulus 0% — the inner edge is not resolving even with
max_gradient. Pair yield 5% is far too low. `separation_mm = 71.0` is still a
PLACEHOLDER, and the pair test depends on it, so the ratio gate is currently
being judged against a guess. The single-edge fallback is useless and should
not be trusted at all — it wanders across the room (fit centre std 326 px)
and was measuring a fan and a cardboard box.

### separation_mm measured — 61.5 mm, and the estimate was wrong

The one number update.md flagged as MISSING. Measured across the two **inner**
circles, twice, so the reading checks itself:

| reading | value | relation |
|---|---|---|
| closest inside points | 18 mm | sep − inner_d |
| farthest inside points | 105 mm | sep + inner_d |

→ inner_d = (105 − 18)/2 = **43.5 mm**, sep = **61.5 mm from both readings**.
The implied 43.5 also agrees with the separately calipered inner diameter of
44.0 to 0.5 mm, so three measurements are mutually consistent.

**61.5 is outside the 67–75 mm predicted from the 137 mm frame width** — the
prediction was 15.4% high. The 71.0 placeholder made the pair test hunt for a
separation/radius of 2.84 when the truth is 2.46, so it was scoring every
genuine rim pair as a poor match and could prefer a wrong one. Distance comes
from the radius alone and was never affected.

Sanity: outer span 61.5 + 50.0 = 111.5 mm leaves 12.8 mm per end piece of a
137 mm frame, typical for a chunky costume frame; 71.0 would have left 8 mm.

Still `measured_n = 1`. The batch **spread over ten pairs** is the number that
actually limits accuracy (±0.5 mm → 6.1 mm at 600 mm) and is still unmeasured.

### Rim distance WORKS — 2026-09-19, measured against the marker board

Paired frames, board held beside the face as ground truth, round orange
glasses worn, 1920, exposure 312 / gain 192, at ~390 mm.

| | value |
|---|---|
| board detection | 100%, steady to **±1.4 mm** |
| annulus formed | **100%** (was 0% all session) |
| rim pose produced | 85–92% of frames |
| outer-edge lock | measured/expected radius **p50 = 1.000** |
| paired error (rim − board) | **p50 −0.4 mm**, IQR 14.9 mm |
| with a 5-frame median | p50 −1.8 mm, **std 6.9 mm** |

The bias is essentially zero and the outer edge is being identified, not
guessed — a lock on the inner edge would read 1.136 and a 13.6% scale error.
The 5-frame median is free rather than a fudge: head pose is only sampled
every `detect_every_n = 5` frames anyway.

**Report this as percentiles, and here is why it matters.** Mean ± std says
376.8 ± 37.7 mm and reads like a broken estimator. The sorted radii say
otherwise:

```
81 82 83 83 83 83 84 84 84 84 84 84 84 84 84 85 85 ... 89 89 90 107
p5 83.1   p25 84.5   p50 86.0   p75 88.2   p95 88.9
```

The core is tight to about ±1.2% with roughly 4–8% gross outliers, and the
std is almost entirely those outliers. CLAUDE.md's convention caught a wrong
conclusion here — the mean said "tune the detector", the percentiles said
"reject outliers".

**Independent confirmation of `separation_mm = 61.5`:** distance computed from
the centre separation alone gives 388.1 mm against the board's 390.4 — a
2.3 mm bias, without using the radius at all.

**What made it work,** in order of size. None of these was a tuning change:

1. `close_px = 3` → 0. Closing bridged the ~7–10 px rim gap and destroyed the
   ring it was meant to rescue.
2. `max_gradient()` instead of luminance. An orange rim on lit skin is nearly
   isoluminant; grayscale never found the right lens in any frame.
3. `separation_mm` 71.0 → 61.5 measured. The pair gate was aimed at 2.84 when
   the truth is 2.46.
4. Hough centres instead of `findContours`. The rim outline is present at the
   right size but arrives broken and fused with brow and hair edges, so no
   connected component is ever a ring. Voting does not care about
   connectivity.
5. `ring_radii()` — radial profile, median over 180 angles. This is what
   finally produced an annulus: a gap costs a few angles and the median does
   not move.

**Still open:** the 4–8% outlier frames are not characterised — something else
in the scene occasionally wins the Hough vote. `radius_mm = 25.0` may be ~2%
off (Z from radius sat 13.6 mm low while Z from separation sat 2.3 mm low in
the same frames). No distance ladder yet: this is one distance, ~390 mm, not
the 450–700 mm sweep update.md asks for. Yaw is noisy (±12–16°) and untested
against the board's yaw.

## 2026-09-20 — DISTANCE LADDER (update.md §4.1), glasses vs marker board

Board rested against the **temple arm** so its plane sits level with the
lenses; rim and board measured on the same frames, ~50 frames per rung, 1920,
exposure 312 / gain 192.

| target | board (truth) | rim p50 | error p50 | error IQR | detection |
|---|---|---|---|---|---|
| 450 | 441.3 ± 1.7 | 417.2 | −24.4 | 14.7 | 77% |
| 500 | 492.1 ± 2.9 | 467.7 | −24.6 | 30.4 | 86% |
| 550 | 545.4 ± 4.2 | 528.9 | **−17.2** | **3.7** | **100%** |
| 600 | 599.7 ± 5.3 | 574.3 | −25.1 | 12.1 | 88% |
| 650 | 644.9 ± 2.1 | 641.9 | −3.2 | 5.4 | 89% |
| 700 | 694.2 ± 2.0 | 673.5 | −19.8 | 12.2 | 57% |

**The bias is a fixed plane offset, not a radius error.** This is the question
the ladder exists to answer, and the two hypotheses separate cleanly because
one is constant and the other is proportional:

| model | residual |
|---|---|
| constant offset | **7.7 mm rms** |
| proportional (radius wrong) | 9.6 mm rms |

corr(distance, error) = +0.50 — no clean distance trend. So `radius_mm = 25.0`
is **not** measurably wrong, and the −22.1 mm median is the card sitting behind
the lens plane: the temple arm runs backward from the frame front, so a card
flat against it is ~2 cm behind the lenses. That subtracts out. The earlier
suspicion that `radius_mm` was ~2% high is **not supported** — it came from a
single distance, where a plane offset and a scale error are indistinguishable.

**After subtracting the median bias**, per-rung residual is 8.2 mm rms, max
18.9 mm — and that spread is board *repositioning* between rungs, not the
detector: 650 mm is the outlier at +18.9 and it is also the rung with the best
board stability (±2.1), i.e. a well-held card in a slightly different place.

**Detector precision is the within-rung IQR:** median **12.1 mm**, best
**3.7 mm at 550**, worst 30.4 mm at 500. The 550 rung — 100% detection,
3.7 mm IQR — shows what this method can do when the pose is square and the
card is steady. update.md predicted 2–6 mm for the rim annulus; that is met at
550 and 650 and missed elsewhere.

**Detection falls off at 700 mm (57%)** and the reason is geometric, not
tuning: the annulus gap is 9.1 px at 450 but only **5.9 px at 700**, against a
`MIN_RING_SEPARATION_PX` floor of 4.0. The two rim edges are running out of
pixels. corr(distance, detection) = −0.36. **700 mm is near the working limit
of this rig at 1920**, and going further needs a bigger rim or more pixels,
not a better algorithm.

**Comparison the ladder was built to make:** marker board ±1.7–5.3 mm,
rim annulus 3.7–30.4 mm IQR. The board remains roughly 3× better, as
simulation predicted (~1 mm vs 2–6 mm). The rims are good enough to use and
not good enough to replace the board as the ruler.

**Not done:** the bare-face-mesh column of update.md's table. Backlit and dim
lighting conditions (§4.2) — everything here is one room, lamp-lit. Pose
agreement (§4.3): yaw was noisy at ±12–16° earlier and has still never been
compared against the board's yaw frame by frame.

## 2026-09-20 — YAW: the rims do NOT measure it. Negative result, with a reason.

`bin/yawcheck`, board flat on the forehead so it rotates with the head, 41
paired samples, board yaw −13° to +41°, at ~570 mm.

| quantity | value |
|---|---|
| **gain** (slope of rim yaw vs board yaw) | **0.198** |
| correlation | **0.138** |
| raw error | rms 22.9°, p95 \|e\| 36.5° |
| residual after fitting gain+offset | rms 19.1° |

A gain of 0.198 with a correlation of 0.138 is not a miscalibration — it is
**no signal**. The rim yaw estimate is essentially uncorrelated with real head
rotation. Distance from these same frames is good to single millimetres; yaw
from them is noise.

**Why, quantitatively.** Yaw comes from the depth difference between the rims
(trap c), `sin(yaw) = −(z_r − z_l)/S`, and depth comes from radius, so yaw is
read as a *difference of two radii*. That difference is tiny:

| Z | rim a | da/dz px/mm | Δa at 20° yaw | Δa at 10° |
|---|---|---|---|---|
| 400 | 85.4 | 0.213 | 4.49 px | 2.28 px |
| 550 | 62.1 | 0.113 | 2.37 px | 1.21 px |
| 700 | 48.8 | 0.070 | 1.47 px | 0.74 px |

MEASURED fit noise on a squared-up subject at ~570 mm, where the true
difference is ~0: the two rims fitted **58.5 and 54.3 px — 4.2 px apart**.

So at 570 mm a 20° yaw separates the radii by 2.2 px while the noise is
4.2 px. **Signal-to-noise 0.53 — the signal is below the noise.** For ±5° yaw
the radius pair would have to be good to 0.56 px, about **7× better** than we
achieve. This is not a tuning problem and no filter recovers it.

**This does not contradict trap (c), it adds to it.** The docs reject
eccentricity-derived yaw because it carries a couple of degrees of systematic
perspective bias. True — but the depth-difference path it recommends is
*noise*-limited at this rig's scale, and 2° of bias is far better than 19° of
noise. Worth testing: yaw from the mean axis ratio of the two rims, which are
coplanar and so should agree, averaging down the per-rim noise. Not yet
measured; the axis ratios were not recorded in this run.

**Consequences for the design.** The rims give **distance**, not orientation.
Anything wanting head *rotation* needs the marker board, the face mesh, or an
accepted 2° bias from eccentricity. The gaze mapping's `t_z` feature is fed by
distance and is unaffected.

**Caveats:** 41 samples, 7 of 12 coverage bins, one subject, one distance, one
room. The board range was asymmetric (−13° to +41°), so the fit is not
well balanced about centre. This is enough to rule the method out at this
scale, not enough to characterise it.

## 2026-09-20 — lighting conditions (update.md §4.2), partial

`bin/lighttest`, ~31–32 frames per condition, ~550–670 mm, same subject and
glasses throughout.

| condition | face | halo | halo/face | board | hough | annulus | pose | dist IQR |
|---|---|---|---|---|---|---|---|---|
| frontlit | 128.7 | – | – | 74% | 100% | 100% | 52% | 42.0 |
| backlit (lamp behind, front lights on) | 152.2 | – | – | 100% | 100% | 100% | 72% | 30.0 |
| backlit2 (lamp aimed at camera) | 122.7 | 112.6 | 0.92 | 0% | 100% | 100% | 48% | 154.9 |
| **backlit3 (front lights OFF)** | 91.2 | 110.4 | **1.21** | 100% | 100% | 100% | **84%** | 44.6 |

**Mild backlighting does not hurt — it helped.** At halo/face 1.21, which is
the most backlit condition achieved, rim pose reached **84%**, the best of any
condition measured, with the annulus at 100% throughout. The predicted failure
mode — backlighting kills the inner edge first and collapses the annulus — did
**not** appear at this level. The annulus never dropped below 100% in any
condition.

**Measure the halo, not the frame.** A whole-frame background average dilutes
a bright source behind the head into a lot of dark room: placing a lamp behind
the subject moved whole-frame bg/face from 0.82 to 0.83, i.e. reported no
change while the scene was plainly different. The ring immediately around the
head is what silhouettes a face, and it read 1.21 where the frame read 1.09.

**Face brightness is not the useful control.** Across these runs face mean
spanned 91–152 and pose ranged 48–84% with no ordering between them: the
*worst* pose (48%) came with a well-lit face of 122.7, and the *best* (84%)
with the darkest face at 91.2. Detection tracked seating distance and pair
stability, not illumination. `bin/aim`'s brightness thresholds are therefore a
guide to whether anything is visible at all, not a predictor of detection.

**NOT YET the real test.** halo/face 1.21 is a lamp on a wall at 00:40. A
window in daylight is far harsher — a faire hall with glazing behind the
visitor could easily exceed 3. **Repeat this in the morning with a window
behind the subject**; the sign of the effect is established, the magnitude at
the worst case is not. Also uncontrolled here: distance varied 515–669 mm
between conditions, and the ladder showed distance alone moves pose by tens of
points, so these percentages carry that confound. The backlit2 row is not
usable — the board was out of frame and distance IQR blew out to 154.9 mm.

## 2026-09-21 — Gate 1c bare-faced (update.md §4.4). CONFOUNDED by head drift.

`bin/calibrate --val-points 26`, shuffled (seed 863568333), no glasses, no rig.

| | value |
|---|---|
| calibration points | 9 |
| training error | 2.65° mean, 5.79° p95 *(self-flattery)* |
| **validation, 26 held-out points** | **6.61° mean, 13.60° p95**, worst 14.50° |
| in pixels | **333 px mean, 693 px p95** |
| implied minimum target | 244 mm → a 1×1 grid, i.e. too coarse to use |

**Do not quote the 6.61° as accuracy.** The drift check built into the tool
fired: head **pitch moved 16.1 sd** between the calibration and validation
blocks, with `t_x` at 2.2 sd and `t_y` at 1.4 sd. The gap was only 5 s, so
this is a genuine head movement, not slow drift — the validation grid was
scored against a head the fit never saw. The tool's own verdict: *read the
validation error as DRIFT, not accuracy.*

**The one clean comparison is in pixels**, because it does not depend on the
viewing-distance convention: **333 px here against run 7's 477 px.** Both
convert the same underlying pixel error, so the pipeline really has improved
since run 7 — that part is not confounded by drift *or* by distance.

**`viewing_distance_mm` corrected 584 → 504.** 584 was a stale 23-inch reading
from a different seating position; 504 was measured later and the subject
independently reported "around 500 mm" at this sitting — two estimates
agreeing to 1%. **Every angular error scales directly with this, so 584 was
inflating every degree figure by 16%.** Consequence for the record: run 7's
8.22°/5.12° were computed at 584. *If* that sitting was also at 504 — not
confirmed — its true figures were **9.52° / 5.93°**. Not retroactively
rewritten, but the earlier numbers cannot be compared to this one in degrees
without knowing each sitting's distance. **Measure the distance every sitting.**

**Lighting was poor and is a candidate explanation for part of the error.**
Face detection was 100% (30/30), but brightness on the detected face box was
**40.3** against the 128.7 measured earlier the same evening. A dim iris is a
noisy iris. Recorded here so the run is interpretable rather than discarded.

**Repeat this run** with (a) the head held still between blocks — the two grids
are minutes apart and nothing restrains the head, and (b) the lamp back to the
128.7 arrangement. Until then Gate 1c bare-faced is **not measured**.

## 2026-09-21 — GATE 1c BARE-FACED: 3.27°. This is Path B, not Path C.

`bin/calibrate --val-points 26`, bare-faced, shuffled, 25 calibration points,
ridge chosen by blocked 5-fold CV **from training data only**.

| | value |
|---|---|
| **validation, 26 held-out points** | **3.27° mean, 5.56° p95** |
| in pixels | 164 px mean, 279 px p95 |
| worst single point | 15.73° |
| drift between blocks | max 1.6 sd — clean |
| implied minimum target | 98 mm → 3×1 grid |

Against run 7's 8.22°, and in pixels — which is immune to the
viewing-distance question — **477 px → 164 px, a 2.9× improvement.**

**`PLAN.md` § the Sunday-night fork:** Path B is fps ≥ 15 and error 2.0–3.5°.
fps p50 is 18–25. Error is 3.27°. **That is Path B: build the AAC grid, add
zoom-to-refine for cursor work.** The project had been on Path C ("do not
build on this, diagnose first") since run 7. It is not on Path C any more,
and no hardware changed — the camera, the lens and the backend are the same.

### Two bugs in the fitting, and neither was visible in the training error

**1. `points = 9` was never enough.** The mapping has 66 parameters
(degree-2 poly on 10 features), so a 9-point grid trains on 8 of them. Same
subject, same session, same 26 validation targets:

| calibration points | validation |
|---|---|
| 9 | 8.4–8.5° |
| 25 | **2.34°** |

Now `points = 25` in `config.toml`. It costs ~112 s to collect against ~37 s.

**2. `ridge = "auto"` used leave-one-out CV, which under-regularises here.**
Calibration points are collected over ~112 s, so consecutive samples are
*temporally correlated* — same head pose, same blink state. LOO leaves a
held-out point's own time-neighbours in the training set, so the point is
predicted partly from itself: CV then reports that barely-penalised fits
generalise, and picks a penalty orders of magnitude too small. Measured on one
real 25-point run, validated on 26 separate targets:

| fold structure | ridge chosen | validation |
|---|---|---|
| leave-one-out | 0.215 | 11.97° |
| **blocked 5-fold** | 46.4 | **2.53°** |
| oracle (best possible) | 21.5 | 2.22° |

Same data, same grid, same solver — only the fold structure differs. Blocked
folds land within 0.3° of the oracle. Blocking is the standard remedy for
correlated samples and was chosen for that reason, not fitted to these runs.

**Both failures were invisible from inside.** The overfitted runs reported
training errors of **0.16°** and **0.40°** — the more badly they overfitted,
the better they looked. `auto` picked 100, 10, 1 and 0.1 across four runs of
the same subject at the same task.

### Also corrected: `viewing_distance_mm` 584 → 504

584 was a stale 23-inch reading from a different seating position. Every
angular error scales directly with it, so **584 inflated every degree figure
by 16%**. Degrees from different sittings cannot be compared without each
one's distance — **measure it every sitting**. Pixels are the safe currency.

### Caveats — do not over-read this

One run, one subject, one lighting condition (face-box brightness 55.4, below
the 128.7 measured earlier the same evening). The **worst single point was
15.73°** against a p95 of 5.56°, so there is a tail the mean hides. 3.27° sits
close to the 3.5° Path B/C boundary. **Repeat it** before committing seven
weeks of schedule to it — and repeat it in good light, since a dim iris is a
noisy iris and this run was dim.

## 2026-09-21 — the 66-parameter model was never earning its parameters

Scored on the same 26 held-out targets as the Gate 1c runs above, refitting
the stored feature vectors — no new sitting.

| calibration points | LinearMapper (7 par) | GazeMapper poly2 (66 par) |
|---|---|---|
| 9 | **3.49°** | 8.37° |
| 25 | **3.01°** | 3.27° |

**Linear wins at every point count tried, including 25 where poly2 was
supposed to have enough data.** `LinearMapper` uses six features — both iris
x/y, yaw, pitch — and a bias, against poly2's degree-2 expansion of all ten.
Dropping `roll`, `t_x`, `t_y`, `t_z` and every quadratic term costs nothing
measurable and buys a model that cannot overfit a short grid.

This reframes the Gate 1c result above. The headline 3.27° came from 25 points
plus the blocked-CV fix; **3.49° was available all along from 9 points and a
linear fit**, at a third of the sitting time. The blocked-CV work was still
necessary — it is what makes poly2 safe at 25 points — but the larger lesson
is that poly2 should probably not be the default at all.

**Not yet done:** poly2 is still the spike's default above 16 points, and
`config.toml` still points at it. Changing that is a one-line decision but it
deserves its own fresh run rather than a refit, since every number here comes
from data collected for a different model. The bunny game has already been
switched to linear for any grid it will present (see its `GAZE.md`).

**Caveat:** one subject, one session, two grids. Linear's margin at 25 points
(3.01 vs 3.27) is inside the run-to-run spread seen earlier tonight; its
margin at 9 points (3.49 vs 8.37) is not.

## 2026-09-21 — the PITCH feature sat on the ±π wrapping singularity

Reported from the board: "it was tracking very well, it has problems if you
tilt your head up or down after calibration."

**Measured cause.** `head_pose()` extracted Euler angles straight from
solvePnP's rotation matrix. The canonical face model faces *away* from the
camera, so a head looking at the lens is ~180° rotated, `R[2,2] ≈ −1`, and
`atan2(R[2,1], R[2,2])` lands on the wrap. Real 25-point calibration data:

```
-3.12 -3.12 ... -3.09  |  -1.25 -1.05 +0.82 +1.46 +2.47  |  +2.89 ... +3.13
      14 near −π              5 scattered                     6 near +π
```

**Standard deviation 2.69 rad — 154°** — for a seated head that barely moved.
A single sign flip is a jump of 2π in a feature the linear mapping multiplies
by a coefficient; measured, that moved the cursor **230 px**.

**Fixed** by taking Euler angles *relative* to the nominal facing-the-camera
rotation (`_NOMINAL_T`), so they sit near zero, far from any singularity.
Verified against synthetic poses: −20° → −20.00, 0 → 0.00, +20° → +20.00, with
yaw and roll at zero. Four regression tests, including one that sweeps through
level and asserts no discontinuity — the failure was never a wrong value, it
was a **step** between two nearly identical poses.

**But the wrap was NOT why head tilt breaks tracking**, and it is worth being
clear about that rather than claiming a fix we did not make. Measured on the
real mapping, a 10° tilt moves the cursor only **6 px**. The coefficient on
pitch is tiny.

**The actual mechanism is that nothing compensates.** Tilt the head up while
still looking at the same point and the eyes counter-rotate down: the iris
moves ~3.8 px in the image, and at the measured **139 screen-px per iris-px**
gain that is **~525 px ≈ 10° of gaze error**. The head-pose features exist to
absorb exactly this, and they cannot, because a 9-point calibration is
collected at one head pose and has almost no pose variation to learn the
coefficient from.

**So the pitch fix is necessary but not sufficient.** What follows from it:

| candidate | note |
|---|---|
| vary head pose *during* calibration | gives the pose coefficients something real to fit; costs sitting time |
| detect tilt and prompt a re-calibration | cheap, and the flags for it already exist |
| drop pose features entirely, require a still head | measured: iris-only is 4.65° vs 3.49° at 9 points, so pose IS earning its place at the same pose |

Untested: whether a calibration that deliberately samples two or three head
pitches recovers the compensation. That is the experiment the faire data may
answer for free, since visitors will not hold still.

## 2026-09-22 — first real gaze-study data (bunny game, fire-on-target)

40 throws, 37 valid, one adult subject, calibrated at 529 mm, 9-point grid.

| | value |
|---|---|
| error | p50 5.40°, p95 8.37° — **TRUNCATED, not accuracy** |
| throws outside the 90 px capture radius | **0 of 37** |
| **time to acquire** | p25 5.5 s, **p50 11.3 s**, p75 16.8 s, p95 26.1 s |
| fastest / slowest | 0.3 s / 28.0 s |
| calibration bias | 10.2, −0.8 px (≈0.8°) |
| seating drift during the round | 70 mm |

**The error figures are unusable and the run proves it.** Fire-on-target only
throws once the gaze is within 90 px, and **zero of 37 throws exceeded that** —
p95 of 8.37° sits against the 9° ceiling. The distribution was cut, not
measured. Use `BFF_STUDY_FIRE=dwell` when accuracy is the question.

**The usable number is 11.3 s to acquire — about 5 selections per minute**,
with an enormous spread (0.3–28 s).

**That is pessimistic for the actual application, by a lot.** A bunny is a
~64 px target that MOVES. A talker AAC cell is 640 × 540 px and stationary.
This measures gaze selection under close to the hardest conditions available,
so it is a floor rather than a ceiling — the same number on the 3×2 board is
the one that would decide the design.

**What the 11.3 s is made of**, and which lever is worth pulling:

| lever | effect | cost |
|---|---|---|
| bigger capture radius | fires sooner | truncates the error further |
| shorter hold (0.25 s) | fires sooner | a saccade crossing a bunny triggers it |
| better accuracy | fewer excursions outside the window | the real fix, and the hard one |
| **stationary, larger targets** | **the window stops moving** | none — it is what the product is |

**Calibration quality moves the result more than expected.** The previous
round's bias was 32.8, −23.3 px and it scored p50 8.99°; this round's was
10.2, −0.8 px at p50 5.40°. Same pipeline, same subject, 20 minutes apart.
Whatever the faire protocol ends up being, it needs to detect a bad
calibration and redo it rather than collecting a session on top of one.

**Also validated this run:** the bad-distance guard caught 0 failed solves
(the previous round had one at −509.5 mm), the self-check printed `gaze OK`
before collection, and 93% of throws passed the automatic distraction flags
with no operator input.

## 2026-09-23 — the red/IR lamp: +96% iris contrast, and gain is a saturated meter

The lamp is **16 red LEDs plus one 850 nm IR LED** — a red illuminator, not an
IR array. That matters: red at ~625 nm passes the C920's IR-cut filter freely,
so the filter concern raised for a pure-IR lamp mostly does not apply.

Four conditions, 8 s each, same subject and seat, `bin/irprobe`:

| condition | face mean | **iris contrast** | R/G | detection |
|---|---|---|---|---|
| dark, no lamp | 10.0 | 1.71 | 0.36 | 100% |
| room lights only | 34.2 | 7.70 | 0.42 | 100% |
| dark + lamp | 34.9 | 10.53 | 1.23 | 100% |
| **room + lamp** | **56.3** | **15.11** | 1.09 | 100% |

**The lamp nearly doubles iris contrast on top of room lighting** (7.70 →
15.11, +96%), and it is not merely adding photons: at essentially matched face
brightness (34.9 vs 34.2) it still beats room light by **+37%** on contrast.
That is the mechanism red light should have — it scatters less in the iris,
flattening texture and sharpening the pupil boundary.

**Detection was 100% in every condition, including face mean 10.0.** Face
detection is not the discriminator at this range and should not be used as one.

### Gain is a light meter only BELOW its ceiling

`gain` read **109 in all four conditions** while face brightness varied 5.6×
and iris contrast 8.8×. It is pinned at its maximum and has no headroom to
show a difference. Reading "gain unchanged" as "the lamp did nothing" would
have discarded a lamp that was plainly working — `bin/irprobe` now detects
saturation and says so rather than offering that interpretation.

This sits beside the earlier finding that face brightness does not predict rim
detection. Both are cases of a convenient proxy being trusted past its range.

### What this does NOT establish

**Iris contrast is a proxy, not the result.** Whether a 96% contrast gain
improves *gaze accuracy* is unmeasured. The obvious test — `bin/fixate` with
the lamp on and off — **cannot currently resolve it**: two runs of the SAME
condition gave 153.8 px and 276.9 px, an 80% spread. Any single on-vs-off
comparison would report a confident number in whichever direction the noise
fell.

To measure the accuracy effect, the fixation protocol needs fixing first:
several short fixations rather than one 15 s hold (lag-1 autocorrelation of
0.6–0.74 suggests the subject's own drift dominates a long hold), alternating
conditions, and enough repeats to compare distributions rather than points.

**Also: the room was dim throughout.** Room lights alone put the face at 34.2
where the same condition measured 128.7 four days earlier, and gain was
saturated in all four readings. Every comparison here is between dim
conditions, which is where a lamp has the most room to help. Whether it still
helps in a well-lit hall is not answered by this data.

**Unrelated confound found and fixed:** the CPU governor was `schedutil`, not
`performance`, which had the pipeline at 7.8 Hz against a camera capable of
19.4. Any timing measured before that fix is void.

## 2026-09-23 — the fixation protocol was measuring the subject, not the tracker

`bin/fixate` showed one dot for 15 s and reported the scatter about its single
mean. Two runs of the SAME condition then gave **153.8 px and 276.9 px** — an
80% spread — which made any A/B meaningless.

**The fault was in the statistic.** Lag-1 autocorrelation ran 0.60–0.74, so
the signal was dominated by something slow. Nobody holds a fixation for 15 s:
the eyes creep, the head settles, the chair moves. All of it landed in
"tracker noise". Demonstrated on synthetic data with a known answer:

| | value |
|---|---|
| true jitter | 42 px |
| old whole-run statistic | **169 px** (4× inflated by drift) |
| new per-fixation statistic | **41 px** |

### What the rebuilt protocol does

- **~20 short fixations, not one long hold.** ~1.5 s each, and scatter is
  measured about *that fixation's own mean*, so drift between fixations
  cannot contaminate it.
- **Positions vary** across a grid. A single centre dot measures the tracker
  where it performs best.
- **Settle time is discarded** — the first 0.6 s after a dot moves is a
  saccade and its overshoot, not a fixation.
- **The run is a distribution**, and a bootstrap gives the median a
  confidence interval.
- **The A/B bootstraps the DIFFERENCE**, not two separate CIs. Judging
  overlap between two intervals by eye is a different and weaker test, and it
  is the one people do without noticing.

Verified to both directions on synthetic data: 60 px vs 85 px resolves
(CI [−39.9, −22.8]), and two draws from the same distribution do **not**
(CI [−22.3, +11.8]) — it declines to claim a difference that is only noise.

It also separates two things the old version conflated:

| statistic | what it measures | what should improve it |
|---|---|---|
| per-fixation scatter | steadiness | illumination, iris contrast |
| offset from the dot | accuracy | calibration quality |

**Still required by the design, not optional:** run each condition at least
twice, alternating. One run per condition cannot distinguish a lamp's effect
from the subject getting tired over the session, and the tool now says so when
it sees a single run.

## 2026-09-23 — the red lamp cuts gaze scatter 3.2×. Four runs, alternating.

Rebuilt protocol, four runs in the order on / off / on / off so that a drift
in the subject across the session cannot be mistaken for an effect of the lamp.

| condition | runs (px) | pooled median | 95% CI |
|---|---|---|---|
| **lamp on** | 83.4, 79.3 | **82.5 px (1.65°)** | [69.9, 99.4] |
| lamp off | 170.6, 317.9 | 267.5 px (5.35°) | [191.4, 322.4] |
| **difference** | | **+183.7 px** | **[+105.0, +242.8]** |

The interval excludes zero by a wide margin. **The lamp reduces per-fixation
scatter by about 3.2×**, from 5.35° to 1.65°.

**The alternating order is what makes this trustworthy.** Run 3 (lamp on,
later in the session) came back at 79.3 px against run 1's 83.4 — so the
effect tracks the lamp, not elapsed time. A single on/off pair would have
produced a confident number that fatigue could equally explain.

**A second finding, in the spread rather than the median.** The two `lamp_on`
runs differ by 5%; the two `lamp_off` runs differ by **86%** (170.6 vs 317.9).
Without the lamp the tracker is not merely worse, it is *unpredictable* — and
for a public demo that is the more damaging property.

### What is NOT established: the accuracy effect

Offset-from-target, which is accuracy rather than steadiness:

| condition | offsets (px) |
|---|---|
| lamp on | 235.8, 303.0 |
| lamp off | 551.4, 297.0 |

**The ranges overlap and the effect is not resolved.** One `lamp_off` run was
the worst of the four and one was mid-pack. Accuracy is dominated by
calibration quality, which varies more between sittings than the lamp varies
it — consistent with 2026-09-22, where two calibrations twenty minutes apart
scored 8.99° and 5.40°.

So the honest claim is narrow: **the lamp makes the gaze point steadier, and
the accuracy benefit is unproven.** Steadiness is what a dwell-selection
interface consumes, so this is the useful half.

**Caveats:** one subject, one room, one evening, all four runs at a face
brightness well below the 128.7 seen earlier in the week. The pipeline ran at
7.2 Hz throughout against 18–25 documented, so each 1.5 s fixation yielded
only ~11 samples; both conditions share that handicap, but it makes every
per-fixation scatter noisier than it needs to be and is worth chasing.

## 2026-09-23 — the lamp effect reproduces in the game, on a different instrument

Same game, same subject, consecutive evenings. Not a controlled A/B — the
sessions differ in calibration, day and room state — but it is an independent
measurement of the same claim.

| | Tue 09-22, no lamp | Wed 09-23, LAMP ON | change |
|---|---|---|---|
| valid throws | 37 / 40 (93%) | 38 / 39 (97%) | |
| **fixation scatter p50** | 26.7 px | **15.0 px** | **−44%** |
| **time to acquire p50** | 11.3 s | **8.7 s** | **−23%** |
| selections per minute | 5.3 | **6.9** | +30% |
| error p50 (truncated) | 5.40° | 5.23° | unchanged |

**Two independent instruments now agree.** The controlled four-run A/B on
`bin/fixate` measured scatter falling 3.2× with the lamp; the game — different
code, different task, different night — shows it falling 44% and acquisition
speeding up 23%. Agreement across instruments is worth more than either
result alone, and neither was tuned to produce the other.

The truncated error being unchanged is expected rather than disappointing:
fire-on-target caps error by construction, so it cannot move.

**6.9 selections per minute is still the number to beat**, and it is measured
on a ~64 px target that moves. The AAC cell it is meant to inform is
640×540 px and stationary.
