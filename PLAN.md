# Front-loaded build plan

**Written:** Fri 7 Aug 2026, equipment arriving · **Deadline:** Wed 30 Sep 2026

**Revised Sat 8 Aug 2026** — a Maker Faire landed in week 7, which was the
buffer week. The taper below is reordered accordingly; see *The Maker Faire
constraint*. Phases 0–2 are unchanged.

The shape of this plan: the weekend converts *unknowns* into *knowns*. It does
not build features. Features are schedulable — you can estimate them and move
them. Unknowns are not, and every unknown left alive on Monday is a hole in the
rest of the schedule. So the cram spends itself on bring-up, camera truth, and
the first accuracy number, and everything after Sunday is ordinary work.

Three numbers come out of the weekend: **fps**, **angular error**, and the
**target size** that error implies. They fork the remaining seven weeks. Do not
start building past them.

---

## Phase 0 — Tonight, Friday · ~3 h · "Boot and probe"

Do this tonight rather than Saturday morning for one reason: if something
physical is missing — a cable, the PD brick, a dead camera — you find out while
you can still order or borrow it, instead of burning Saturday's best hours
discovering it.

- [ ] Unbox. Connect the 8-in-1 hub, HDMI to a monitor, keyboard/mouse, Ethernet
- [ ] Power the hub from the PD brick — **not** from the board
- [ ] Camera into a USB-A port on the hub, not the pass-through
- [ ] First boot of the UNO Q; get on the network; confirm App Lab loads
- [ ] `sudo apt update && sudo apt install -y git v4l-utils`
- [ ] Unpack the spike, `./setup.sh` (creates swap first — let it)
- [ ] `./bin/probe`

**GATE 0 — probe exits 0.** Everything downstream assumes this.

| If probe says | Do this |
|---|---|
| glibc < 2.28 | You're on the hard path. Stop, sleep, reassess Saturday — do not start a Bazel build at midnight |
| no `/dev/video*` | Hub power. Try the camera in the board's USB-C directly to isolate |
| no MJPEG offered | Wrong device node — probe lists several; metadata nodes have no formats |
| controls did NOT stick | Raise `warmup_frames` to 15 in `camera.py`. This is the C920 STREAMON reset |
| under 5 fps on noise | Check CPU governor is `performance`, not `powersave` |

**Hard stop by midnight.** Do not start the bench tonight. A tired first
measurement is a measurement you will not trust and will redo.

---

## Phase 1 — Saturday · ~10 h · "Get the numbers"

### Morning · 3–4 h · Camera truth

Everything measured today inherits from this block. A sloppy camera setup makes
every later number meaningless, and worse, it makes them *plausible* — you will
spend Sunday tuning a filter to fix a focus problem.

- [ ] Mount the camera where it will actually live, on the screen
- [ ] **Measure** eye-to-screen distance with a tape. Put it in `config.toml`
- [ ] **Measure** the screen's *active area* in mm — not the bezel. Into config
- [ ] Sweep `focus_absolute` 0→100 in steps of 5 with the user seated; keep the
      value where the iris edge is crispest. C920: 0 is infinity, higher is nearer
- [ ] Lock exposure; adjust until the iris/sclera boundary is sharp with no
      motion blur when you look around quickly
- [ ] Re-run `./bin/probe`

**GATE 1a — all controls verified, and you can see a sharp iris.**

### Afternoon · 3–4 h · Speed

- [ ] `./bin/bench --sweep --save bench_baseline.json`
- [ ] Sit exactly as the user will sit. An empty-room sweep measures the
      detector's failure path, not the pipeline
- [ ] Run it three times: bright room, dim room, and backlit-window worst case

**GATE 1b — pick the largest `input_size` whose p5 fps stays ≥ 15.** Write it
down. If nothing reaches 15: check the governor, check for thermal throttling,
confirm `bin/probe` says you're on the mediapipe backend and not the unverified
LiteRT one.

### Evening · 2–3 h · First accuracy number

- [ ] `./bin/calibrate --out baseline_cal.npz`
- [ ] Three sessions. **Keep every one of them.**

> **The single most important process note in this plan.** Save the raw
> baseline before you tune anything. The strongest figure this project can put
> in front of a judge is accuracy over time, with and without online
> recalibration — and the "without" arm can only be recorded once, before you
> start improving things. Tune first and it is gone permanently.

**GATE 1c — you have a p95 angular error in degrees and the target size it implies.**

**Saturday night:** write the three numbers in a file. fps, degrees, target
size. Stop.

---

## Phase 2 — Sunday · ~8 h · "Close the loop"

### Morning · 3 h · The UART link and real thresholds

- [ ] Meter both boards' logic levels **before** connecting anything
- [ ] Wire TX↔RX, RX↔TX, GND↔GND
- [ ] Replace `init_sensor()` / `read_pressure()` in `circuitpython/code.py` with
      your I2C sensor. Keep the contract: **signed hPa, positive for puff**
- [ ] Tare, then log pressure through ordinary sipping and puffing
- [ ] Set the four thresholds in `config.toml` **from that log**, not from guesses

**GATE 2a — puffing produces `E left_click` on the UNO Q's serial.**

### Afternoon · 3 h · Gaze moves a cursor

The spike deliberately stops at measurement — there is no `bin/run` yet. This
block is where you write it, and it is about 150 lines of glue:

```
capture → resize → backend.detect → features.extract → blink gate
        → mapper.predict → OneEuroFilter2D → protocol.gaze → serial
```

- [ ] Write `bin/run` composing the above
- [ ] Load `baseline_cal.npz`; suppress output while `is_blinking()`
- [ ] Watchdog: if the breath board's heartbeat goes silent past
      `heartbeat_timeout_ms`, stop moving the cursor. A pointing device whose
      click channel has died should not keep pointing

**GATE 2b — the cursor follows your eyes and a puff clicks.**

### Evening · 2 h · Online recalibration, live

- [ ] Wire `mapper.observe_click()` to real clicks with the activated element's centre
- [ ] Run 30 minutes of ordinary use; log accuracy every few minutes
- [ ] Deliberately shift your seating position partway through

**GATE 2c — you have a drift curve showing error falling as clicks accumulate.**

**Sunday night: stop, and write one page of what you learned.** Not for anyone
else — for you in September, when you will not remember why `focus_absolute` is
45 or which exposure fixed the backlit case. This page becomes the spine of the
maker.io post.

---

## The Sunday-night fork

Your numbers pick the path. Decide once, in writing, and don't relitigate it on
Tuesday.

**Path A — fps ≥ 20 and error ≤ 2.0°.** Direct cursor pointing is viable.
Weeks go to the AAC grid, polish, and user testing. You have room.

**Path B — fps ≥ 15 and error 2.0–3.5°.** The likely outcome. Build the AAC
grid first; add zoom-to-refine for cursor work. Plan for it rather than
treating it as a fallback.

**Path C — fps < 15 or error > 3.5°.** Do not build on this. Diagnose first,
and suspect geometry before code: the C920's 78° lens may simply be putting too
few pixels on the iris. Move the camera closer, or fit an Arducam M12 body with
a ~40° lens — that single change roughly doubles linear iris resolution and is
worth more than any amount of filter tuning.

---

## The Maker Faire constraint

A Maker Faire falls the week before the deadline — week 7, which the original
plan reserved as buffer. If it runs Sat–Sun **Sep 26–27**, you tear down a
booth on Sunday evening and submit by Wednesday.

That is the largest risk in this schedule, and it is not the faire's fault. The
buffer existed to absorb *the thing you cannot predict*. It is now spoken for by
something predicted, which leaves the unpredictable thing nowhere to go.

**The fix is ordering, not extra work: the submission must be assembled before
the faire, not after it.** Documentation and video move to week 6. Week 7 is the
faire, and the days after it are for folding in what the faire produced —
nothing else.

Framed that way the timing is a gift rather than a hazard. A week before
submission you get strangers using the device unrehearsed, video no bench demo
can match, and real sessions for the accuracy-over-time figure. If the
submission is already assembled, the faire *upgrades* it. If it isn't, the faire
*consumes* the time you needed to assemble it. Same event, opposite outcomes,
decided entirely by what happens in week 6.

**Scope is what buys the buffer back.** One unit working well beats two working
badly. Cut in this order, without guilt:

1. **The two-user station.** Keep the identity validation in `config.py` — it is
   written, tested, and costs nothing to leave in — but do not schedule the
   dual-cursor demo.
2. **Cursor mode and zoom-to-refine**, if the AAC grid demos well. The grid has
   the lower accuracy bar and the higher reliability, which at a faire makes it
   the better demo regardless.
3. **Enclosure polish.** Functional beats pretty in a photograph taken at a
   booth.

A second unit stays reachable *only* because of the eMMC image (week 5): it
becomes a flash rather than a build. That image is also how you recover if a
unit dies mid-faire, which is the real argument for it.

---

## Weeks 1–7 · the taper

| Week | Dates | Focus |
|---|---|---|
| 1 | Aug 10–16 | Your path's core build. **Publish the maker.io post as a WIP now** and update it weekly |
| 2 | Aug 17–23 | AAC grid, or zoom-to-refine |
| 3 | Aug 24–30 | Robustness, **aimed at the booth** — see below |
| 4 | Aug 31–Sep 6 | **Real user testing.** Cannot be compressed, cannot be faked, cannot be done in week 7 |
| 5 | Sep 7–13 | Deployed config: barrel-jack power, no hub, enclosure. **Clone the eMMC to an image.** Verify the runtime fits on 2 GB |
| 6 | Sep 14–20 | **FREEZE.** Documentation, video, submission drafted to 90%. Faire prep and packing |
| 7 | Sep 21–27 | **MAKER FAIRE.** Operate it, film it, collect reactions. No development |
| — | Sep 28–30 | Fold the faire material in. Submit. **Not on the 30th.** |

### Week 3 robustness, specifically

A failure at the faire is now unrecoverable, so week 3 targets booth conditions
rather than bench conditions:

- **Lighting.** Faire venues are lit badly — bright, uncontrolled, frequently
  backlit by a window or the neighbouring booth's LEDs. Saturday's backlit
  worst-case sweep *is* the faire case. Weight it accordingly.
- **Stranger calibration.** Sixty seconds, or a default profile that online
  recalibration sharpens live. The second option demos the part of this project
  that is a contribution rather than an integration.
- **Recovery with no keyboard attached.** Face loss, camera unplug, power blip —
  all must self-recover.
- **Duty cycle.** Hours, not minutes. Thermal throttling will move your fps
  numbers away from what you measured in August.

---

## Standing rules

**Publish early, update often.** Documentation quality is an explicit judging
criterion. A post that shows the journey — including the dead ends — reads as
more credible than one assembled in a panic on Sep 29, and starting it in week 1
costs you nothing because you're writing the notes anyway.

**Photograph everything as you go.** You cannot reshoot week one. Bench shots,
the wiring, the first ugly working version, the calibration screen — all of it.

**Keep every calibration run.** They accumulate into the accuracy-over-time
figure that is the strongest single visual this project can produce.

**Log the friction while it still hurts.** Every manual step, dead end and
wasted hour goes in `REPLICATION.md` as it happens. This is an open-source
assistive project: an hour you spend on setup is an hour *every* builder
spends, three times over for your own units. The log is simultaneously the
backlog of things to engineer away and the honest-journey section of the
maker.io post, which is explicitly rewarded. You will not reconstruct it later.

**Soldering is optional for the builder.** Prefer plugs to joints — Qwiic /
STEMMA QT for the I2C pressure sensor, jumper wires to headers for UART. Choose
the sensor breakout on that basis *before* Phase 2 wires it.

**Hard stops at night.** Debugging a vision pipeline past midnight reliably
produces negative progress — you introduce a bug at 1am and spend two hours
Saturday finding it. The cram is Friday through Sunday; sleeping is part of the
plan, not a concession to it.

**Both contests.** The same work submits to the DigiKey/Arduino Dream Lab
Challenge (#UNOQDreamLab on maker.io, closes Sep 30, four winners at ~$5,000)
and to Hackster's *Invent the Future with Arduino UNO Q*. One build, two shots.
