# UNO Q gaze spike — portable digest

Self-contained context for a conversation that cannot see this repo (claude.ai
project knowledge, a fresh chat, a collaborator). Everything here is
**measured on hardware** unless marked otherwise. The working docs — CLAUDE.md,
RESULTS.md, RESTART.md, GLASSES.md, PLAN.md — stay in the repo; this is the
subset that travels.

Last updated **2026-09-21**.

## The project in five lines

Eye tracking bolted onto a sip-n-puff assistive device. Arduino UNO Q 4GB
(QRB2210, 4× Cortex-A53, **no NPU** — inference is CPU-bound), Logitech C920x,
Debian. Deadline **30 Sep 2026**, DigiKey/Arduino Dream Lab contest. A separate
CircuitPython board does breath sensing and **stays the USB HID endpoint** —
the UNO Q is a sensor that streams gaze over UART, so the tracker is a bolt-on
for people who already built the sip-n-puff rather than a rewrite.

## Where it stands

**Gate 1c bare-faced: 3.27° mean / 5.56° p95** (26 held-out targets). Against
`PLAN.md`'s fork — Path B is fps ≥ 15 and 2.0–3.5° — that is **Path B: build
the AAC grid, add zoom-to-refine.** It had been Path C ("do not build, diagnose
first") and **no hardware changed**; the gain came entirely from fixing the
fit. fps p50 18–25.

Caveats that matter: one subject, one run, dim light, and the worst single
point was 15.73° against a p95 of 5.56° — there is a tail the mean hides.
3.27° sits close to the 3.5° boundary. Repeat before committing schedule.

## The measured facts, in order of how much they cost to learn

**The 7-parameter linear model beats the 66-parameter degree-2 polynomial at
every point count tested.** Six features — both iris x/y, yaw, pitch — plus a
bias. Scored on 26 held-out targets:

| cal points | linear (7 par) | poly2 (66 par) |
|---|---|---|
| 9 | **3.49°** | 8.37° |
| 25 | **3.01°** | 3.27° |

Dropping roll, t_x, t_y, t_z and every quadratic term costs nothing
measurable. 9 points + linear is within half a degree of a 25-point fit at a
third of the sitting — which is the whole argument for a short grid in a
queue.

**Never judge a calibration by its training error.** The badly overfitted runs
reported training errors of **0.16°** and **0.40°**. The worse they
overfitted, the better they looked.

**Leave-one-out CV under-regularises temporally correlated samples.**
Calibration points collected over ~112 s share a head pose and blink state, so
LOO leaves a held-out point's own time-neighbours in training and it is
predicted partly from itself. Measured on one real run: LOO chose ridge 0.215
→ 11.97°; **blocked 5-fold** chose 46.4 → **2.53°**; oracle 2.22°. Same data,
same grid, same solver. Folds must be **contiguous in collection order** —
strided folds reproduce the failure while looking like k-fold.

**Angular error is meaningless without the viewing distance, and it must be
re-measured every sitting.** A stale 584 mm (should have been 504) inflated
every degree figure by 16% for months. **Prefer pixels when comparing across
sittings.**

**MediaPipe cannot execute on this board.** Its aarch64 wheel uses ARMv8.1 LSE
atomics; the QRB2210 is ARMv8.0 and dies with SIGILL. `import mediapipe`
*succeeds* — the .so loads lazily — so never test availability by importing;
smoke-test in a subprocess, because SIGILL cannot be caught. LiteRT is the
only backend.

**The C920 resets UVC controls at `VIDIOC_STREAMON`, silently.** Open, discard
warmup frames, *then* apply controls, then read them back. It also quantises
exposure to EV stops while streaming (39, 78, 156, 312, 625, 1250) and floors
anything else to the stop below, invisibly.

**720p beats 1080p here** (15.0 → 23.2 fps) and `input_size` should equal the
capture width — both models have fixed input sizes (128 detector, 256
landmark), so downscaling first buys no speed and only discards detail.
**3 threads, not 4**: four starved the MJPEG decode in the capture thread.

## The glasses-rim fiducial: distance yes, orientation no

Round lensless party glasses; the circular rims **are** the fiducial. A circle
projects to an exact ellipse and no other outline does, so every departure
from circular is pose information.

**Distance works.** Against a printed ArUco board in the same frames: 100%
detection and **3.7 mm error IQR at 550 mm**, 12.1 mm median across a
450–700 mm ladder. Bias is a board plane offset, not a radius error — six
rungs separate constant (7.7 mm rms) from proportional (9.6 mm rms).

**700 mm is the working limit**, for a geometric reason: the rim annulus gap
is 9.1 px at 450 mm and 5.9 px at 700 against a 4.0 px floor; detection falls
to 57%. **Seat people at 500–650.**

**Yaw does not work and cannot be tuned into working.** Gain 0.198,
correlation 0.138, rms 22.9° — no signal, from frames whose distance is good
to millimetres. Yaw is read as a *difference of two radii*: at 570 mm a 20°
turn moves them apart by **2.2 px** while measured fit noise is **4.2 px**.
SNR 0.53. ±5° would need 0.56 px, ~7× better than achieved.

Note this contradicted a synthetic model that reported yaw good to 0.435° —
which assumed **0.5 px** of fit noise against a real 4.2 px. The geometry was
right; the noise assumption was optimistic by an order of magnitude.

**So the rims give distance, not orientation**, and they add nothing to a
calibrated gaze mapping — which does not read `t_z` at all.

### Four silent detection bugs, each of which presented as "the rim isn't visible"

1. **Morphological closing destroyed the ring it was meant to rescue.** A 3×3
   close bridges the ~7–10 px rim gap. `close_px=3` → 0 surviving candidates;
   `close_px=0` → 3.
2. **Grayscale cannot see an orange rim on lit skin** — nearly isoluminant.
   The right lens was never found in *any* frame until edges were computed on
   the per-pixel max gradient across B, G, R, a\*, b\*. That is not colour
   thresholding: it picks no colour and has no cut, so it does not drift with
   the room lights.
3. **A square is a perfect ellipse by every test but fit residual.**
   `fitEllipse` on a square gives axis ratio 1.00 and arc coverage 1.00. Real
   rim residual 0.021–0.044, squares 0.100–0.106. A faire is full of squares.
4. **`findContours` cannot deliver a rim from a real face.** The outline is
   present at the right size but arrives broken into arcs *and* fused with
   brow and hair edges, so no connected component is a ring — the best-scoring
   contour in the frame was the **eye**. Hough centres + a radial profile
   (median over 180 angles, so a gap costs a few angles) work.

**Rank candidate pairs by span residual, never by ratio or size error.** Those
are cheap for clutter to fake — a spurious background pair beat the real rims
0.122 to 0.126 and a distance read 353 mm against a true 457.

## Lighting

Mild backlighting **did not hurt** (halo/face 1.21 gave the best pose rate
measured; the annulus never dropped below 100%). **The daylight/window case is
untested** and is the one a faire presents.

**Measure the halo around the head, not the frame average** — a lamp behind
the subject moved whole-frame bg/face from 0.82 to 0.83, i.e. reported
nothing, while the halo read 1.21. **Face brightness does not predict
detection**: face spanned 91–152 while pose ranged 48–84% with no ordering
between them.

**Rim detection needs its own exposure** (312/gain 192) — the gaze setting of
156/0 is short deliberately so a saccade does not smear. The trap: exposure
1250 *reads* as well exposed and is worse than useless, because 125 ms smears
the rim and a lens detected at 156 vanishes entirely. **Brighter and blinder
at once — fix darkness with gain, not time.**

## Rig constants (calipered, 10 pairs, spread ±0.2 mm)

Outer diameter **50.0 mm**, inner **44.0 mm**, rim 3.0 mm, centre-to-centre
separation **61.5 mm**. The separation is *not* the 67–75 mm predicted from
the 137 mm frame width — that estimate was 15.4% high, and the placeholder
built on it made the pair test hunt for the wrong ratio. **Measure it; do not
derive it.**

Camera intrinsics are calibrated (RMS 0.306 px, fx/fy agree to 0.2%). Every
distance is `f × size / pixels`, so an error in `f` is proportional error in
everything — larger than the difference between any two fiducial designs.

## Open

1. Repeat Gate 1c in good light — the 3.27° run was dim (face 55.4 vs 128.7).
2. The window/backlit test. Needs daylight.
3. Yaw from the **mean axis ratio** of the two coplanar rims — the one untried
   idea with an argument behind it, and worth ~2° of systematic bias to escape
   19° of noise.
4. Make linear the spike's default too (the game already switched); it needs
   its own fresh run rather than a refit.
