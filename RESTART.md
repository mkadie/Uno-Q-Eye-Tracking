# RESTART — read this first after a crash or power loss

Last updated: **2026-09-16** — board reset cleanly (85 s, no crash). **The
power fault looks fixed**: a clean shutdown after 14d22h uptime, the first this
board has ever logged. See "hub power".

After this reset: governor back to `schedutil` (run `./hil perf`), camera moved
`video0 -> video2` (the by-id path in `config.toml` absorbed it, as designed),
monitor still detected, `bin/probe` exits 0 with `gain = 0`.

**UPDATE 2026-09-19 PROCESSED** (`/home/trex/claude/docs/update.md`). The
glasses are now calipered — outer 50.0 mm, inner 44.0 mm — which supersedes
the photo-derived 23.5 mm radius and explains the hardware run: the detector
had been fitting the two rim edges MERGED at the midline. `ring_pair()`,
`spike/intrinsics.py`, `spike/marker_board.py`, `spike/rig_geometry.py` and
`tools/calibrate_camera.py` are all in. Suite **145**.

**The two things that gate everything else, neither done:**

1. **Run `tools/calibrate_camera.py`.** Until `camera_intrinsics.json` exists,
   every distance is proportionally wrong by however far this C920 differs
   from its spec sheet. Target RMS < 0.5 px, and `fx`/`fy` within 2% or the
   capture did not tilt enough.
2. **Caliper the centre-to-centre separation**, ten pairs, record the spread.
   Expected 67–75 mm. Distance testing does NOT wait on this.

Then the experiment in `update.md` §4: the distance ladder at 450–700 mm with
all three estimators on the same frames. §4.4 says the one that matters most
is **bare-faced `bin/calibrate`** — it needs none of the fiducial work.

**THE PROJECT HAS PIVOTED TWICE since Gate 1c.** In order:

1. **Glasses fiducial** (`GLASSES.md`) — 6-DOF head pose from the circular rims
   of costume glasses. Geometry verified to sub-mm/sub-degree on synthetic
   ground truth; real-rim detection works only intermittently and the black
   frames are the worst case. Coloured frames were due 2026-09-17.
2. **Bunny Feeding Frenzy driven by gaze** — the game now calibrates and plays
   by eye on this board. See `/home/trex/claude/coder/games/bunny_feeding_frenzy/GAZE.md`,
   which is the authoritative doc for that work. **Read it before touching the
   game.** The board runs it from `~/bunny`.

**The single most important open finding, from playing the game:** the
VERTICAL gaze axis is unusable. In play the aim pins to the bottom of the
screen in one session and the top in the next — arbitrary, not drifting —
which matches the spike's own `r_y = 0.22` against `r_x = 0.78–0.90`. The fix
that follows from the measurement is to steer with gaze-x only and pin y to
the target band; it is specified but NOT implemented. Do that before any more
smoothing or calibration work.

**GATE 1c — run 7 is the first CLEAN measurement; runs 1-6 were confounded.**
Both grids were presented in raster order, making elapsed time collinear with
target y (r = +0.98), which inflated every head-pose/time correlation. Order is
now randomised. Clean numbers: **8.22° at 0 clicks (chance is 7.78°), falling
to 5.12° mean / 7.95° p95 by 20 online clicks.** Online recalibration works
*directionally* but plateaus around 5°. **On PLAN.md's criteria that is
Path C — diagnose, do not build.** Best remaining lead: iris resolution
(8.3 px at 720p vs 13.2 px at 1080p). See "Gate 1c" below.

**`bin/probe` exits 0 in bright light and fails on `gain` in a dim room** — the
C920 raises gain itself when the light is low. That makes probe your light
check: run it before any sitting, and record the Gate 1c baseline bright. See
"`gain` is a light meter".

This file exists because the dev machine has crashed mid-session more than
once. It records what is done, what is next, and the exact commands to get
back to a working state. Keep it updated at the end of every working session
and after every gate.

---

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
| `CLAUDE.md` | load-bearing decisions. Read before proposing changes. |
| `PLAN.md` | the schedule, the gates, the Sunday-night fork |
| `RESULTS.md` | every measurement, written as it arrives |
| `REPLICATION.md` | how to rebuild this board from scratch |
| `RESTART.md` | this file — session state and recovery |
| `AUTOCAL.md` | auto-calibration design for deployment; B/C results |
| `GLASSES.md` | glasses-rim fiducial: decision, accuracy, hardware findings |
| `bin/rimcheck` | find real rims on a real camera; also measures the rig |
| `bin/repeat` | within-session repeatability (the sensor-ceiling test) |
| `bin/live` | standalone gaze cursor on the board's monitor |
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
