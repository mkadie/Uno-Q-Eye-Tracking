# Glasses-rim head pose

Closed-form 6-DOF head pose from round lensless party glasses. The circular
rims **are** the fiducial — nothing is printed, cut or glued onto them.

## UPDATE 2026-09-19 — the rig is now CALIPERED, and the photo was wrong

`update.md` delivered measured constants. They supersede everything derived
from the product photo:

| quantity | photo-derived | **calipered** |
|---|---|---|
| outer diameter | 47.0 mm (r 23.5) | **50.0 mm (r 25.0)** |
| inner diameter | — | **44.0 mm (r 22.0)** |
| rim thickness | — | 3.0 mm |
| centre-to-centre | 62.7 mm | **STILL MISSING**, expect 67–75 |

**Why the photo lied, and why it matters twice over.** The product image is
labelled 1.85 in = 47.0 mm, and 47.0 is exactly the **mid-rim** diameter
((50+44)/2). Scaling off it produced the midline radius, not the outer one —
a 6% error in every distance.

And it explains the hardware run that never made sense. `bin/rimcheck`
measured an implied radius of **23.71 mm**; the mid-rim radius is **23.50**.
The detector had been fitting the two rim edges **merged into one midline
ellipse** the whole time, which is precisely what `update.md` §2.2 predicts
below ~960 px detect width — and we were running at 1280. The "good" agreement
between the photo value and the measured value was two wrongs matching.

**What changed in code:**

- `ring_pair()` — requires the two concentric edges at ratio 1.1364 ±6%, at
  least `MIN_RING_SEPARATION_PX` apart and genuinely concentric. This is both
  the false-positive filter (coffee lid 1.060, grommet 1.350, CD 8.000 all
  rejected) and the answer to "which edge is this", worth 82 mm at 600 mm.
- `RigSpec(inner_radius_mm=...)` and `RigSpec.ring_ratio`.
- `detect_width` 640 → **1920**. The edges do not resolve below ~960.
- `spike/intrinsics.py` — calibrated intrinsics, loud warning on fallback.

**Still outstanding:** the centre-to-centre separation (ten pairs, record the
spread), and `tools/calibrate_camera.py` has not been run. Distance testing
does not wait on either — distance needs the radius alone.

## Status 2026-09-16 — parked, not abandoned

Coloured frames were expected 2026-09-17 and the black-frame **baseline is
recorded below**; run the identical command on the coloured pair and compare
the USABLE line, nothing else. The module, its tests and `bin/rimcheck` are
all in place and staged.

Work moved to driving Bunny Feeding Frenzy by gaze before that comparison
happened. See the game's `GAZE.md`.

## The decision, and why

A circle projects to an **exact ellipse** under perspective, and no other
outline does. So every departure from circular in the image is pure pose
information, and the inversion is closed form — no solver, no per-batch
contour template, no learned model. A wayfarer or cat-eye outline is already
non-circular, so its shape and its perspective are entangled.

Two rims rather than one: both lie in a single plane, so the rig's own x-axis
must be perpendicular to the shared normal. That resolves the planar-marker
sign ambiguity for **yaw**. It does not rescue **pitch** — see gotcha 2.

Rejected, with reasons, so they are not re-proposed: wayfarers with printed
ArUco tabs (no flat area big enough, ~600 glue joints across 200 pairs, and a
tab that rotates silently corrupts the rig geometry); cat-eye frames with
rhinestones (rhinestones are *mirrors* — the glint moves with the light, not
the object — and 2–3 mm is about 5 px at working distance); QR codes (built
for a data payload, corners not optimised for pose).

## Accuracy actually achieved

75-pose sweep (5 yaw × 5 pitch × 3 distances, ±20°, 450/600/900 mm), C920-class
intrinsics at 1920×1080 and 70.4° HFOV, noise-free, pitch hint supplied:

| DOF | mean error | max error | target | |
|---|---|---|---|---|
| distance | **0.469 mm** | **1.204 mm** | < 2 mm | pass |
| yaw | **0.102°** | **0.435°** | < 0.5° | pass |
| pitch | **0.214°** | **1.369°** | < 3° | pass |
| roll | **0.008°** | **0.036°** | < 1° | pass |

Against 0.5 px of fitting noise, yaw error stays under 2° at 12° yaw.

These are **synthetic** numbers: a rig of known dimensions projected through a
known camera, fitted with the same `cv2.fitEllipse` the production path uses.
They validate projection, fitting and inversion as a chain. They say nothing
about detection on a real frame in a real hall, which is untested.

## First hardware test, 2026-09-16 — detection does NOT work yet

Real glasses (round Warner Bros costume frames, black), real face, 584 mm,
`bin/rimcheck`. **The geometry is fine; the detection is not.** Recorded here
because the failures were instructive and the honest state is easy to lose.

What happened, in order:

| filter state | "detection" rate | plausible |
|---|---|---|
| no arc filter | **100%** | **0%** |
| + arc coverage/residual | 0% | — |
| + CLAHE, close=7 | 62% | **0%** |
| + scale-invariant ratio check | 12% | **0%** |

**Every single pose was rejected by `plausible()`.** That is the system working
as designed -- the span check is a measurement the pose never used to derive
itself -- but it means no real rim has been successfully located yet.

The first row is the important one. Unfiltered, `cv2.fitEllipse` reported a
confident pair on **every frame**, with a 17 mm radius on a 23.5 mm rim and an
axis ratio of 0.585 while the subject faced the camera square-on. It was
fitting **arcs** -- fragments of eyebrow, eyelid and rim, tangled together in
the edge map. Nothing downstream could have told.

Three filters were added as a result, each measured rather than guessed:

- `arc_quality()` -- angular coverage about the fitted centre plus normalised
  fit residual. An arc cannot cover more bins than its own extent.
- **CLAHE** before Canny. Without it, 0 of 12 saved frames contained a contour
  that was simultaneously round, right-sized, well-covered and a good fit.
  With it, 9 of 12 did.
- **The scale-invariant ratio check**, which is the one that should have been
  there from the start: the rig fixes `separation/radius = 2.67`, and that
  ratio holds at *any* distance. The junk pairs sat at ~5.0. Unlike the size
  gate it needs no distance estimate and cannot be fooled by a subject who is
  simply nearer or further than expected.

### With a lamp on and the subject at 508 mm — it WORKS, intermittently

Second session, same day. A desk lamp lifted the face region from mean 21 to
**85.8** (whole-frame mean barely moved, 68 -> 74, because the frame is mostly
dark room -- measure the FACE, not the frame). Subject moved to 508 mm, so the
rims grew to ~80 px across.

**The first plausible pose:**

```
L@608  R@712   a = 40.3 / 38.9 px   axis ratio 0.93
distance 538 mm (true 508)   span residual 2.2 mm   plausible = True
```

Span residual 2.2 mm against 163-199 mm for every earlier junk pair. And with
better-tuned gates a later frame gave **distance 509 mm against a true 508 mm**.
When detection succeeds, the geometry is as good as the synthetic tests
promised.

Two changes made it work, both driven by the data:

- **Median residual, not RMS.** A real rim usually arrives with a temple arm or
  eyebrow fused to part of its contour. RMS lets that minority destroy an
  otherwise clean rim: the right rim scored RMS 0.297 against median 0.151,
  while genuine junk scored 0.288 median. RMS could not separate them.
- **Coverage 0.40, not 0.75.** A real rim often arrives as a clean PARTIAL arc:
  the left rim above had coverage 0.44 and a median residual of 0.058, fitting
  to 40.3 px against a true 42.0. What makes a permissive coverage gate safe is
  not the gate -- it is the pair-level scale-invariant ratio check, which no
  accidental pair has ever passed.

### Reliability: ~19% of frames, and that may be enough

Swept over 16 unbiased frames (saved every 3rd regardless of outcome -- saving
only the hits biases tuning toward what already works):

| gate setting | found | **usable** | median distance |
|---|---|---|---|
| cov 0.40, resid 0.18, close 3, no CLAHE | 11/16 | **3/16 (19%)** | 463 mm |
| cov 0.55, resid 0.18, close 3, no CLAHE | 11/16 | 1/16 | **509 mm** (true 508) |

"Usable" means found AND plausible. 19% sounds poor for a tracker -- but this
is not a tracker. **Head pose moves slowly**, which is the entire reason
`detect_every_n = 5`. At 19% usable and 9 fps, a validated pose arrives roughly
every 3 seconds, which is ample for the jobs it has: distance zones for the
NeoPixels, the eye ROI crop, and a pitch-sign hint.

What it is NOT yet good enough for is anything wanting continuous head pose.

### BLACK-FRAME BASELINE, 2026-09-16 — the number to beat tomorrow

100 frames, one held pose. **Recorded so the coloured-frame test is a
controlled comparison rather than an impression.** Match every condition below
or the comparison means nothing.

| condition | value |
|---|---|
| frames | black, round, 23.5 mm outer radius, 62.7 mm centre-to-centre |
| distance | 508 mm (20 in), camera to frame |
| lighting | desk lamp frontal; face-region mean 85.8 |
| exposure | 625 (gain reads 0; the configured 156 is far too dark for this room) |
| capture | 1280x720, fx = 907.3 from nominal 70.4 deg HFOV (NOT calibrated) |
| gates | cov 0.40, resid 0.18, close 3, CLAHE off, canny (40,120) |

**Result:**

| metric | value |
|---|---|
| frames yielding a pair | 44 / 100 (44%) |
| **frames USABLE (found AND plausible)** | **2 / 100 (2%)** |
| implied radius at 508 mm | **23.71 mm** vs 23.50 configured |
| major-axis jitter | 21.7% |

Two things worth separating here.

**The good:** implied radius **23.71 mm against a configured 23.50 mm**. When
the detector locks on, it is measuring the right circle -- the rim's outer
edge, not the inner -- and the photo-derived dimension is confirmed to better
than a millimetre. The inner/outer ambiguity flagged earlier is resolved:
it fits the outer.

**The bad:** 2% usable. 44% of frames produce a pair and 95% of those are junk
that `plausible()` throws away. The gates are admitting far more than they
should, and only the pair-level checks stand between that and a confident
wrong pose.

Note the earlier 19% figure came from a 16-frame offline sweep on a
deliberately-held pose; 2% over 100 live frames is the honest number. Quote
this one.

### For tomorrow's coloured-frame test

Run exactly this, changing only the glasses:

```
./bin/rimcheck --at 508 --expect 508 --exposure 625 --frames 100 \
               --debug /tmp/colour.png --save rims_colour.npz
```

Compare the **USABLE** line, not the find rate. A rig change that lifts finds
from 44% to 80% while usable stays at 2% has made things worse, not better.

If the room light differs, re-measure the face region first -- whole-frame
brightness is misleading here, it is mostly dark room.

### Why detection still misses, and what would fix it

Root cause is image quality, not parameters. The evidence:

- Room brightness at the configured exposure 156 was mean **21** (a well-lit
  face frame sits at 90-140). Even at exposure 1250 -- 125 ms, which drops the
  loop to **5.8 fps** -- it only reached 108.
- **Black frames against dark hair and shadowed brows is the worst case for
  edge detection.** The rim/face contrast is where the whole method lives.
- At 584 mm the rims are only ~73 px across, so there is little to work with
  once the outline fragments.

Ranked fixes, cheapest first:

1. **More frontal light.** DONE once, and it was the difference between 0% and
   19% usable -- but the face region is still 85.8 mean against a 90-140
   target. The lamp is working; it wants to be brighter or closer.
2. **Lighter-coloured frames.** White or bright rims against skin and hair
   would be far higher contrast than black. `GLASSES-PROMPT` already assumes
   five rim colours for visitor identity, so this is in scope -- and black is
   the worst of the five, not a representative sample.
3. **Sit closer.** More rim pixels. 400-450 mm roughly doubles the rim area.
4. Longer exposure works but costs frame rate, and the rim path can afford
   that better than the gaze path can -- head pose is sampled every
   `detect_every_n` frames.

**None of this invalidates the approach.** The closed-form geometry is verified
to sub-millimetre and sub-degree against synthetic ground truth, and the
consistency checks caught every bad pose without a single false accept. What is
unproven is Canny finding a black plastic circle in a dim room.

## Three gotchas

**1. Caliper the rims. This is not optional.** A 1 mm error in `radius_mm` is
a ~4% error in every distance the module reports, and it is silent — no check
anywhere will catch it, because the geometry is self-consistent at the wrong
scale. `RigSpec.trusted` stays False until `measured_n >= 5`, and
`[frame_rig]` in `config.toml` ships **disabled** with placeholder dimensions.
Also caliper *several* pairs and record `spread_mm`: party glasses are not
precision optics, and a spread above 1 mm means the rig is less "known" than a
single measurement suggests.

**2. Pitch needs a hint near square-on.** Both rim centres lie *on* the rig's
x-axis and pitch rotates *about* that axis, so at zero yaw, tilting up and
tilting down produce mathematically identical rim geometry. The information is
not in the image. Below `YAW_MIN_FOR_PITCH_SIGN_DEG` (5°) the pose is returned
with `pitch_ambiguous=True`, and `pitch_hint_deg` supplies **the sign only,
never the magnitude** — the hint comes from a different estimator with a
different bias, and mixing the magnitudes would launder that bias in.

The gate is on **measured yaw**, not on how well separated the candidate
normals look. A separation score is not a correctness score.

> **Honest note.** The prompt that specified this warns that between roughly
> 1° and 3° of yaw the candidates separate cleanly *and the winner is
> systematically the wrong one*. **That failure did not reproduce here**: in
> this implementation an ungated discriminator was correct in 72/72 synthetic
> cases (both pitch signs, both yaw signs, noise-free and at 0.5 px noise).
> The gate is kept anyway — it is cheap, it is conservative, and the degeneracy
> at exactly zero yaw is real and provable. But be clear about what the test
> guards: `test_the_inverted_sign_danger_zone_is_gated` proves the gate is
> *applied*, not that the danger exists in this code. If the original failure
> came from a different candidate-normal derivation (e.g. the two-solution
> cone decomposition rather than the analytic normal used here), that would
> explain the difference.

**3. Detect by shape, never by colour.** Five rim colours and a hall whose
lighting drifts all day means any colour threshold that works at setup fails
after lunch. `find_rims()` is Canny + contour + `fitEllipse`, filtered on size
and axis ratio and paired by the known separation. Read colour from *inside*
the fitted ellipse afterwards, purely as a visitor-identity label.

## Integration steps that remain

In order. Nothing below step 1 is meaningful until step 1 is done.

1. **Caliper real frames.** At least 5 pairs. Put `radius_mm`,
   `separation_mm`, `measured_n` and `spread_mm` into `[frame_rig]` and set
   `enabled = true`.
2. **Wire `find_rims()` into the capture loop** at `detect_every_n` (default
   5 — head pose moves slowly next to gaze, and this is the whole reason the
   fiducial is affordable). Run it on a `detect_width`-wide copy, not the full
   frame.
3. **Feed `pitch_hint_deg` from `features.head_pose()`.** Sign only. That
   estimator is biased in magnitude by the canonical-face-model assumption —
   which is exactly the bias this module avoids — so taking its magnitude
   would undo the point.
4. **Drive the NeoPixel zones from `distance_mm`.** This is the first
   user-visible payoff: a "you are too close / too far" indicator that does
   not depend on the gaze pipeline working at all.
5. **Crop with `eye_roi()` before the landmark model.** Measured at ~2% of the
   frame at 600 mm, well inside the 12% budget. Note the lesson from the
   full-res ROI experiment in `RESULTS.md`: the landmark model is trained on
   *aligned* faces, so a crop that is sharper but worse-centred makes things
   worse. Verify the recovered landmarks, do not assume.
6. **Fall back cleanly when no rims are found.** `find_rims()` returns None;
   the pipeline must continue on the existing path rather than stall. Most
   visitors at a faire will not be wearing the glasses at all.
7. **Measure the real fps cost on the board.** `bin/bench`, governor
   `performance`, App Lab stopped. The synthetic accuracy above is free; the
   Canny pass is not.

## Where the code is

| | |
|---|---|
| `spike/frame_fiducial.py` | the module; the four traps are commented in place |
| `tests/test_frame_fiducial.py` | 22 tests, synthetic ground truth, no hardware |
| `CLAUDE.md` | the load-bearing decisions, between the `glasses-fiducial` markers |
| `config.toml` | `[frame_rig]`, shipped disabled |
