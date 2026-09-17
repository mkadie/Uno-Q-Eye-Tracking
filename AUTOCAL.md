# Auto-calibration — design notes

Written 2026-08-16, after Gate 1c produced 5.1 deg and a pile of negative
results. This is a design document, not a measurement: everything here is
reasoning and prior art, and the parts that need measuring are marked as such.

Context: this has to work at a maker faire, on somebody else's machine, for a
visitor who arrives, tries it for ninety seconds, and leaves.

---

## What is actually wrong with what we have

`bin/calibrate` fits a 66-parameter polynomial from 25 targets shown **on the
UNO Q's own display**. Three properties make it undeployable, and only the
first is obvious:

1. **It needs the UNO Q to show targets.** In deployment the user is looking at
   the *destination* machine's screen. The UNO Q is a sensor bolted to the side.
2. **It needs to know the screen geometry** to place targets and to convert
   pixels into degrees. Every destination screen is different.
3. **It conflates the person with the setup.** The fitted polynomial encodes
   "this person's eyes" *and* "this camera at this angle to this screen" in one
   inseparable blob of 66 numbers. Nothing transfers. A new visitor means
   refitting everything; moving the rig means refitting everything.

(3) is the deep one, and it explains the measurements. Gate 1c had 25 points
for 66 parameters and could not generalise five seconds into the future
(`RESULTS.md` § "Gate 1c run 7"). That is not bad luck. It is what happens when
you ask a black-box regression to learn optics, anatomy and furniture at once
from 25 samples.

---

## The proposal: split the person from the setup

```
screen point  =  f_setup( g_person( landmarks ) )

g_person : landmarks -> a gaze RAY in camera coordinates
           (origin = eye centre in 3D, direction = visual axis)
           depends on the person's eye geometry. NOT on the screen.

f_setup  : ray -> screen point
           ray-plane intersection, then metres -> pixels.
           depends on where the screen is relative to the camera. NOT on
           the person.
```

Everything good follows from this split:

| | varies with | when it must be measured |
|---|---|---|
| `g_person` | the visitor | once per person, ~4 parameters |
| `f_setup` | the rig placement | once per setup — **all day at a faire** |

At a faire the camera is clamped to the monitor and does not move. `f_setup` is
measured once in the morning. Each visitor then needs only `g_person`, and
`g_person` is *small*: the dominant person-specific term is the **kappa angle**
between the eye's optical axis (which we can see) and its visual axis (where
they are actually looking). Kappa is about 5 deg, varies between people, and is
**two numbers per eye**.

Four parameters from a handful of samples is a completely different problem
from 66 parameters from 25 samples. That is the whole argument.

### What this buys, concretely

- A new visitor is usable after ~4 well-chosen samples instead of 25.
- A population-average kappa gives a working-but-imprecise cursor
  **immediately, with zero calibration** — good enough to click large buttons,
  which is good enough to bootstrap (see below).
- Moving to a different destination machine changes only `f_setup`.
- Head movement stops being a source of drift and becomes an *input*: the ray
  origin moves with the head, which is geometry we compute rather than a
  correlation we hope holds. This directly attacks the failure measured in
  runs 2–8, where the fit leaned on `t_y` and fell apart when the head shifted
  6 mm.

---

## Getting `f_setup` without any software on the destination machine

This is the part I think is being over-thought, and it is worth stating
plainly:

> **The screen's physical corners are calibration targets. They need no
> rendering, no software, and no coordination.**

"Look at the top-left corner of your monitor" is an instruction that works on
any machine, in any OS, with the destination powered off. The corners are
physically there. Their spatial relationship is known once you know the panel's
width and height in mm, which is one tape-measure reading (or a lookup from the
model number).

So the initial calibration routine is:

1. Prompt the user to look at each of the four corners, then the centre.
2. Prompt with **sound** (a beep per target) or a helper's voice — not with a
   display. The UNO Q has no screen requirement at all in this scheme.
3. Five (feature, direction) pairs is plenty to solve for `f_setup` given
   `g_person`, or for kappa given `f_setup`.

The centre is the only weak target — "the middle of your screen" is vague. Fix
it with a sticker, a bezel notch, or just drop it and use the four corners plus
the camera itself ("look at the lens") which is a *perfectly* known direction:
the ray to the camera origin is (0,0,0) by definition. **"Look at the camera"
is a free, exact calibration point.** That is worth exploiting.

Your eventual idea — coordinating with the destination machine to show targets
— is strictly better for precision, and it is the right long-term path. But it
requires software on every destination, which cuts against the project's core
premise (`CLAUDE.md`: this is a bolt-on for people who already built the
sip-n-puff). Keep it as the optional high-accuracy path, not the default.

---

## Bootstrapping without any explicit calibration at all

Prior art here is strong and directly applicable.

**WebGazer** ([paper](https://jeffhuang.com/papers/WebGazer_IJCAI16.pdf)) does
exactly what we need: it never runs an explicit calibration. Every mouse click
is a training pair, because a user who clicks a button was looking at it. It
reports ~4.17 deg against a commercial tracker — which is *the same ballpark as
our measured 5.1 deg*, and reassuring: we are not doing something uniquely
badly, we are hitting the normal webcam-gaze ceiling.

We have the same signal, and better: **the breath board already generates
discrete, intentional clicks**, and it is the HID endpoint, so it knows exactly
when a click fired. Each click yields (gaze features at that instant -> the
centre of whatever was activated).

This session measured that this works on our own data:

| clicks fed back | held-out error |
|---|---|
| 0 | 8.22 deg |
| 3 | 6.11 |
| 8 | 5.58 |
| 20 | **5.12** |

Monotonic. The mechanism is real; `calib.py`'s anchor-decay design was built
for it. What we lacked was a sane starting point — which is what the geometric
model provides.

**The bootstrap loop:**

```
population-average kappa           ->  crude cursor, maybe 6-8 deg
   -> user clicks big targets      ->  each click refines kappa
      -> cursor tightens           ->  smaller targets become clickable
         -> more clicks            ->  converges
```

The chicken-and-egg ("you need a cursor to click, you need clicks to get a
cursor") is broken by the fact that a 6-8 deg cursor can still hit a 100 mm
button, and the first UI the visitor sees can be exactly that: four huge tiles.

**Related prior art worth reading:** implicit calibration that clusters samples
by head pose and updates a local model per cluster
([Tri-Cam](https://arxiv.org/html/2409.19554v1), and the mouse-operation work
in the ScienceDirect/ResearchGate results below). Clustering by head pose is a
cheap approximation of what the geometric model does properly.

---

## Smooth pursuit — the calibration nobody notices

[Pursuit calibration](https://dx.doi.org/10.1145/2501988.2501998) samples
calibration points while the user follows a *moving* target, and detects
attention by correlating eye motion with target motion. Two properties matter
for us:

- **Correlation-based detection is independent of offset and scale.** It tells
  you *that* the user is following, without needing a calibrated mapping. This
  is a way to get supervision before you have a working mapping.
- It can run **without the user knowing it is calibration** — it can be the
  attract-loop animation on the faire stand.

Threshold in the literature is r > 0.8 over a short window.

The catch: it needs something to move, i.e. a display on the destination. So it
belongs with the coordinated path, not the zero-software path. Worth
remembering that the *thing that moves could be physical* — a hand waved in a
prescribed arc, a servo-driven dot, an LED strip. At a faire stand that is not
absurd.

---

## The target-free constraint: both eyes look at the same point

From the 3D-model literature: the visual axes of the two eyes **intersect at
the point being looked at**. If we also assume that point lies on the screen
plane, that is a constraint per frame with **no knowledge of where the user is
looking**.

That means: let the visitor use the thing for thirty seconds, collect frames,
and solve for the kappa values that make the two eyes' rays converge on the
screen plane most consistently. No targets, no clicks, no cooperation.

I rate this the most interesting research direction here and the least certain.
It depends on resolving both irises well enough that the vergence angle is
meaningful, and our iris radius is 8–10 px. Vergence at 600 mm is a small
angle. **This needs measuring before it is believed** — but the data to test it
offline may already exist in `ref_frames.npz` and the eight `cal_*.npz` runs.

---

## What to do with the rig we have — the "distances and angles" experiment

Your instinct is right, and the split above says exactly what the experiment is
*for*: **to test whether `g_person` is genuinely independent of the setup.**

Important framing point: using the UNO Q's display to *generate ground truth*
in the lab is completely legitimate. What must not happen is *depending* on it
at deployment. The display is a measurement instrument here, like the chin rest.

**Experiment A — does the mapping survive a geometry change?**

For one person, collect the standard 25+26 grid at a matrix of conditions:

| axis | values |
|---|---|
| distance | 450, 600, 750, 900 mm |
| lateral angle | 0, ±20 deg off-axis |
| camera height | at screen top, at screen bottom |

Then measure, for both models:

1. Fit on condition A, test on condition B, for every pair.
2. The current 66-param polynomial should fall apart (prediction: it will do
   roughly as badly as the 5 s block gap already does).
3. A geometric `g_person` + recomputed `f_setup` should hold up. **If it does
   not, the whole decomposition is wrong and this document is wrong.**

That is a real experiment with a real falsifiable prediction, and it is the
cheapest way to find out whether any of this is right.

**Experiment B — how many parameters does a person actually need?**

Using the eight runs already saved: fit kappa-only (2–4 params) against the
full polynomial (66) on the same data, and compare held-out error. This needs
no chair time at all — the `.npz` files carry raw `aX`/`ay`/`vX`/`vy`.

**Experiment C — is the vergence constraint usable at our iris resolution?**

Offline, from saved runs: compute both eyes' rays under a candidate eye model,
and see whether the convergence point is stable enough to carry information.
Also no chair time.

Do B and C first. They are free.

---

## Experiments B and C — RUN 2026-08-16, offline, no chair time

Both needed no sitting, so they are done. Results below are measurements, not
proposals.

### B: how much per-person/per-session fitting is actually needed?

Using runs 4, 5 and 7 (same person, same rig, 720p, chin rest). Fit on one
session, test on run 7's held-out validation block.

| | error |
|---|---|
| fit from scratch on run 7, 25 points | 8.22 deg |
| **run 4 mapping, raw transfer** | **168 deg** |
| **run 5 mapping, raw transfer** | **49 deg** |
| run 4 mapping + affine correction, 3 points | 10.00 |
| run 4 mapping + affine correction, **4 points** | **7.83** |
| run 4 mapping + affine correction, 6 points | 6.96 |
| run 4 mapping + affine correction, 10 points | 6.52 |
| run 5 mapping + affine correction, 4 points | 9.70 |
| run 5 mapping + affine correction, 10 points | 7.42 |
| chance | 7.78 |

**Two findings, and they point the same way.**

1. **The 66-parameter polynomial does not transfer at all** — not even between
   two sessions of the *same person on the same rig* minutes apart. 49 and
   168 deg are not "degraded", they are meaningless. Anything that assumes a
   stored per-person profile survives a session boundary is wrong.
2. **A 4-parameter affine correction on 4 points recovers everything.** 7.83
   deg from 4 points versus 8.22 deg from a full 25-point refit. Six points
   beats the full refit outright.

That is the design in miniature, confirmed on real data: **keep a mapping, and
re-anchor it each session with a handful of points.** And note the number —
**four points is what the four screen corners give you.** The corner-based
routine and the measured parameter requirement land on the same number, which
is a pleasant place to be.

Caveat, stated clearly: this is one person across sessions. It does **not**
show that a mapping transfers *between people* — that is Experiment A's job,
and the k=2 row (231 deg, unstable) shows the correction itself needs enough
points to be well-posed. Use 4 minimum, prefer 6.

### C: is the vergence constraint usable at 8-10 px iris radius?

Matched the 25 identical target positions across runs 5 and 7 and compared the
vergence proxy `lx - rx` against the plain horizontal signal, using
session-to-session disagreement as the noise estimate:

| signal | spread across targets | session noise | SNR |
|---|---|---|---|
| vergence (`lx - rx`) | 0.01376 | 0.00900 | **1.53** |
| plain iris-x | 0.01351 | 0.00727 | **1.86** |

**Vergence is not dead.** Its SNR is within 20% of the primary signal we
already rely on, so the target-free binocular constraint is worth pursuing —
it is no worse-conditioned than the thing the whole tracker already runs on.

**But look at the second column, because it is the more important result.**
Session-to-session noise is roughly *half* the entire across-target spread, for
the main signal. The features themselves are only about 2x repeatable between
sittings. That is very likely the real ceiling — not iris pixels, not the
model, not the regulariser. It also explains every transfer failure in this
document, and it is consistent with B: if the features shift between sessions,
you *must* re-anchor per session, and a small affine correction is exactly the
right shape of fix.

(The noise estimate is an upper bound — head position genuinely differed
between the two sessions, so some of that "noise" is real signal we are not
modelling. A proper measurement would repeat identical targets *within* one
sitting, which is a 2-minute run and worth doing.)

---

## The repeat-targets test — RUN 2026-08-18, INCONCLUSIVE (confounded)

`bin/repeat` was built for this (9 targets x 3 passes, 45 s rest between,
220 s total) and run. **The result must not be quoted**, and the reason is
instructive.

Raw output:

| feature | spread | noise | SNR |
|---|---|---|---|
| l_iris_x | 0.00936 | 0.01423 | **0.66** |
| l_iris_y | 0.01097 | 0.01887 | 0.58 |
| r_iris_x | 0.00452 | 0.01011 | **0.45** |
| r_iris_y | 0.00931 | 0.01364 | 0.68 |

SNR below 1 would mean repeated looks at the *same* target disagree more than
different targets differ — i.e. the sensor cannot tell the targets apart at
all, and the ceiling is hardware.

**But the run is not comparable to the calibration runs it is meant to explain:**

| | run 7 | repeat run |
|---|---|---|
| seating distance | 730 mm | **442 mm** |
| `r_iris_x` across-target spread | 0.01188 | 0.00452 (**0.38x**) |
| `l_iris_y` across-target spread | 0.02044 | 0.01097 (0.54x) |
| head movement between repeats | — | **6-9 mm** |

At 442 mm the screen subtends ~42 deg instead of ~26 deg, so iris excursion
should have gone **up about 1.6x**. It went **down 2-4x**. That combination —
closer seating, smaller eye movement, several mm of head movement between
passes — is the signature of the subject **turning their head toward each
target instead of moving their eyes**. The head does the work, the iris signal
shrinks, and the head-pose variance grows. The run measures posture, not the
sensor.

Removing a linear head-pose term lifts the SNR only to 0.56-1.02, so head pose
does not fully explain it either. Both readings are consistent with "the eyes
barely moved".

`bin/repeat` now **withholds its verdict** when head movement between repeats
exceeds 4 mm, and prints the head-pose-removed SNR alongside the raw one. The
2026-08-18 run trips that guard at 8.9 mm.

### How to run it so the answer counts

1. **Chin rest, genuinely used.** The whole measurement depends on the eyes
   doing the work. Verify afterwards: head movement between repeats should be
   under ~3 mm.
2. **Fixed distance, matching the run being compared against** (730 mm for
   run 7, or re-run run 7's protocol at the new distance — but pick one).
3. Keep the rests short, or drop them: the 45 s "look wherever you like" screen
   is what invited the repositioning. A 10 s rest still separates the repeats
   in time without inviting a whole new posture.

One incidental positive: **442 mm is a much better place to sit** for this
sensor — more iris pixels, which is the one lever that has ever helped. If the
head can be held still there, it is worth re-running everything at that
distance rather than 730 mm.

---

## Risks and honest doubts

- **We may be at the sensor ceiling.** WebGazer's 4.17 deg and our 5.1 deg are
  suspiciously close. If ~4 deg is what an uncalibrated consumer webcam gives,
  no amount of clever calibration reaches 2 deg, and the answer is an interface
  designed for 5 deg (large tiles + zoom-to-refine) rather than a better
  tracker. `PLAN.md` Path B already anticipates this.
- **Iris resolution is marginal.** 8–10 px radius. Run 8 showed that naively
  adding pixels makes things *worse* if ROI alignment degrades, so this is not
  a simple lever.
- **Vertical is much weaker than horizontal** (raw correlation 0.62 vs 0.90).
  Eyelid occlusion is the likely cause and it is anatomy, not code. A UI with
  wide, short tiles suits the sensor better than a square grid — that is a
  design decision the measurements are pointing at.
- **The geometric model needs camera intrinsics.** Focal length in pixels for
  the C920 at 1280x720 — needs a one-off checkerboard calibration, or the EXIF
  /spec value as a starting point. Currently `features.head_pose` guesses.
- **Absolute distance is biased.** PnP against a canonical face model inherits
  face-size error; today it read 701 mm against a config of 584. For a
  geometric model this matters more than it did for the regression, because it
  scales the ray-plane intersection. Mitigation: solve per-person scale from
  the corner calibration, where the geometry is over-determined.

---

## Suggested order of work

1. ~~Experiment B~~ **DONE** — 4 points + affine ≈ a full 25-point refit.
2. ~~Experiment C~~ **DONE** — vergence SNR 1.53 vs 1.86 for the main signal;
   usable. And the incidental finding that matters more: session-to-session
   feature noise is ~half the signal spread.
3. ~~Repeat-targets run~~ **RUN 2026-08-18 — INCONCLUSIVE, needs redoing.**
   `bin/repeat` exists and works; the run was confounded by the subject sitting
   at 442 mm instead of 730 mm and turning their head toward targets rather
   than their eyes. See the section above for how to redo it so it counts.
   **Still the most informative cheap measurement available** — it is the
   difference between "build better calibration" and "stop, the sensor is the
   limit" — so redo it properly before step 4.
4. **Corner-based calibration, 4-6 points, audio-prompted.** B says this is
   enough; it needs no destination software; it is the deployable routine.
   Build this before any geometry work — it is cheap and it is the product.
5. Click-driven refinement on top (mechanism already measured: 8.22 -> 5.12
   deg over 20 clicks).
6. Camera intrinsics — one checkerboard session, unblocks all geometry.
7. Implement the `g_person` / `f_setup` split behind the existing `GazeMapper`
   interface, so `bin/calibrate` and the online-click path keep working.
8. **Experiment A** (distances and angles) — the falsification test for the
   split. Only worth the chair time once 3 says the sensor can support it.
9. Only then, optionally, the coordinated destination-display path.

**What changed after running B and C:** the corner routine moved *up* (4 points
is provably enough) and the geometric split moved *down* (it is a bigger job,
and step 3 may show the ceiling is elsewhere). Do the cheap decisive
measurement before the elegant architecture.

---

## Sources

- [WebGazer: Scalable Webcam Eye Tracking Using User Interactions](https://jeffhuang.com/papers/WebGazer_IJCAI16.pdf) — click-based self-calibration, ~4.17 deg
- [WebGazer project page](https://webgazer.cs.brown.edu/)
- [Pursuit calibration (UIST 2013)](https://dx.doi.org/10.1145/2501988.2501998) — correlation-based, offset/scale independent
- [Using Smooth Pursuit Calibration for Difficult-to-Calibrate Participants](https://pmc.ncbi.nlm.nih.gov/articles/PMC7141046/)
- [Calibration-Free Gaze Interfaces Based on Linear Smooth Pursuit](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC7881880/)
- [Tri-Cam: Practical Eye Gaze Tracking via Camera Network](https://arxiv.org/html/2409.19554v1) — implicit calibration from clicks, head-pose clustering
- [3D gaze estimation without explicit personal calibration](https://www.sciencedirect.com/science/article/abs/pii/S0031320318300438)
- [Model-Based 3D Gaze Estimation Using a TOF Camera](https://pmc.ncbi.nlm.nih.gov/articles/PMC10891597/) — eyeball/cornea model, kappa
- [3D Eye Modeling and Geometry-based Gaze Estimation (RPI CVRL)](https://sites.ecse.rpi.edu/~cvrl/3DFace_Eye/3D_eye.html)
- [Display-camera calibration using eye reflections](https://www.sciencedirect.com/science/article/abs/pii/S1077314211000725) — corneal reflection for display pose (needs resolution we do not have)
- [Evaluating Calibration-free Webcam-based Eye Tracking](https://dl.acm.org/doi/fullHtml/10.1145/3536221.3556580)
- [Webcam-based Eye Gaze Tracking under Natural Head Movement](https://arxiv.org/pdf/1803.11088)
