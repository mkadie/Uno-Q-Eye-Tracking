# RESTART — read this first after a crash or power loss

Last updated: **2026-09-30**, end of session — HEAD POINTING WORKS, tuned and mapped. Code public on GitHub. **Board powered down.**

> **THE FAIRE RAN Fri 25 + Sat 26 Sep: 125 visitors, 2413 throws, p50 6.26
> deg — and SUNDAY CAPTURED NOTHING.** 87% of visitors got a median error of
> 10 deg or better; **10% got zero valid throws**. All 136 sessions ran
> `cal_points = 9`. The
> data is pulled to `study_data/bff_gaze_study.jsonl` (it existed ONLY on a
> board that has crashed repeatedly -- back it up first, always). Headline and
> caveats are in `RESULTS.md`; only the headline has been read. Deadline is
> **30 Sep 2026**, i.e. tomorrow.

> **THE BOARD CRASHED TWICE on the evening of 2026-09-24** — boots at 22:37
> and 23:24 both ending in `crash`. Those two are real: distinct times, the
> network was up, NTP was syncing. **Do NOT read any later `last -x reboot`
> row as a dated crash** — the RTC has no battery, reads 1970 on every boot,
> and systemd advances it to the last synced value, so a netless board prints
> the same frozen "Sep 27 08:02" for every power-up. See RESULTS.md § "THE RTC
> HAS NO BATTERY". No cause found: **no** undervoltage or over-current in
> `dmesg`, **no** OOM, temps 42-47 C, 2.4 GB free. Nothing was being pushed
> at the time. Two unexplained crashes in one evening is a faire risk in its
> own right -- **check `last -x reboot` at the START of the next session**,
> and if it has grown, treat power first (the board wants 5V @ 3A, and
> undervoltage on this hardware presents as random instability that reads
> like a software bug). The governor was reset to `performance` after the
> last boot; it reverts to `schedutil` on EVERY reboot, so any timing taken
> across one of these crashes is void.

> **HEAD POINTING WORKS, AND IT IS THE ANSWER FOR THE 10% GAZE FAILED.**
> An ArUco tag on the glasses drives the same AAC board. 2026-09-30:
> **100% detection, NOT LOST ONCE in 359 frames**, 23 dwell selections.
> Subject: "almost no drift, went right to my selections." Median trail
> spread **1060 -> 368 px on the vertical axis** against gaze, same subject,
> same day. After the calibration fixes: **RMS 0.0359 of screen** (was
> 0.0793), 18 samples per point (was 8), 2 of 5 points retried (was 5 of 5),
> tag acquired in 0.5 s. **The tag on this rig is id 2, NOT the id 0 head_track.md names** --
> a wrong id reads exactly like bad lighting and cost an hour. It is the 4th
> kiosk row. See RESULTS.md § "Head pointing from an ArUco tag".

> **THE CODE IS PUBLISHED: <https://github.com/mkadie/Uno-Q-Eye-Tracking>**,
> public, MIT. Push with `git push origin master` as normal. Two things about
> it that are NOT recoverable if forgotten:
> **(1)** `board_artifacts` was purged from all 55 commits with
> `git filter-repo` because the frames were shot in a home and several showed
> the subject shirtless. The originals live ONLY at
> `~/unoq-artifacts-ORIGINAL-do-not-publish/` — they are in no git history
> anywhere. **(2)** Everything published went through
> `tools/deidentify.py` (face kept, rest pixelated at 1/44 then blurred).
> **Anything new added to `board_artifacts/` or `docs/` must go through it
> too, with `--raw` for frames that carry no drawn annotations.**

## The 60-second version

The **glasses-rim fiducial now measures distance on real hardware** and does
**not** measure yaw. Both are measured against the printed marker board in the
same frames, not asserted. Everything below is in `RESULTS.md` with the
numbers; this is the orientation.

| thing | status |
|---|---|
| camera intrinsics | **DONE** — `camera_intrinsics.json`, RMS 0.306 px, fx/fy agree to 0.2% |
| glasses calipered | **DONE** — outer 50.0, inner 44.0, separation **61.5**, spread ±0.2 over 10 pairs |
| `RigSpec.trusted` | **True** (`measured_n = 10`) |
| rim **distance** | **WORKS** — bias is a plane offset, IQR 3.7 mm at best, 12.1 mm median |
| rim **yaw** | **DOES NOT WORK** — gain 0.198, correlation 0.138. Do not retry as-is. |
| distance ladder 450–700 | **DONE**, all six rungs |
| lighting conditions | **partial** — mild backlight fine; the daylight/window case is NOT done |
| Gate 1c bare-faced | **DONE — 3.27 deg / 5.56 p95 -> PATH B.** Repeat in good light. |
| red lamp | **WORKS — 3.2x steadier, CI excludes zero, reproduced in the game. USE IT.** |
| fixation protocol | **REBUILT** — the old one measured the subject's drift, not the tracker |
| faire kiosk | **RUNS on hardware** — auto-login confirmed, all three rows launch |
| gaze talker | **selects by DWELL since 2026-09-30.** Before that it needed a key it could not receive |
| head talker | **WORKS 2026-09-30** — tag id 2 on the glasses, 0 losses in 359 frames, RMS 0.079 |
| kiosk with NO KEYBOARD | **fixed 2026-09-24** — every app can now be left by mouse alone. Untested by hand. |
| calibration FIT | **two bugs found and fixed** — see below. This is where the gain came from, not the glasses. |
| the model | **linear (7 par) beats degree-2 (66 par) at every point count tried** |
| bunny game | seats the player before calibrating; linear always; see its `GAZE.md` |
| `DIGEST.md` | portable ~8 KB summary for claude.ai / a fresh chat. **Re-upload when findings land.** |

Suite is **195 passing** here, 194 + 1 skip on the board. No hardware needed.

**What the faire measured, in one line:** 6.26 deg p50 over 125 visitors, 87% of them at 10 deg or better, **10% who got nothing** — and the thing that separated that 10% was HEAD TURN, a cliff at 20 deg, not distance. `RESULTS.md` has it in full.

## What changed this session, and what it means

**Distance works.** At 550 mm: 100% detection, error IQR **3.7 mm**. Median
across the ladder is 12.1 mm. The ~22 mm bias is the marker board sitting
behind the lens plane, **not** a radius error — six rungs separate those two
hypotheses cleanly (constant offset 7.7 mm rms vs proportional 9.6 mm rms,
corr(distance, error) = +0.50). So `radius_mm = 25.0` is fine. An earlier
single-distance claim that it was ~2% high is **retracted**; at one distance a
plane offset and a scale error are indistinguishable.

**700 mm is near the working limit** and for a geometric reason, not a tunable
one: the annulus gap is 9.1 px at 450 and 5.9 px at 700 against a 4.0 px
floor. Detection falls to 57%. **Seat visitors at 500–650.**

**Yaw is dead at this scale.** gain 0.198, correlation 0.138 — no signal, from
frames whose distance is good to millimetres. The arithmetic: yaw is read as a
*difference of two radii*, and at 570 mm a 20° turn moves them apart by
**2.2 px** while measured fit noise is **4.2 px**. SNR 0.53. ±5° would need
0.56 px, ~7× better than achieved. No filter recovers this.

  Worth trying next (NOT yet measured): yaw from the **mean axis ratio** of
  the two rims. They are coplanar so should agree, which averages the per-rim
  noise down. `CLAUDE.md` trap (c) rejects eccentricity-derived yaw for
  carrying ~2° of systematic bias — true, but 2° of bias beats 19° of noise,
  and the depth-difference path it recommends is what just failed. Record the
  axis ratios; `bin/yawcheck` did not.

**Design consequence: the rims give DISTANCE, not orientation.** Head rotation
has to come from the marker board, the face mesh, or an accepted ~2°
eccentricity bias. The gaze mapping's `t_z` feature is fed by distance, so it
is unaffected — which is the part that matters for 30 Sep.

## Four bugs found this session, all silent

Each presented as "the rim is not visible". Do not reintroduce them.

1. **`close_px = 3` was deleting the rim.** The two edges of a 3 mm rim are
   ~7–10 px apart at 1920; a 3×3 close bridges them and fuses the ring into a
   blob that no longer fits an ellipse. Same frame: `close_px=3` → **0**
   candidates survived, `close_px=0` → 3. Now defaults 0. Anything above 0
   forfeits annulus mode.
2. **Grayscale cannot see an orange rim on lit skin** — nearly isoluminant.
   The right lens was never found in *any* frame until `max_gradient()` (max
   per-pixel gradient over B,G,R,a\*,b\*). 2 candidates/one lens → 7/both.
   This is not colour thresholding: no colour is picked and there is no cut.
3. **A square is a perfect ellipse by every gate but residual.** All four
   ArUco markers were being reported as flawless rims — `fitEllipse` on a
   square gives axis_ratio 1.00 and coverage 1.00. Only residual separates
   them (markers 0.100–0.106, real rim 0.021–0.044). `max_residual` 0.18 →
   0.06. Matters beyond the board: a faire is full of screens and keycaps.
4. **`findContours` cannot deliver the rim at all on a real face.** The
   outline is present at the right size and place but arrives broken into arcs
   AND fused with brow/hair edges, so no connected component is a ring — the
   best-scoring contour in the frame was the **eye**. Replaced by Hough
   centres + `ring_radii()` (radial profile, median over 180 angles, so a gap
   costs a few angles) + `ring_ellipse()`.

**Honest correction:** an earlier claim in this session that "annulus 100%" was
a detector win was **wrong**. At 450 mm all twelve Hough candidates passed the
1.1364 ±6% ratio check — `ring_radii` searches peak pairs across a ±45% span
and can nearly always find one. The annulus is a weaker filter than it sounds.
What actually discriminates is ranking pairs by **span residual** (a
measurement the pair did not choose) plus the geometric depth bound
`|z_r − z_l| ≤ separation_mm · sin(max_yaw)`.

## Lighting — the important one is NOT done

| condition | face | halo/face | annulus | pose |
|---|---|---|---|---|
| frontlit | 128.7 | – | 100% | 52% |
| lamp behind, front lights on | 152.2 | – | 100% | 72% |
| front lights OFF | 91.2 | **1.21** | 100% | **84%** |

Mild backlighting **helped**; the annulus never dropped below 100%. The
predicted "backlight kills the inner edge first" did not appear at this level.

Two measurement lessons: **measure the halo around the head, not the frame** (a
lamp behind the subject moved whole-frame bg/face 0.82 → 0.83, i.e. reported
nothing, while the halo read 1.21); and **face brightness does not predict
detection** — face spanned 91–152 while pose ranged 48–84% with no ordering,
the worst pose coming with the best-lit face.

**TODO, needs daylight:** sit with a **window behind you** and run
`bin/lighttest window 40`. halo/face 1.21 was a lamp on a wall at 00:40; a
glazed hall could exceed 3. The sign of the effect is known, the worst case is
not. Distance also varied 515–669 mm across those runs, which is a real
confound since the ladder shows distance alone moves pose by tens of points.

## The calibration fit — where Path B actually came from

No hardware changed between Path C and Path B. Two bugs in the fit did it, and
**neither was visible in the training error** — the worse they were, the
better the run looked.

**1. The 66-parameter model was never earning its parameters.** Scored on 26
held-out targets, refitting stored feature vectors:

| cal points | linear (7 par) | poly2 (66 par) |
|---|---|---|
| 9 | **3.49 deg** | 8.37 deg |
| 25 | **3.01 deg** | 3.27 deg |

Linear wins at *every* point count, including 25 where poly2 was supposed to
have the data. `LinearMapper` uses six features — both iris x/y, yaw, pitch —
plus a bias; dropping roll, t_x, t_y, t_z and every quadratic term costs
nothing measurable. **9 points + linear is within half a degree of a 25-point
fit at a third of the sitting**, which is the argument for a short grid in a
queue.

**2. `ridge="auto"` used leave-one-out CV, which under-regularises here.**
Calibration points collected over ~112 s share a head pose and blink state, so
LOO leaves a held-out point's own time-neighbours in training and it is
predicted partly from itself. Measured on one real run: LOO chose 0.215 ->
11.97 deg; **blocked 5-fold** chose 46.4 -> **2.53 deg**; oracle 2.22. Same
data, same grid, same solver. `_cv_ridge` now uses **contiguous blocked
folds** — they must stay contiguous in COLLECTION order, since strided folds
reproduce the failure while looking like k-fold.

**Honest notes on how that was found.** Along the way I swept ridge against
the *validation* set and got 5.63 and 2.91 deg — those do not count, and the
3.27 deg figure is a fresh run whose penalty came from training data alone. I
also tried a one-standard-error rule first, broke a passing test with it, and
reverted rather than bending the test.

**`config.toml` now says `points = 25`** (was 9) and `viewing_distance_mm = 504`
(was a stale 584, which inflated every degree figure by 16% for months).
**Measure the viewing distance every sitting, and prefer pixels when comparing
across sittings.**

**Still to do here:** the spike still defaults to poly2 above 16 points. The
game has already been switched to linear for any grid it will present. Making
that change in the spike deserves its own fresh run rather than a refit, since
every number above came from data collected for a different model.

## T-Rex Talker demo — built, runs, NOT yet usable

`bin/talker` is a 3x2 AAC board on the gaze pipeline: gaze aims, SPACE/ENTER
speaks. It reads the device's real `.menu` files (`spike/menu.py`) and plays
its real recorded clips. 3x2 rather than the CYD's 4x2 because at 504 mm a
cell is 640x540 px = 12.8 x 10.8 deg, and 2x the measured error needs 327 px
(mean) / 556 px (p95): 3x2 is comfortable, 4x2 is tight on both axes at p95.

**Status 2026-09-21: it runs and gives "some control, but very jumpy".** Not
yet demoed successfully. Hysteresis was added in response and **has never been
tested** — that is the first thing to try next session.

The hysteresis idea, for whoever picks this up: on a 6-cell board, jitter
*inside* a cell is cosmetic and jitter *across a boundary* is fatal, because
the highlight flickers between two cells and the user cannot tell which one a
keypress will speak. So a new cell must win `--hold` consecutive samples
(default 3, ~190 ms at 16 Hz) before the hover moves, and the committed cell
is what a keypress acts on. That spends lag only at the boundary, where
smoothing would spend it everywhere. `--smooth` (default 0.35) additionally
scales `min_cutoff` down, because config.toml's value is tuned for a cursor
chasing a moving target and an AAC board is the opposite case — the target
does not move and lag is nearly free.

**Open question, unmeasured:** whether the jumpiness is a filtering/UX problem
that hysteresis fixes, or whether the landmark estimate itself is too noisy at
this working distance. Nobody has measured the sample-to-sample noise of the
gaze point while fixating, which is the measurement that would tell them
apart. Do that before changing the tracker.

## WHY IT IS JUMPY — the number that explains the whole project

**The entire screen is about 14 px of iris movement.** At 504 mm the screen
subtends +/-18.5 deg; an eyeball of radius 12 mm rotating that far translates
the iris 7.6 mm, which at the 1280-wide capture is **13.8 px**. Mapping that
onto 1920 px of screen is a **gain of 139 screen px per px of iris**.

So **one pixel of iris-centre error is 2.8 deg of gaze error**, and the
measured 3.27 deg is **1.17 px of iris noise**. The pipeline is sitting at
roughly one pixel of landmark precision, which is near the floor of what the
478-point model delivers in a single frame.

That single number explains things that looked unrelated:

- "My eyes are not moving but the cursor jumps" -- sub-pixel landmark jitter
  multiplied by 139.
- "Without a bright light I get nothing" -- less light is more sensor noise is
  worse than a pixel.
- Why better models and more calibration points plateau around 3 deg: they fit
  the mapping better, but they cannot manufacture iris precision.
- Why raising capture resolution did NOT help in August. The landmark model
  crops the face and resizes to a FIXED 256x256, so iris pixels *in the
  model's input* are set by anatomy (iris is ~8% of face width), not by the
  camera mode. More capture pixels only reduce interpolation blur in that crop.

**The three levers, in order of leverage:**

1. **Average over time.** If the jitter is independent frame to frame it falls
   as sqrt(N): 8 samples is 0.5 s and 3.27 -> 1.16 deg; 16 samples is 1 s and
   -> 0.82 deg. A dwell UI waits that long anyway, so it is free precision
   that the current live-cursor design throws away. **This only pays if the
   noise is independent** -- see `bin/fixate`.
2. **More real pixels on the iris**, via a narrower lens (Arducam M12 ~40 deg,
   roughly 2x linear iris resolution -- `PLAN.md` Path C already says this) or
   simply moving the camera closer. NOT via capture resolution.
3. **IR illumination**, which is what commercial trackers do and what removes
   the bright-light-in-the-eyes problem. Hardware project.

**`bin/fixate` is the measurement that picks between 1 and 2.** Stare at one
dot; it reports the scatter, then the sd of the mean of N consecutive samples
against the 1/sqrt(N) ideal, plus lag-1 autocorrelation. Independent jitter
means averaging works and nothing else is needed. Correlated drift means
averaging buys almost nothing and the answer is pixels. The two look identical
on screen. **Run this before changing the tracker or buying a lens.**

## Two display gotchas that cost a session

**Do not reboot with the monitor asleep.** The board's own DPMS puts it to
sleep, and a reboot from that state comes up with **EDID 0 bytes** — the
monitor never answers, so the driver offers only generic VESA modes
(640x480, 1024x768, 800x600) and X comes up at 640x480. Recovering it needs a
physical re-plug of the DisplayPort cable or a monitor power-cycle; there is
no software fix from the board side.

**Do not guess a modeline to work around it.** A forced 1920x1080 at a 173 MHz
pixel clock made the monitor say OUT OF RANGE and left the user with no
picture at all. If EDID is missing, drop to a mode the driver already offers
(`xrandr --output DP-1 --mode 1024x768`) and fix the EDID physically.

**`bin/talker` still hardcodes the screen size from config.toml.** It should
read the actual display size so a board that comes up at 1024x768 draws a
correct 3x2 rather than a broken one. Not done.

**OpenCV drawing is not an input event**, so X blanks a gaze demo mid-run --
gaze is not input as far as the idle timer is concerned. `spike/nosleep.py`
disables blanking for the life of a tool and restores the previous settings at
exit; it is wired into `talker`, `aim`, `ladder` and `yawcheck`.

**`pkill -f "bin/talker"` kills its own shell** when run over ssh, because the
pattern appears in that shell's command line. Use `bin/talk[e]r`.

## Maker-faire study — FIRST BATCH IS VOID. Read this before collecting again.

**2026-09-22: 334 throws across 12 sessions recorded NOTHING.** Every row has
`gaze: null`, `face_frac: 0.0`, flagged `no_gaze`. Kept in
`board_artifacts/study/` for the record; **do not analyse it**.

Cause: `GazeAim` stores its gaze source as `self.src`, and the study's
per-frame hook looked for `aim.source`. It got `None` and recorded empty rows
without complaint. Fixed, and the lookup now accepts either name.

**That was the THIRD silent collection failure in one evening** — the study
ran in mouse mode because `BFF_GAZE` was unset; the camera intrinsics resolved
to the wrong directory; and then this. Each produced a full session of
confident, useless rows, and none announced itself. `_study_selfcheck()` now
runs after calibration and prints either

    [study] gaze OK -- recorder sees a point at (x, y)

or a loud `*** NOT RECORDING GAZE: <reason> ***`. **Check that line before
letting anyone play.** It is the cheapest possible guard against spending a
faire morning collecting nothing.

## Maker-faire study — how to run it

`~/bunny/run_study.sh` (detached; log `/tmp/bff.log`, data
`~/bff_gaze_study.jsonl`). **275 rows collected 2026-09-22, not yet analysed.**

    python3 ~/bunny/analyse_study.py ~/bff_gaze_study.jsonl --filter

**The line to read is `ratio scatter/error`.** It decides the project's next
move and nothing else in the file matters as much:

- **> 0.7, jitter-dominated** -> averaging over a dwell cuts error by sqrt(N).
  0.5 s takes 3.27 deg to 1.16, free, no hardware.
- **< 0.7, bias/drift-dominated** -> averaging is a dead end and the answer is
  more pixels on the iris: a closer camera or the ~40 deg M12 lens
  (`PLAN.md` Path C).

**Analyse the existing 275 rows SEPARATELY from anything collected after
2026-09-22.** They were taken at a 0.85 s auto-carrot, which fires while the
eyes are still travelling to the next bunny -- those samples are saccades, not
fixations, and a saccade is exactly what the scatter test misreads as tracker
noise. The beat is now 4 s. Session headers record the settings, so the runs
can be told apart.

Also expect a high blink-exclusion rate in the last rows of that batch: the
subject was tired and said so. That is the flags working, not a fault, but it
is not representative of a fresh visitor.

## Faire kiosk: auto-login into a menu

Built 2026-09-23, **deployed and running 2026-09-24**. Auto-login works and
all three rows launch. What it lacked was any way *back* without a keyboard;
see § "the kiosk ran, and had no way out of anything".

    tools/setup_kiosk.sh            # dry run, shows what it would change
    tools/setup_kiosk.sh --apply    # autologin + autostart
    tools/setup_kiosk.sh --undo     # put it back

`bin/menu` is a fullscreen launcher with three rows:

| row | what it runs |
|---|---|
| Bunny Feeding Frenzy | the gaze study build (`BFF_GAZE_STUDY=1`) |
| T-Rex Talker — eyes | `bin/talker`, gaze aims, SPACE/ENTER/click speaks |
| T-Rex Talker — mouse | `bin/talker --mouse`, pointer only |

**Mouse AND keyboard both work; gaze deliberately does not.** The menu is what
you use when gaze is not calibrated yet, and a menu that needs working gaze to
escape is a trap. Arrows or 1–3 to choose, ENTER/SPACE/click to start.

**Quit is a chord (Q then Y), not a row** — a visitor cannot end the session
by clicking the wrong thing.

**Each activity is a child process**, so when it exits for any reason,
including a crash, the menu redraws. Nothing leaves a stranger at a terminal.

Deliberately NOT a systemd service replacing the desktop: the menu needs a
real X session (OpenCV windows, the cursor, `xset` for blanking), and a bare
service loses all of it. It also leaves the desktop reachable if the menu is
killed — at a faire a visitor facing a black screen is worse than one facing
a desktop.

**Both talkers already take mouse button, SPACE and ENTER** to speak a word:
`fire = k in (32, 13, 10) or mouse["click"]` in `bin/talker`. No change was
needed there.

**Leaving an activity is now mouse-only too**, which it was not on the day:
right/middle-click for the talker's home board, an `exit` chip on it, and an
`X` in the bunny game. The menu's own Q-then-Y quit is still a keyboard
chord — that is deliberate, it drops to the desktop and a visitor should not
find it.

## 2026-09-24: the kiosk ran, and had no way out of anything

The kiosk was deployed and auto-login works. Then every activity turned out
to be a **one-way trip for anyone without a keyboard**, which is the actual
faire configuration. All four holes are fixed; **none has been tested by
hand yet** — that is the first thing to do next session.

| was | now |
|---|---|
| talker **Back** cell did nothing | works |
| no way home from a talker submenu | **right- or middle-click**, any depth |
| talker exited on `q` only | small **`exit` chip**, top right of the HOME board |
| bunny game exited on ESCAPE only | small **`X`**, bottom right, every phase |

**The Back cell was a parsing bug, not a UI one.** The `.menu` format marks
the back cell with a BARE `back =` key -- an empty value whose PRESENCE is
the entire signal -- and names the destination separately as `[menu] back =
<file>`. `spike/menu.py` read neither, so Back arrived as a press with no
`sound=` and no `submenu=`: it highlighted, accepted a press, and fell
through to `voice.say()` with nothing to say. Parse that key by MEMBERSHIP;
a `.get()` there is the bug. The `b` key worked the whole time, which is
exactly why it reached the board.

**The trap that cost the most time: `cv2.WINDOW_GUI_EXPANDED` is ZERO.**
This OpenCV is built `GUI: QT5`. Passing a bare `cv2.WINDOW_NORMAL` to
`namedWindow` therefore selects the *expanded* Qt chrome, and Qt grabs
right-click for its own "Save image" popup -- a dialog that blocks the app
and needs a keyboard to dismiss. Both kiosk windows now pass
`WINDOW_NORMAL | WINDOW_GUI_NORMAL`. Nothing raises without it and no unit
test can click a mouse, so `test_kiosk_windows_disable_the_qt_context_menu`
asserts it in the source of both bins. **Check this first if right-click
ever stops working.**

**Every exit is guarded the same way, deliberately, so there is one habit:**

- **Mouse only, never gaze.** In the talker the chip takes a left-click and
  ignores dwell. In the game, gaze emits `"fire"` and only `"down"` reaches
  `_on_click`, so staring at the corner cannot close it. Do not "helpfully"
  route fire to either.
- **Two clicks.** First arms (turns red, reads `SURE?` / `SURE`), second
  within 4 s leaves, any other click disarms.
- **Small and cornered.** Gaze p95 is ~164 px, so a chip of that order in
  the corner is out of a visitor's reach and trivial for the operator's
  mouse. **That asymmetry IS the guard** -- enlarging either button to look
  friendlier hands the exit to the person in the chair.

**The game's white face-light border is OFF** (`GAZE_LIGHT_BORDER = 0`). It
predated the lamp, and the lamp measured 3.2x steadier -- far more than a
12 px rim of white could buy. Kept, not deleted: raise it and the frame
comes back if a booth ever loses the lamp. `GAZE_PLAY_BRIGHTEN = 24` is
**still on** and is the same idea; it is a candidate to go the same way.

**Two things that only showed up by looking at a rendered frame:** the
game's close button was first drawn *underneath* the carrot inventory, and
the talker's chip had to be checked against the grid at four screen sizes.
Neither errors. Render the frame headless and look at it --
`SDL_VIDEODRIVER=dummy` on the board for the game, `cv2.imwrite` for the
talker.

**A leak worth recognising:** a `timeout 10 python3 bin/talker ...` left two
processes alive **28 minutes later**, holding the display next to the
kiosk. `timeout` killed the wrapper, not the child. If that shape is in a
script it will recur at the faire.

## 2026-09-30: the gaze talker could not be used by gaze

Three faults, all found while capturing screenshots, all of the same family
as the Back button and the missing exits: **invisible to anyone testing with
a keyboard and a mouse in reach.**

**`--dwell` defaults to 0.0, and the kiosk was not passing it.** Selection
therefore needed SPACE, ENTER or a click. A visitor with neither hand nor
keyboard — the actual AAC case, the entire point of the project — could
highlight a word and never speak it. `bin/menu` now launches the eyes row
with `--dwell 1.2`; the mouse row stays click-only on purpose, because a
pointer rests where it was left and would speak whatever it is parked on.
**FIXED but NOT yet run from the menu by hand** — launching the eyes row
once confirms the path end to end.

I also misdiagnosed this first. Every captured frame logged `dwell=0.00`
and I said the 2 s capture interval was skipping past the dwell window. It
was not: there was no dwell to catch. **The log was right and the
explanation was wrong** — check what a default actually is before blaming
sampling.

**`light-locker` put a lock screen over the running talker.** `nosleep.py`
was only doing `xset s off` and `-dpms`, which that locker ignores — it runs
its own timer. On a kiosk with no keyboard this is unrecoverable: nobody can
type a password to get back, so the exhibit simply ends showing a login
prompt. **This is a live candidate for why Sunday captured nothing**,
alongside the boot failures. `nosleep.hold()` now SIGSTOPs light-locker,
xscreensaver, gnome-screensaver, mate-screensaver and xfce4-screensaver and
SIGCONTs them at exit — stopped rather than killed, so a desktop's locker is
not permanently disarmed.

**The de-identifier leaked on raw camera frames.** The pure-colour test that
rescues drawn annotations from the wipe also rescued a bright blue lamp glow
in the background: a saturated highlight is indistinguishable from a
saturated stroke. That rule only holds on frames that HAVE annotations, so
`tools/deidentify.py --raw` turns it off. **Use `--raw` on every plain
camera frame.**

## Head pointing: how to run it, and the two traps

Built 2026-09-30 to `head_track.md` (Drive, `claude/sip-n-puff/`, with
`headtrack.py` as the reference implementation beside it).

    bin/tagcheck                 # 20 s: is the tag seen, how big, how fast
    bin/headrange                # 35 s: 9-target map of the reachable field
    bin/talker --mode head       # calibrate (5 pts) then use the board
    bin/menu                     # row 4 does both, with --tag-id 2

**START WITH `bin/tagcheck`.** Every head-mode failure so far has looked
identical from the inside -- "calibration says my head is unstable" -- and
had a different cause each time: wrong tag id, then room lights off. Thirty
seconds of tagcheck names which.

**TRAP 1: the tag on this rig is id 2.** `head_track.md` specifies id 0 and
says 0-3 were printed. `tagcheck` reported **0% detection** and its advice
pointed at lighting, glare and distance -- all wrong. The fix was to sweep
all 27 ArUco dictionaries over ONE captured frame, which found it instantly.
**If detection is 0%, suspect the id before the optics.** Defaults now point
at id 2 everywhere.

**TRAP 2: a DARK ROOM reports itself as five unstable calibration points.**
MEASURED 2026-09-30: with the lights off, calibration collected **0 samples
on 4 of 5 points** and called them unstable -- blaming the head for not
holding still when the tag was never seen. Lights on, the tag is acquired in
**0.5 s**. `calibrate_head` now waits for five consecutive detections before
showing the first dot, so this says so out loud.

I misread this first, and the misreading is the lesson: a trial read 1% /
80% / 80% on the same dark screen and I called it the camera settling,
citing frame mean barely moving (13.9 -> 17.2) as proof light was not the
variable. The lights had been switched on mid-trial. **Frame mean could not
show it because the lamp lights the FACE, not the scene** -- the third time
this project has been fooled by a whole-frame statistic, after `gain` pinned
at its ceiling and face brightness failing to predict rim detection.

**TRAP 3: do NOT drop to 960x540 to chase frame rate**, whatever the spec
says. Measured: 1280x720 gives 19.0 fps camera-alone and **100%** detection;
960x540 gives 22.2 fps and **67%**, because the tag falls to ~5.5 px per cell
and the corners stop resolving. **Detection costs 0.9 fps** -- the shortfall
against the spec's 25 is the sensor and the MJPEG decode, not the tracker,
which is why `tagcheck` reports fps instead of gating on it.

**The reachable field is WIDE and SHALLOW.** `bin/headrange` maps it: nine
targets, detection + tag size + skew at each. MEASURED 2026-09-30: 100% at
all nine, skew never above 0.04 -- the tag does NOT tilt away when pointing
down, that suspicion is dead -- but the tag travels **102 px horizontally
and only 37 px vertically** across the whole screen. Against a ~3 px jitter
floor that is 11x margin per column on a 3-wide board and 6x per row on a
2-high one. **A denser head board should add COLUMNS, not rows.**

**Design decisions worth not re-litigating:**

- **In-process, not uinput.** The spec offers a uinput virtual mouse; `evdev`
  is not installed here and `/dev/uinput` is root-only, so that needs a
  package AND a udev rule. `bin/talker` already computes its own cursor from
  a feature source, so head mode is just another source. No packages, no
  udev, no root.
- **Affine, not the ridge polynomial.** Head-to-screen is near-linear: six
  parameters, five points over-determine them. Gaze needs ridge because 66
  parameters over 9 points fits noise; there is no such danger here.
- **Head mode loads NO backend.** No face mesh, no LiteRT, no threads.
- **A lost tag freezes the dwell, not just the pointer.** Holding the pointer
  alone would let the clock run out on the cell it was parked on and speak a
  word nobody asked for.
- **Calibration collects by SAMPLE COUNT (18), not by clock**, and judges
  jitter with a scaled MAD rather than a standard deviation. The spec's 0.7 s
  window assumes 30 fps; at 17 it gave exactly 8 samples and all five points
  failed their first attempt. **This change is UNMEASURED** -- the 5-of-5 run
  it replaces was already good. Worth a comparison run.

## Capturing screenshots without HDMI capture

`bin/talker --record DIR` writes the canvas straight from the render loop —
no screen-grab tool needed, and the board has none installed. Add
`--record-cam` for the matching camera frame at the same instant, and
`--record-every SEC` for unattended runs. **SIGUSR1 saves a frame
immediately**, which is how a capture gets triggered on a board with no
keyboard: `kill -USR1 $(pgrep -f "bin/talk[e]r")` over ssh.

`--trail N` draws the last N gaze samples as fading dots. That is the thing
a still frame otherwise cannot show: the gaze does not sit on a target, it
circles one.

Each saved frame logs its own state — `dwell=`, `hover=`, `spread=` — so the
frame worth keeping is picked from the log rather than by opening hundreds
of images. **`spread` is also the fastest calibration check there is:** a
few hundred px means it took, ~1900x1079 means it calibrated to an empty
chair.

Published shots live in `docs/`. The capture run that produced them also
reproduced the head-turn cliff live: trail spread went 136x483 px while the
subject faced the screen, then 1919x1079 once the head turned — the same
71% -> 5% collapse the faire data shows, in one sitting.

## The lamp WORKS — measured 2026-09-23, two instruments agree

It is **16 red LEDs plus one 850 nm IR LED** — a red illuminator, so the
IR-cut-filter objection mostly does not apply. Red passes it freely.

**Controlled A/B, four runs alternating on/off/on/off:**

| condition | runs (px) | pooled | 95% CI |
|---|---|---|---|
| lamp on | 83.4, 79.3 | **82.5 px (1.65°)** | [69.9, 99.4] |
| lamp off | 170.6, 317.9 | 267.5 px (5.35°) | [191.4, 322.4] |
| difference | | **+183.7 px** | [+105.0, +242.8] |

**3.2× steadier.** Run 3 (lamp on, LATER in the session) matched run 1, so the
effect tracks the lamp and not fatigue. `lamp_on` repeats agree to 5%;
`lamp_off` repeats differ by 86% — without the lamp the tracker is not just
worse, it is *unpredictable*.

**Reproduced in the game, a different instrument:** fixation scatter 26.7 →
15.0 px (−44%), time to acquire 11.3 → 8.7 s (−23%), valid throws 93% → 97%.

**What is NOT established: accuracy.** Offset-from-target overlapped
(235.8, 303.0 with vs 551.4, 297.0 without). Accuracy is dominated by
calibration quality, which varies more between sittings than the lamp varies
it. The claim is narrow: **steadier, yes; more accurate, unproven.**
Steadiness is what dwell selection consumes, so it is the useful half.

**USE THE LAMP AT THE FAIRE.** Also: `iris_contrast` (`bin/irprobe`) is the
metric that predicts this, not brightness — room light alone gave 7.70 where
room+lamp gave 15.11.

## How to run the A/B again (Thursday/Friday)

    bin/fixate --label lamp_on      # ~75 s: 9 cal dots + 20 fixations
    bin/fixate --label lamp_off
    ... ALTERNATE, at least twice each ...

It beeps before and after (`bin/beep`), bootstraps the DIFFERENCE, and prints
`REAL` or `NOT RESOLVED`. **Alternating is not optional** — a single on/off
pair cannot separate the lamp from the subject tiring, and the tool says so
when it sees one run of a label.

`bin/irprobe --label X` is the 8-second version: gain, R/G, face brightness,
iris contrast. No fixation needed. Note **gain is saturated at 109** in every
dim condition and is useless there; read iris contrast.

## Thursday: the 850 nm IR test — how to decide it

**The report is waiting for this result.** A pending section sits in the doc
(Artifact `65c40e0a-88fb-41ee-8e1c-fec67ced83f2`, after Lighting) reserved for
it. Once the A/B is run, fill that block rather than restructuring the doc.
The report is a Claude Doc and is edited through the Docs connector, never by
publishing files.

**Protocol, so the two runs are comparable.** Anything that differs between
them other than the lamp becomes the result:

1. Same seat, same distance, same room lights, back to back.
2. `bin/fixate --seconds 20 --label ir_off`
3. Switch the lamp on. Change NOTHING else.
4. `bin/fixate --seconds 20 --label ir_on`
5. It prints the comparison and appends to `board_artifacts/fixate.jsonl`.
6. Repeat both at least twice, alternating, so a drift in the subject over the
   session cannot masquerade as the lamp's effect.

Record the lamp's POSITION too: on-axis beside the lens gives a bright pupil
by retroreflection, off-axis gives a dark pupil with a glint. They are
different images and the landmark model may prefer either, so label them
(`ir_on_axis`, `ir_off_axis`) rather than lumping them together.

An 850 nm illuminator was ordered 2026-09-22 to brighten the pupils. Decide it
with `bin/fixate`, which now labels and A/Bs:

    bin/fixate --seconds 20 --label ir_off
    bin/fixate --seconds 20 --label ir_on

It appends to `board_artifacts/fixate.jsonl` and prints the comparison
immediately. **The number that decides it is FIXATION SCATTER, not
brightness** — the rim work already established that face brightness does not
predict detection (face spanned 91–152 while pose ranged 48–84% with no
ordering), and the same trap applies here. A brighter picture that does not
steady the gaze point has bought nothing.

**Two risks worth knowing before the light arrives**, both of which would show
up as "no change" rather than as an error:

1. **The C920 has an IR-cut filter**, designed to block exactly this
   wavelength. Some 850 nm leaks through — that is why IR LEDs look faintly
   red on a webcam — but expect far less illumination than the lamp's rating
   suggests. If Thursday shows almost no change in image brightness, that is
   the filter and not the lamp, and the fix is a camera without one (a NoIR
   module), not a brighter LED.
2. **This pipeline does not use pupils.** Commercial trackers do bright-pupil
   and corneal-glint tracking with dedicated algorithms. We use MediaPipe's
   face-mesh iris landmarks, trained on VISIBLE-LIGHT faces. Under heavy IR
   the image washes out and irises look pale, which could make those
   landmarks worse rather than better. Genuinely uncertain, which is why it is
   worth measuring rather than assuming in either direction.

Placement matters if it does work: **on-axis** (beside the lens) gives a
bright pupil by retroreflection, **off-axis** gives a dark pupil with a glint.
Try both; they are different images and the landmark model may prefer either.

## Still open, roughly in priority order

0. **Launch the head row from `bin/menu` once.** Head mode has only ever
   been started by hand with explicit flags. The menu row passes
   `--tag-id 2 --dwell 1.2`; confirm that path end to end. Same for the
   eyes row, which has the `--dwell` fix but has not been run from the menu.
0a. **Measure head pointing against the eye numbers properly.** Today's
   comparison was two sessions with different tasks. A controlled A/B --
   same targets, same duration, alternating -- would say what head pointing
   is actually worth, and it is the strongest result this project could
   still produce before the deadline. The `--dwell` fix is on the
   board but has only been run by launching `bin/talker` directly. One
   minute, and it is the path a visitor takes.
0b. **Test the four kiosk exits by hand** — 5 minutes, and nothing else on
   this list matters if a visitor can strand the booth. Talker: Back cell in
   Food & Drink, right-click home from a submenu, the `exit` chip (two
   clicks). Game: the `X`, bottom right (two clicks). All four were written
   2026-09-24 and **not one has been pressed by a human**.
1. **Repeat Gate 1c in good light.** 3 minutes, and it is what the whole
   schedule now rests on. The 3.27 deg run was at face brightness **55.4**
   against the **128.7** measured earlier the same evening; a dim iris is a
   noisy iris. One subject, one run, worst single point 15.73 deg against a
   p95 of 5.56, and 3.27 sits close to the 3.5 deg Path B/C boundary. **Do
   this before committing seven weeks to Path B.**
2. **Switch the spike to the linear model** and re-measure on a fresh run —
   the comparison above is a refit of data collected for poly2.
3. **The window/backlit test.** 10 minutes, needs daylight. `bin/lighttest
   window 40` with a window behind the subject. The one condition a faire
   will actually present and the only one untested.
4. **Yaw from mean axis ratio** — the one untried idea with a real argument
   behind it. Record the axis ratios; `bin/yawcheck` does not.
5. **`GAZE_HORIZONTAL_ONLY` for the game** — specified, never implemented, and
   now doubtful: the vertical axis was `r_y = 0.22` in the spike but the
   2026-09-19 bare-faced run gave `r_y = 0.755` vs `r_x = 0.563`, which
   reverses it. **Re-measure before acting on either number.**
6. Bare-face-mesh column of update.md's ladder table — never run.
7. Re-upload `DIGEST.md` to Drive / the claude.ai Project after any of the
   above lands. It is a snapshot, not a link. **Current: 2026-09-29**, Drive
   id `1hmITrRAye9SEDZUzc4vJG6_IosblVOpa`, in the `claude/sip-n-puff/unoq`
   folder (`14dd62Ji4FD4DmqHKwKH1Gudv-42MTLsO`). Superseded snapshots go to
   `unoq-gaze-spike ARCHIVE` (`1aWFUXOeGpNTzXl0Z_753VCpgFIlam_Ry`), renamed
   `SUPERSEDED <date> ... (do not use as current)` -- 09-21 and 09-23 are
   both there. The measurement report is a Claude Doc, not Drive:
   https://claude.ai/artifact/DZrdz44qiA5NHy175mNJed -- it carries the faire
   section and is updated alongside this file.

## Where we are right now

**Gate 1b is COMPLETE.** The crash happened seconds after it finished — all
results were already written to `RESULTS.md` and pushed to the board, so
**nothing was lost.**

| gate | what | status |
|---|---|---|
| 0 | `bin/probe` — platform, camera, controls, backend | **done**, exits 0 |
| 1a | `bin/facecheck` — backend geometry, focus sweep | **done**, 10/10 |
| 1b | `bin/bench` — fps | **done**, p50 18–25, p5 14.2 |
| soak | 45 min under combined load — gates 1c | **PASSED 2026-08-16** |
| 1c | `bin/calibrate` — angular error, target size | **7 runs** — 5.12° @20 clicks, **Path C** |

The 2026-08-09 soak did not pass (it was void — the camera node had moved, so
every bench died in ~1 s and the loop "finished" in 20 s looking like a pass).
The **2026-08-16 re-run passed properly**: both arms genuinely overlapping for
45 minutes, `inf=1` unbroken across 39 consecutive 60 s samples, `err=0`
throughout, temp 59–61 °C, no ping loss, and — the criterion that matters —
**no new `crash` entry in `last -x reboot`**; uptime spans the whole window.
The inference arm exited by completing its 2700 s, not by dying.

Evidence: `board_artifacts/soak_watch_2026-08-16.log` (the full poll) and
`board_artifacts/soak.log.2026-08-16`. See `board_artifacts/README.md`.

Note `soak.done` is absent for that run **because the bench arm was stopped
deliberately** once the inference arm finished — 18 of 30 runs — to free the
camera for `bin/facecheck`. That is not a failure; the 45 min window was
already complete.

The headline result so far: **MediaPipe cannot execute on this board** (SIGILL,
ARMv8.1 LSE atomics on an ARMv8.0 core). LiteRT is the primary and only
backend. See `RESULTS.md` § "The headline finding".

## Gate 1c — 7 runs. Run 7 is the only clean one.

Full analysis in `RESULTS.md` § "Gate 1c run 7". Short version:

**Runs 1-6 are confounded.** Both grids were presented in raster order, so
elapsed time was collinear with target y (**r = +0.981** calibration). Under
that, "head drifts over time" and "head follows the target down the screen" are
the same measurement. Order is now randomised (`--seed` saved with each run;
`--raster` only to reproduce the old ones). Confound after the fix: **-0.127**.

**Run 7, clean** — 25 cal + 26 val, chin rest, randomised, `ridge="auto"`:

| clicks | held-out mean | p95 |
|---|---|---|
| 0 | 8.22° | 16.54° |
| 3 | 6.11° | 12.02° |
| 8 | 5.58° | 10.29° |
| 20 | **5.12°** | **7.95°** |
| **chance** | **7.78°** | **11.94°** |

**Corrections — do not quote the old numbers:**

- `r_x = 0.997` was a confound artefact. Honest value **0.784**.
- "2.42° after rescaling" was inflated the same way, and fitted 2 params on 6
  points. Not a real figure.
- Vertical gaze is nearly absent: **`r_y` = 0.221**, slope 0.56.

**What IS established:** drift is real and measurable now that position is
decorrelated — r(time, `t_y`) = +0.854, and **r(time, error) = +0.565** over a
~3 min session. And online recalibration works directionally, 8.22° → 5.12°.

### Where this leaves the fork

**Path C on PLAN.md's criteria** (error > 3.5°): "do not build on this,
diagnose first". 20 clicks still plateau near 5°.

### Full-res ROI crop — TRIED, WORSE, REVERTED (run 8)

The obvious next lead was iris resolution, and `config.toml` already named the
fix. It was implemented (`litert_backend.detect(rgb, full=...)`) and measured.
**It made things worse and is reverted.**

| | run 7 (720p) | run 8 (1080p + crop) |
|---|---|---|
| iris radius | 8.3 px | **10.0 px** |
| **raw iris↔target corr x** | **0.902** | **0.664** |
| validation | 8.2° | **18.2°** |
| detection rate | 100% | **55%** |
| fps p50 | 23 | 14.8 |

The raw correlation is computed *before any fit*, so this is not ridge,
capacity or drift. **Why:** the landmark model is trained on ALIGNED faces, and
the ROI comes from the downscaled detection image — cropping from 1920
magnifies its centring error 3×, so the face lands mis-centred in the 256×256
input. Sharpness up, alignment down, and alignment wins.

**Do not retry without making the ROI itself more precise first** (detect at
full res, or refine the ROI with a second landmark pass). The `full=` parameter
is kept, tested and unused; plain `detect(rgb)` is byte-identical to before.

### Also found: config's seated distance is wrong

`bin/bench` reports **median face distance 701 mm**; `config.toml` says
`viewing_distance_mm = 584`. Every degree figure is therefore ~**17% too
large**. It changes no conclusion (Path C at 5.1° is Path C at 4.3°) but must
be fixed before publishing a number — sit at 584 mm, or re-measure `[screen]`.

### Auto-calibration design — see `AUTOCAL.md`

Written 2026-08-16 for the maker-faire / any-destination-machine goal. Core
proposal: split the mapping into `g_person` (eye geometry, ~4 params, moves
with the visitor) and `f_setup` (where the screen is relative to the camera,
fixed all day at a stand). Two offline experiments were run against the saved
`.npz` files:

- **A 4-parameter affine correction on 4 points ≈ a full 25-point refit**
  (7.83° vs 8.22°). Four points is what the four screen corners give you, and
  the corners need no software on the destination machine at all.
- **The 66-param polynomial does not transfer between sessions** — 49–168° raw,
  same person, same rig. No stored profile survives a session boundary.
- **Session-to-session feature noise is ~half the across-target signal spread.**
  This may be the real ceiling, not iris pixels or the model.

**Repeat-targets test (`bin/repeat`, new) ran 2026-08-18 and is INCONCLUSIVE.**
Raw iris SNR came out 0.45–0.68, which would mean a hardware ceiling — but the
subject sat at 442 mm rather than 730 mm and moved 6–9 mm between repeats, and
iris excursion *fell* 2–4x when closer seating should have raised it ~1.6x.
That is head-turning, not eye movement. `bin/repeat` now withholds its verdict
above 4 mm of head movement. **Redo on a chin rest at a fixed distance** — this
is the measurement that decides whether to keep improving calibration at all.

### So what is actually left to try

Ranked, now that resolution is ruled out:

1. **Fix the distance**, then re-run run 7's protocol so the degrees are real.
2. **A more precise ROI** — the run-8 failure says ROI placement, not pixel
   count, is what limits the landmark model here. That is the live lead.
3. **Accept ~5° and design for it** — an AAC grid of very large cells plus
   zoom-to-refine, which PLAN.md's Path B already contemplates for cursor work.
   At 5° the implied target is ~90 mm, so roughly a 3×2 grid on this screen.

### Running it — the mechanics that took a while to work out

```bash
# needs a monitor attached AND a real desktop session (not the lightdm greeter)
./hil raw 'cd ~/unoq-gaze-spike && DISPLAY=:0 ./bin/calibrate --points 25 --out cal_runN.npz'
```

- `bin/calibrate` opens a **fullscreen OpenCV window**; it cannot run headless,
  and a headless run would write a plausible-looking but meaningless `.npz`.
- The monitor must be the one `config.toml [screen]` describes: 1920x1080,
  338 × 190 mm, 584 mm. A different panel makes every degree wrong. `xrandr`
  reporting 345 × 195 mm is the right monitor (EDID rounding). Ignore
  `xdpyinfo`'s 509 × 286 mm — that is X's fake 96-DPI default.
- **DP hotplug is not detected; the board needs a reboot** with the monitor
  already plugged in. Confirm with
  `cat /sys/class/drm/card0-DP-1/status` → `connected`.
- After any reboot: governor resets to `schedutil` (`./hil perf`), and the
  camera node may move — the by-id path in `config.toml` absorbs that
  automatically now (it moved video2 → video0 on 2026-08-16 and nothing broke).
- **Disable screen blanking first** — the desktop blanks after 600 s and will
  black out mid-sitting (it did on 2026-08-16):
  `./hil raw 'DISPLAY=:0 xset s off -dpms'`. It does not persist across reboots.
- **Keep every run** (`--out cal_runN.npz`, then `./hil pull`). The
  without-recalibration arm is recordable only once, and each `.npz` carries the
  raw `aX`/`ay` so analysis can be redone without another sitting.

### Preconditions verified ready 2026-08-16

| precondition | state |
|---|---|
| governor | `performance` |
| App Lab / docker | both `inactive` |
| disk free | 3.3 G |
| monitor | DP-1 connected, 1920x1080 |
| desktop session | `arduino` on seat0 (X reachable over ssh as `DISPLAY=:0`) |
| lighting | `bin/probe` exits 0 → gain 0 (re-check on the day) |

Read the warning in `PLAN.md` § "Evening · First accuracy number" before
running it. In short:

> **Save the raw baseline before tuning anything.** The accuracy-over-time
> figure needs a "without online recalibration" arm, and that arm can only be
> recorded once — before anything is improved. Tune first and it is gone
> permanently.

Three sessions, keep every one. Sit at ~584 mm, as the user will actually sit.

The fps criterion already lands on **Path B** (`PLAN.md` § the Sunday-night
fork), touching Path A on good runs. **The fork now depends entirely on the
angular error Gate 1c produces.**

---

## Getting back to a working state

**To run the gaze-controlled game** (the most likely reason you are here):

```bash
# on the dev machine -- deploy, then run on the board
cd ~/claude/coder/games/bunny_feeding_frenzy
rsync -az --exclude='.git' --exclude='.venv' --exclude='awscliv2.zip' \
      --exclude='android' --exclude='ios' --exclude='aws' \
      --exclude='__pycache__' --exclude='*.pyc' --exclude='screenshots' \
      ./ arduino@10.42.0.250:~/bunny/

ssh arduino@10.42.0.250 'pkill -f main.py'          # NOT "python3 main.py" -- see GAZE.md
ssh arduino@10.42.0.250 'cd ~/bunny && DISPLAY=:0 BFF_GAZE=1 \
  BFF_GAZE_PATH=$HOME/unoq-gaze-spike BFF_GAZE_EXPOSURE=625 python3 -u main.py'
```

`pygame-ce 2.5.8` is installed on the board (aarch64 wheel, no source build).
The game prints `[gaze] ...` diagnostics to stdout — calibration quality, the
gaze/bunny offset, snap counts and feeds. Those lines are how every problem so
far was actually found; read them before changing anything.

To re-enter the Claude session for this project: **`~/claude/unoq.sh`** — cds
here and continues the most recent conversation (`--new` / `-n` anywhere in the
args forces a fresh one). Same pattern as the other project launchers in
`~/claude/`.

```bash
cd /home/trex/claude/unoQ/unoq-gaze-spike

pytest tests/ -q          # 90 tests, no hardware — sanity check the tree first
                          # last green: 2026-08-16, 90/90 in 0.18 s
                          # (85 + 5 new in tests/test_camera_device.py)
./hil check               # board identity, deps, camera, governor
./hil perf                # governor -> performance. Skip this and every fps
                          # number is meaningless. It boots as `schedutil`
                          # EVERY time (confirmed 2026-08-09 and -08-16) —
                          # this is not optional and it does not persist.
./hil push                # rsync tree -> board
```

If `./hil check` fails, work through **Board is unreachable** below.

### Before any benchmark or calibration run

```bash
./hil raw 'sudo systemctl stop arduino-app-lab docker' 2>/dev/null
./hil perf
```

App Lab and dockerd compete for RAM and CPU; leaving them up cost ~5 fps.

---

## Board is unreachable

Symptom: `ssh: connect to host 10.42.0.119 port 22: No route to host`.

The board is at **10.42.0.250** as of 2026-08-08 20:05 (it was .119 earlier the
same day — the lease DB was wiped by the host crash and it took a new address).
**Check `journalctl -b | grep DHCPACK` for the current one before assuming
either.** The `DHCPACK` line carries the hostname `uno-q`, which is how you
confirm it is the board and not some other device. User is `arduino`
(`.hil.env`, gitignored). The address is handed out by a NetworkManager
**shared** connection on this machine — profile name `direct-pi`, interface
`enp1s0`, host side `10.42.0.1/24`, dnsmasq DHCP pool `.10–.254`. The link dies
with the host, so unreachable-after-a-crash is expected and not a board fault.

### Diagnose without touching the board

Do these in order — they distinguish "board is off" from "board is powered but
hung", which look identical to `ping`.

```bash
ip a | grep 10.42.0                  # host side up? expect 10.42.0.1/24
ethtool enp1s0 | grep -i 'link detected'   # PHY negotiated? = something is powered
cat /sys/class/net/enp1s0/statistics/rx_packets   # has ANYTHING come back?

# the useful one — did the board ever ask for an address?
journalctl -b | grep -iE 'enp1s0.*carrier|DHCPDISCOVER|DHCPOFFER|DHCPACK'
```

Reading it:

| what you see | means |
|---|---|
| link detected **no** | board unpowered, or cable/dock out |
| link **yes**, `rx_packets` climbing, `DHCPACK` | it's up — find the address below |
| link **yes**, `rx_packets` ~0, `DHCPDISCOVER` but no `DHCPACK` | **board powered but not completing boot** — see below |
| repeated `carrier: link connected` every ~20 s | link flapping — see the caveat directly below |

**Carrier flapping alone is NOT the fault — a normal boot does it too.**
Observed 2026-08-16 on a healthy power-on: carrier connected 5 times over
~100 s (14:15:03 → 14:16:05) with `rx_packets` stuck at 3 and no DHCP at all,
which looks exactly like the failure signature. It then took `.250` and
answered ping at **14:16:41**. So give a fresh power-on **~2 minutes** before
concluding anything.

The discriminator is what happens *after* the flapping stops:

| after ~2 min | verdict |
|---|---|
| `DHCPACK` + ping answers | healthy boot — the flapping was normal |
| flapping continues, no `DHCPACK` ever | the fault |
| one `DHCPDISCOVER`, offer, then silence | the fault (the 17:13 / 17:43 signature) |

`arping` is not installed on this machine; don't reach for it.

To find the board when it *is* up but the address moved:

```bash
journalctl -b | grep DHCPACK          # authoritative — what it actually took
for i in $(seq 2 254); do (ping -c1 -W1 10.42.0.$i >/dev/null 2>&1 \
  && echo "UP 10.42.0.$i") & done; wait
./hil init                            # rewrite .hil.env with the new address
```

### Observed 2026-08-08 17:13 and 17:43 — dies ~26 s into boot, REPRODUCIBLE

Recorded because this is the signature to recognise next time:

- PHY negotiated **100 Mb/s full duplex, link detected yes** — the board had
  power.
- `carrier: link connected` fired **7 times in 2 minutes** (17:13:07 → 17:15:10),
  then went quiet.
- **One** `DHCPDISCOVER` from `00:e0:6b:67:24:6a`, offered `10.42.0.250` — and
  **no `DHCPREQUEST`, no `DHCPACK`.** It never took the address.
- `rx_packets = 1` against `tx_packets = 4290`. Silent for 16+ minutes while
  holding the link up. Nothing answered on the whole `/24`.

A DHCP client that discovers, gets an offer, and then dies before requesting is
a stack that started and stopped — not a board that was never on. Combined with
the carrier flapping, the leading suspicion is **power**: the board requests
**5 V @ 3 A**, and undervoltage on this hardware presents as random instability
that looks exactly like a software bug.

**A power cycle at 17:43 reproduced it exactly** — carrier up, DISCOVER +26 s,
offer, then dead. Same as 17:13. This is the **third occurrence** of the fault
first logged in `REPLICATION.md` (the original was a drop-off after ~20 min
uptime); it is no longer intermittent, it happens every boot.

`Link detected: yes` proves nothing here — **the Ethernet PHY is on the powered
hub, not the board.** Only a `DHCPACK` or a ping reply proves the board is
alive.

### The discriminating test — do this before anything else

`REPLICATION.md`'s standing top candidate is undervoltage, and boot is exactly
when draw peaks (eMMC + 4 cores + USB enumeration + camera spin-up at once).
Rule power in or out first, because every other hypothesis is more expensive to
test:

1. **Is the hub powered from the PD brick, and not from the board?** This is the
   specific arrangement `REPLICATION.md` calls out. If the board is feeding the
   hub, the camera's inrush lands on the board's own rail.
2. **Unplug the camera, then power-cycle.** The cleanest discriminator: if the
   board boots and stays up without the camera, the supply cannot carry the
   full load and no amount of debugging the software will help.
3. **Barrel jack, 7–24 V, hub removed.** `PLAN.md` already specifies this for the
   deployed build. Pulling that decision forward is simultaneously the
   reliability fix, the replication fix (fewer parts, no PD negotiation) and a
   cheaper BOM.

If it survives all three, the network has nothing further to offer — get a
serial console on the UNO Q. (`/dev/ttyACM0` is the Fruit Jam breath board,
*not* the UNO Q; the UNO Q presents no USB gadget at all, see
`REPLICATION.md`.)

### Recovered 2026-08-08 19:55 — cause NOT established

After a re-power at 19:54:52 the board booted normally and took `.250`:

```
19:54:52  carrier DROPPED (activated -> unavailable)   <- new: the hub lost power
19:55:49  carrier: link connected
19:55:55  DHCPDISCOVER / DHCPOFFER / DHCPACK 10.42.0.250 ... uno-q
```

The carrier genuinely going *down* first is the difference from the two failed
attempts, where the hub stayed powered throughout and only the board was dead.

**Board-side evidence after recovery:**

- No undervoltage or thermal messages in `dmesg`. This is **not** exculpatory:
  this SoC does not emit Pi-style undervoltage warnings at all, so their absence
  says nothing.
- `last -x reboot` shows **every prior session ending in `crash`** — no clean
  shutdown record anywhere. Consistent with power being pulled every time.
- `/sys/fs/pstore` empty — no kernel panic remnant.
- One USB reset of the C920 at t+21 s during boot.

**USB topology (matters for the power argument):**

```
root_hub -> hub(4p) -+- C920            (uvcvideo, 480M)
                     `- hub(4p) -- r8152 USB Ethernet
```

The Ethernet is a **USB adapter downstream of the externally-powered hub**. That
is exactly why `Link detected: yes` persisted while the board was dead, and why
carrier is worthless as a liveness signal — only `DHCPACK` or a ping reply is.

**The fault is survived, not diagnosed.** Three failures then one success, with
no board-side error recorded, means the next occurrence is a matter of time. Do
not treat the board as trustworthy until the power arrangement is settled.

### `gain` is a light meter — RESOLVED 2026-08-16, but read this before 1c

**In a dim room `bin/probe` fails with `BAD gain want=0 got=109`. Turn the
lights on and it reads `want=0 got=0`.** Confirmed both directions:

| room | runs | `gain` reads |
|---|---|---|
| dim (~16:00, ambient) | 3 | **109**, every time |
| bright | 2 | **0**, `PASS all controls survived stream start`, probe exits 0 |

So the C920 drives gain itself in low light **even with `auto_exposure` reading
`1 (Manual Mode)` and `exposure_time_absolute` holding at 156**. It is not a
control-ordering bug and `warmup_frames = 8` is fine — do not raise it.

It was also **not** the `camera.py` symlink change:
`os.path.realpath("/dev/video2")` returns `/dev/video2`, so `v4l2-ctl` received
a byte-identical string, and six other controls on that same path stuck.

**What this means for the measurements, which is the real point:**

- `gain` is now a usable **read-out of whether the room is bright enough**. A
  failing probe is the camera telling you the light is too low, not a fault.
  **Run `bin/probe` as the light check before any sitting.**
- Everything in RESULTS.md — the focus sweep, iris sharpness, Gate 1b — was
  measured at gain 0, i.e. bright. Match that or the comparison is broken.
- **Record the Gate 1c baseline in bright light**, and write the condition down.
  It can only be recorded once.
- The open "three lighting conditions" item (bright / dim / backlit) is now
  partly characterised in advance: the dim arm will run at raised gain, so it
  measures *sensor noise plus* whatever the lighting does to the landmarks. Do
  not attribute the whole degradation to the lighting.

### The camera node moves between boots — check it before every run

**Found 2026-08-16, after it silently destroyed a soak run.** `config.toml` had
`device = "/dev/video0"`. On that boot `/dev/video0` was the **Qualcomm Venus
video decoder**, and the C920 was on **`/dev/video2`**. It had genuinely been
video0 on 2026-08-08 — the registration order is a boot race between the
platform codec driver and USB enumeration.

The failure is nasty because it is *fast and quiet*: every `bin/bench` died
instantly with `RuntimeError: could not open /dev/video0`, so all 15 soak
iterations "completed" in about 20 seconds and the loop wrote
`soak.done = FINISHED`. From the outside that is indistinguishable from a pass.
**This is why `err=` exists in `bin/soak-status`.**

Check before any long run:

```bash
./hil raw 'ls -l /dev/v4l/by-id/'
# usb-046d_HD_Pro_Webcam_C920_1DB6303F-video-index0 -> ../../video2
```

Take the `video-index0` target — index1 is the C920's metadata node, not video.

**FIXED 2026-08-16 — `config.toml` now holds the by-id path.** `camera.py` used
to do `int(re.sub(r"\D", "", self.device) or 0)`, scraping digits out of the
path and opening by index, so a by-id name collapsed to the garbage index
**4046920163030**. It now:

- resolves absolute paths with `os.path.realpath()` in `__init__`, once, so the
  capture index and the `v4l2-ctl` control calls cannot land on different nodes
  (bare integer device strings are left alone — `realpath("2")` would give
  `$CWD/2`);
- matches `/dev/videoN` strictly in `open()` and raises naming **both** the
  requested and resolved paths, instead of silently opening the wrong camera.

Covered by `tests/test_camera_device.py` (5 tests, no hardware — the path check
runs before cv2 is touched). **Still wants a `bin/facecheck` run** to re-verify
against a real face, since `camera.py` is a hardware-verified file: it was
edited during a soak and has only been smoke-tested by `bin/bench` since.

If the camera is ever swapped, the serial in `config.toml` stops matching and
you get a named error — update it from `ls -l /dev/v4l/by-id/`.

### Board clock is unreliable — and the drift is getting worse

`last` reports every boot as the same wall-clock time and the board's clock ran
~7 h off the host. There is no usable RTC. Be careful reading board-side
timestamps, and be aware `rsync` mtime comparisons in `./hil push` are being
made against a skewed clock.

**2026-08-16: the board booted believing it was Aug 10** — roughly **six days**
behind the host, up from 7 hours. Treat every board-side date as fiction.
*Relative* gaps between two board-written files within one boot are still usable
(same clock), which is all the soak analysis above relies on; absolute times and
host-to-board comparisons are not.

**`uptime` is affected too, not just dates.** On 2026-08-16 the board reported
`up 0 min` at 14:17 host time and `up 45 minutes` at 14:25 — eight host minutes
apart. Do not use board uptime to judge how long a soak has been running; time
it from the host.

If a run's ordering ever matters, stamp it from the host side rather than
trusting the board:

```bash
./hil raw 'date'; date        # board time, then host time — expect a large gap
```

### Likely cause: hub power — CONFIRMED in hindsight (see 2026-09-16 update)

**Re-cabling the hub's power brought it back first try** on 2026-08-08 20:05.
The hub had been fed from the board, so the C920's inrush landed on the board's
own rail. This is candidate 1 in `REPLICATION.md` and the arrangement it already
warned about.

That looked like a fix. **It was not.** Crash-terminated boots recorded *after*
the re-cabling:

| when (board clock) | count | context |
|---|---|---|
| Aug 8 22:26–22:27 | **8** | after that session ended |
| Aug 9 04:12–04:16 | **3** | during the soak, as the inference arm died |
| Aug 10 22:51 (= Aug 16 host) | **3** | this power-on, before it settled |

**UPDATE 2026-09-16 — the fault appears genuinely fixed.** `last -x reboot`
now records a **clean shutdown** after a **14-day 22-hour** uptime
(`Sep 2 02:46 - 01:39 (14+22:53)`), the first clean shutdown this board has
ever logged. A commanded reset on 2026-09-16 came back in **85 seconds** with
no carrier flapping and no crash entries. That is the hub re-cabling of
2026-08-08 20:05 vindicated, two weeks after the fact.

Treat the board as trustworthy again — but keep the diagnostics above: the
failure signature is recorded and cheap to re-check if it ever returns.

Historical record below, kept because it is how the fault was diagnosed.

Before that, `last -x reboot` had **never** recorded a clean shutdown. The
re-cabling may still have helped — the board now usually comes back on its own,
which it did not before — but the underlying instability was live, not solved.
Did not plan around it being fixed, and did not spend an irreplaceable
calibration baseline on the assumption.

The three discriminating tests above (hub off the PD brick, camera unplugged,
barrel jack 7–24 V) are **still the open action**, and the barrel-jack option is
looking less like a nice-to-have.

### The soak test — 2026-08-16 PASSED; the 2026-08-09 run below was VOID

**Current status: PASSED.** The re-run on 2026-08-16 held both arms overlapping
for 45 minutes with no reboot — details in the status table at the top of this
file and in `RESULTS.md`. Gate 1c is not blocked.

The rest of this section is the **2026-08-09 post-mortem**, kept because it is
the record of how a dead run impersonated a passing one. Evidence in
`board_artifacts/` (see "What lives where").

#### Post-mortem of the void 2026-08-09 run

What the artifacts actually show:

| arm | planned | achieved |
|---|---|---|
| `bench` loop ×15 | 15 runs | **15/15 complete**, `soak.done` = `FINISHED` |
| all-core inference | 2700 s | **656 s / 22000 invokes — stops mid-log** |

**The two arms never overlapped.** `soak.log` and `soak.done` were both last
written at **03:43:29**. `load.log` was last written at **04:13:45** after 656 s
of progress, so it started at **~04:02:49** — nineteen minutes *after* the bench
arm had already finished. The whole point of the soak is camera + pipeline +
all-four-cores drawing at once; that condition was never created. Running the
two arms back-to-back tests neither.

**And the board crash-looped right at the end of it.** `last -x reboot` shows
boots at 04:12, 04:15 and 04:16 all ending in `crash` — bracketing `load.log`'s
final write at 04:13:45. The inference arm did not exit cleanly; it was killed.
(An earlier cluster of **8** crash boots sits at Aug 8 22:26–22:27, after the
previous session ended.)

So the one arm that stresses power is exactly the arm that died, at ~24% of its
planned duration. That is the opposite of a pass.

**Caveat, and it is a real one:** every timestamp above comes from the board's
own clock, which is badly unreliable (see "Board clock"). Relative gaps between
board-written files are still meaningful — same clock, same boot — but do not
try to align them against host-side wall time.

#### Re-running it correctly

**Nobody needs to be seated for this** — and note an empty-room `bench` is NOT
sufficient load on its own: with no face, `landmark_ms` is 0.0 and the expensive
stage never runs. (The 2026-08-09 run bears this out — 14 of its 15 runs sat at
p50 ≈ 14.9 fps, the no-face path, well under the Gate 1b p50 of 18–25. Do not
read soak fps as a bench result.) That is *why* the inference arm exists, and
why it has to run **at the same time**, not after:

```bash
rm -f soak.log soak.done load.log       # stale logs are how the last run got misread
./hil perf                              # boots as schedutil EVERY time — see below
./hil raw 'sudo systemctl stop arduino-app-lab docker' 2>/dev/null

# start the all-core inference load FIRST, so it is definitely up before bench
./hil run 'setsid nohup python3 -u -c "
import numpy as np, time
from ai_edge_litert.interpreter import Interpreter
it=Interpreter(model_path=\"models/bundle/face_landmarks_detector.tflite\",num_threads=4)
it.allocate_tensors(); d=it.get_input_details()[0]
x=np.random.rand(*d[\"shape\"]).astype(d[\"dtype\"])
t0=time.time()
while time.time()-t0 < 2700: it.set_tensor(d[\"index\"],x); it.invoke()
" > load.log 2>&1 </dev/null &'

# then camera + pipeline load, in the same window
./hil run 'setsid nohup bash -c "for i in \$(seq 1 15); do ./bin/bench -n 1500 \
    >> soak.log 2>&1; done; echo FINISHED >> soak.done" >/dev/null 2>&1 </dev/null &'
```

**Verify both are actually running before you walk away** — this is the step
whose absence invalidated the 2026-08-09 run. Use `bin/soak-status`, which
exists precisely because inline `$(...)` over `hil raw` gets mangled by the ssh
quoting layers and returns a mangled line that reads like a healthy zero:

```bash
./hil raw 'cd ~/unoq-gaze-spike && ./bin/soak-status'
# inf=1 bench=2 load=0s soakKB=3 done=no err=0 tempC=59
```

Poll it every 60 s from the host for the whole window. What each field must do:

| field | healthy | meaning if not |
|---|---|---|
| `inf=1` | exactly 1, whole window | 0 = inference arm died — **that is a fail** |
| `bench>=1` | 1–2 | 0 before `done=FINISHED` = bench arm died |
| `err=0` | **must stay 0** | nonzero = camera failing; see "The camera node moves" |
| `soakKB` | climbing | static = bench producing nothing |
| `tempC` | ~59 stable | climbing hard = thermal, not power |

**`load=` will read `0s` and that is expected.** The inference command above has
no `print` in its loop, so `load.log` only ever gets the XNNPACK banner. Do not
use it as a liveness signal — `inf=` from a 60 s poll is strictly better
evidence anyway, because it samples continuously instead of trusting one
timestamp. (The 656 s progress lines in the 2026-08-09 `load.log` therefore came
from some *augmented* version of this command, not the one recorded here. The
evidence stands; the command as documented would not reproduce those lines.)

The original fault appeared after ~20 min of uptime, so a pass needs **at least
30–45 minutes with both arms overlapping**.

A pass is: `inf=1` unbroken across the whole window, `err=0` throughout,
`soak.done` = `FINISHED`, **and** `last -x reboot` showing no new `crash` entry
across it.

**Do not run Gate 1c until this soak passes.** A brown-out partway through
calibration corrupts the one baseline that can only ever be recorded once.

---

## What lives where

| file | what it is |
|---|---|
| `DIGEST.md` | **portable** ~8 KB summary for a context that cannot see this repo (claude.ai project knowledge, a fresh chat, a collaborator). Keep it in sync when a finding lands. |
| `CLAUDE.md` | load-bearing decisions. Read before proposing changes. |
| `PLAN.md` | the schedule, the gates, the Sunday-night fork |
| `RESULTS.md` | every measurement, written as it arrives |
| `REPLICATION.md` | how to rebuild this board from scratch |
| `RESTART.md` | this file — session state and recovery |
| `AUTOCAL.md` | auto-calibration design for deployment; B/C results |
| `GLASSES.md` | glasses-rim fiducial: decision, accuracy, hardware findings |
| `bin/fixate` | **measures WHY it is jumpy** — fixation scatter, whether averaging helps (sd of block means vs 1/sqrt(N)), lag-1 autocorrelation. Run before changing trackers or buying a lens. |
| `bin/talker` | **T-Rex Talker 3.0 as a gaze demo** — 3x2 AAC board, gaze aims and SPACE/ENTER speaks. Reads the real `.menu` files and plays the device's own clips. Logs offset-from-cell-centre on every selection, so it is a test and not a toy. |
| `bin/aim` | **live view on the board's monitor** — aim the camera, tune booth lighting, watch BOARD/GLASSES lock lamps. Start here at any sitting. |
| `bin/ladder` | distance ladder with on-screen guidance; auto-captures once in tolerance AND locked |
| `bin/yawcheck` | rim yaw vs board yaw; board goes FLAT ON THE FOREHEAD so it rotates with the head |
| `bin/lighttest` | named lighting condition -> `board_artifacts/lighttest.jsonl` |
| `bin/boardrim` | paired board-vs-rim distance, the first version of the ladder |
| `bin/rimcheck` | older contour-based rim finder. **Superseded** by `find_rims_hough`; kept for the rig-measuring mode. |
| `bin/repeat` | within-session repeatability (the sensor-ceiling test) |
| `bin/live` | standalone gaze cursor on the board's monitor |
| `tools/hcheck.py` | one frame: every Hough candidate, its annulus ratio, what got chosen and why. **The first thing to run when the glasses will not lock.** |
| `tools/rimpair.py` | which `find_rims` stage kills the pair; `[close_px] [gray\|maxgrad]` |
| `tools/rimedge.py` | colour \| max_gradient \| Canny panels around one rim |
| **the game** | `~/claude/coder/games/bunny_feeding_frenzy` — see its `GAZE.md` |
| `config.toml` | tuned values, each with a MEASURED comment saying why |
| `hil` | dev-machine driver for board runs; `.hil.env` holds the address |

**Pulled to the dev machine 2026-08-16** into `board_artifacts/` — no longer
board-only: `bench_baseline.json` (the pre-optimisation truth, 11.5 fps),
`bench_tracked.json`, `bench_optimised.json`, `bench_final.json`, plus the soak
evidence `soak.log`, `soak.done`, `load.log`.

**Still board-only:** `ref_frames.npz` (44 reference frames from the focus
sweep, 39 MB, so backend changes can be re-checked offline without a sitting).
Pull it before any long session:

```bash
./hil pull ref_frames.npz board_artifacts/ref_frames.npz
```

The eMMC has not been imaged yet and the whole replication plan depends on being
able to image it, so treat anything that exists only on the board as at risk —
this board has crash-looped repeatedly.

## Config values that were measured, not guessed

Do not "clean these up" — each one cost a measurement. The reasoning is in
`RESULTS.md`; the short version:

- `width = 1280` — 720p beats 1080p; the 1080p pixels were discarded before
  anything used them, while their MJPEG decode cost was paid every frame.
- `input_size = 1280` — **no downscale at all.** Both models have fixed input
  sizes (128 detector, 256 landmark), so downscaling first buys no speed and
  only discards detail before the 256 crop.
- `num_threads = 3` — four threads on four cores starved the MJPEG decode in
  the capture thread.
- `exposure = 156` — the C920 quantises exposure to EV stops *while streaming*.
  250 was silently running at 156 anyway.
- `focus_absolute = 30` — peak iris sharpness, 5.4× better than the far end.
- `[calibration] points = 25` (was 9) — 66 parameters cannot be fitted from 9
  points; measured 8.4 deg at 9 against 2.34 at 25 on the same session. NOTE
  this matters only while the spike still defaults to the degree-2 model; with
  the linear model 9 points gives 3.49 deg and the long grid is not worth it.
- `[screen] viewing_distance_mm = 504` (was a stale 584) — every angular error
  scales with it, so 584 inflated every degree figure by 16%. **Re-measure it
  every sitting.**
- `[frame_rig] rim_exposure = 312`, `rim_gain = 192` — **rim detection needs
  its own exposure.** `[camera] exposure = 156, gain = 0` is a *gaze* setting
  (short, so a saccade does not smear) and left the face at mean 20 with the
  rim edges under the noise. The trap is that exposure 1250 also *reads* as
  well exposed (face mean 113) and is worse than useless: 125 ms smears the
  rim and the lens detected at 156 vanishes entirely. **Brighter and blinder
  at once. Fix it with gain, not time.**
- `[frame_rig] separation_mm = 61.5` — measured, and **not** the 67–75 mm
  predicted from the 137 mm frame width; that prediction was 15.4% high. The
  71.0 placeholder made the pair test hunt for a separation/radius of 2.84
  when the truth is 2.46, so it scored every genuine rim pair as a poor match.
  Measured twice over the two inner circles so it checks itself (closest
  inside 18 mm, farthest 105 mm → inner_d 43.5, sep 61.5 from both).
- `[frame_rig] max_residual = 0.06`, `close_px = 0` — see the four silent bugs
  above. Neither is a taste call; both were measured.

## Known dead ends — don't re-derive these

- **MediaPipe will never run here.** Don't test it by importing; `import
  mediapipe` succeeds and the process dies later. Use
  `backends.mediapipe_runs()`, which smoke-tests in a subprocess — a SIGILL
  cannot be caught with `try/except`.
- **p5 ≥ 15 fps is unmeetable**, not merely unmet. 15.0 fps is exactly two
  camera frame periods, and the landmark model alone costs 36–37 ms, above the
  33.3 ms period. No thread count, resolution, or input size moved p5 off
  14.1–14.4. Report it as a camera-quantisation tail, not a compute stall.
- **Camera controls go on AFTER stream start.** The C920 resets UVC controls at
  `VIDIOC_STREAMON`, silently.
- **Rim yaw from the depth difference is noise-limited, not mis-tuned.** 2.2 px
  of signal at 20° against 4.2 px of fit noise at 570 mm. Do not re-attempt it
  by filtering, seeding or smoothing; the information is not there. The only
  live idea is the mean axis ratio (see above).
- **`findContours` will not find a rim on a real face.** Broken into arcs and
  fused with brow/hair. Do not go back to it, and do not "fix" it with
  morphological closing — closing is what destroys the annulus.
- **The UNO Q image has no audio player and no TTS.** No mpg123, ffplay, mpv,
  espeak or spd-say. `pygame-ce` is present (the bunny game needs it) and its
  mixer opens at 44100/-16/2, so play audio through `pygame.mixer` rather than
  shelling out. A demo that needs `apt` on a faire morning is a demo that does
  not run.
- **Do not judge booth lighting by face brightness.** It does not predict
  detection: face 91–152 across runs, pose 48–84%, no ordering. Judge it by
  whether the GLASSES lamp in `bin/aim` stays green.
- **Never judge a calibration by its training error.** The two worst-fitting
  runs of 2026-09-21 reported 0.16 and 0.40 deg training error and 9.3 and
  12.9 deg validation. The worse the overfit, the better it looks from inside.
- **Do not choose the ridge by sweeping it against the validation set.** That
  is what the held-out set exists to prevent, and it produced two
  attractive-looking numbers (5.63, 2.91 deg) that are not accuracy. Selection
  must use training data only.
- **Degree-2 has never beaten linear on real data.** 7 parameters beat 66 at
  every point count tried. Do not reach for more model before more light, more
  points, or a better seating distance.
