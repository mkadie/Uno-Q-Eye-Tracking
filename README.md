# UNO Q gaze spike

A measurement harness for adding eye tracking to a sip-n-puff assistive device,
targeting the Arduino UNO Q.

This is deliberately **not** a working eye tracker. It is the thing you run
first to find out whether building one in the time you have is comfortable or
tight, and to produce the numbers that decide the design. Guessing at fps and
accuracy and then discovering the truth in week five is how projects miss
deadlines.

## Results, measured

Tested on the public at Maker Faire Bay Area, 25–26 September 2026 —
**125 visitors, 2413 throws.**

| | |
|---|---|
| median gaze error, visitors | **6.26°** (p95 20.60°) |
| median gaze error, practised subject | 3.27° |
| best single visitor | **2.11°** — head held still by a companion |
| visitors at ≤10° median | **87%** |
| **visitors who got nothing at all** | **10%** |
| throughput | 18–25 fps, no NPU, no infrared |
| calibration | 9 points, 7-parameter linear fit |

**Head turn is a cliff, not a slope.** Valid tracking holds near 71% out to
15° of head rotation and collapses to **5% beyond 20°** — past that the
camera is looking at one eye and the tracker does not degrade, it stops.
Every one of the visitors who got nothing sat beyond that line. Head pitch
behaves identically (72% → 4%).

**Accuracy decays with movement away from where you calibrated** — 5.30° if
the visitor stayed within 18 mm, 8.93° if they moved, and half of them moved.

**The remaining error is bias and drift, not jitter** (per-throw scatter is
0.22 of the error scatter), so averaging over a dwell will not rescue it.
The gain has to come from calibration, not filtering.

Full numbers, methods and the things that turned out to be wrong are in
[`RESULTS.md`](RESULTS.md); the portable summary is [`DIGEST.md`](DIGEST.md).

## What it answers

1. **Does the inference stack run on this board at all?** (`bin/probe`)
2. **How fast, and at what input resolution?** (`bin/bench --sweep`)
3. **How accurate, in degrees of visual angle — and therefore how big do my UI
   targets have to be?** (`bin/calibrate`)

Run them in that order. Each one gates the next.

## Quick start

```bash
./setup.sh          # deps, swap, model bundle
./bin/probe         # go / no-go
./bin/bench --sweep # fps vs input size — sit in front of the camera
./bin/calibrate     # accuracy in degrees, and what it means for your UI
pytest tests/ -q    # 195 tests, no hardware needed
```

## The architecture, and why

**Gaze points, breath clicks.** Pure gaze interfaces suffer the Midas touch
problem — everything you look at activates — so they fall back on dwell-time
selection, which is slow and error-prone. A sip-n-puff supplies a discrete
click channel completely decoupled from where the eyes point. That is not a
workaround; it is the configuration commercial AAC vendors charge five figures
for, and it lowers the accuracy bar substantially because you are selecting
regions rather than pixels.

**The breath board stays the HID endpoint.** Your existing CircuitPython
firmware keeps doing pressure sensing, thresholds, debounce and USB HID exactly
as it does now. The UNO Q is demoted to a sensor that streams gaze coordinates
in over UART. This means the eye tracker is a bolt-on that anyone who already
built the sip-n-puff can add, rather than a rewrite that orphans existing
builds — which matters more for an open-source assistive project than
architectural tidiness does.

**Camera on the screen, not the chair.** A near-eye camera on a chair-mounted
gooseneck measures eye-in-head rotation beautifully and has no idea where the
head is relative to the screen, so it drifts whenever the user shifts. That
geometry only pays off if the camera is head-*coupled*. A screen-mounted camera
sees the whole face, so head pose and iris position compose into gaze in screen
coordinates. Hence `features.py` carrying both.

**No IR, for now.** IR's win is the dark-pupil and glint trick for a near-eye
camera doing PCCR geometry. With a screen-mounted camera, MediaPipe's face mesh
does the heavy lifting, and that model was trained on visible-light RGB.
IR-illuminated monochrome is out of distribution for it — you would be
degrading the stage you depend on to improve a stage you are not using.

**Online recalibration is the interesting bit.** Drift is what makes cheap eye
trackers unusable after twenty minutes. A dwell-based tracker cannot cleanly
fix it, because the dwell *is* the selection, so the estimate and the label are
not independent. Your breath click is an independent confirmation channel:
every puff yields a clean (gaze estimate, intended target) pair, for free,
during ordinary use. `calib.py` accumulates those and continuously refits.

That is the part of this project that is a contribution rather than an
integration, and it is what to lead with in the writeup.

## Two things that will cost you a day each if you skip them

**The C920 resets its UVC controls at `VIDIOC_STREAMON.`** Set exposure and
focus before opening the capture — the obvious order — and the camera silently
discards them. No error anywhere. You get autofocus hunting and auto-exposure
breathing and you blame your gaze code for the jitter. `camera.py` opens the
stream, discards warmup frames, *then* applies controls, then reads them back
to verify. `bin/probe` reports on it explicitly.

**No multi-puff gesture on the fast path.** Triple-puff and puff-sip-puff both
require waiting after every puff to see whether another follows, which adds
that wait to the latency of every ordinary click, forever. Recalibration
instead sits behind a long hard-sip prefix that cannot be confused with a
normal sip-click, so the fast path is untouched. `tests/test_gesture.py`
contains a test asserting click latency never exceeds debounce — it exists to
stop someone casually reintroducing a fast-path timeout later.

## Multi-unit identity (two cursors on one host)

Only relevant once more than one gaze mouse shares a USB host — two users on a
Fruit Jam, each driving their own cursor. A single-unit build ignores all of it.

The problem: two units of the same build are indistinguishable by USB
descriptor. Same VID, same PID, same product string. The host binds cursors in
enumeration order, that order varies between reboots, and the two cursors swap.

The fix is a distinct product string per unit, set in `boot.py` via
`supervisor.set_usb_identification()`, with a binding table in `config.toml`:

```toml
[device]
name      = "left"
usb_label = "Gaze Mouse L"

[[cursor]]
name   = "left"
match  = "Gaze Mouse L"
glyph  = "cursor_l.bmp"

[[cursor]]
name   = "right"
match  = "Gaze Mouse R"
glyph  = "cursor_r.bmp"
```

Vary the product *string*, never the VID/PID — inventing a vendor ID means
squatting on somebody else's registered number and buys nothing the string
doesn't.

**`glyph` is required and must be unique, and the validator enforces it.**
Cursor identity is carried by shape; the accent colour is decorative
reinforcement. Two cursors distinguishable only by colour fail for a
colourblind user, which on an assistive device is not a defensible default.
Distinct accents do not excuse a duplicate glyph. Unset accents are filled from
validated palette slots in fixed order.

`boot.py` reads its identity from `settings.toml` via `os.getenv()` —
CircuitPython's native mechanism, always present, unlike a full TOML parser.
Generate it from the same source of truth so the two can't drift:

```bash
python3 -c "import sys; sys.path.insert(0,'.'); from spike import config; \
print(config.settings_toml(config.load('config.toml')), end='')" \
> circuitpython/settings.toml
```

`boot.py` also gates its interface trimming behind a **grounded safety pin**.
That guard is not optional: if `boot.py` disables the CIRCUITPY drive and
anything is wrong, you can no longer edit `boot.py` to fix it, and the only
recovery is a full erase and reflash. One jumper buys back the ability to undo
your own mistake.

## Verification status

Be clear about what has actually been exercised.

**Tested — 85 passing tests, no hardware required:**

| module | what is covered |
| --- | --- |
| `oneeuro.py` | jitter reduction, lag vs beta, dropped-frame gaps, duplicate timestamps, no step overshoot |
| `gesture.py` | click latency bounded by debounce, command-mode entry/exit/timeout, dead-end sequences, no click leakage in command mode |
| `protocol.py` | CRC roundtrip, single-bit-flip detection, split-packet framing, bounded buffer |
| `calib.py` | fit recovery, ridge behaviour on sparse grids, **drift correction 4.35° → 1.94° over 24 simulated clicks**, anchor decay, bad-sample resistance |
| `features.py` | iris monotonicity, scale invariance, blink detection, degenerate-eye safety |
| `config.py` | multi-unit identity: duplicate match/glyph/name rejection, colour-alone prevention, palette assignment, settings.toml codegen |

**Not tested — needs your hardware:**

- `backends/mp_backend.py` — structurally correct, but never run against real
  weights (the authoring machine could not reach the model CDN).
- `backends/litert_backend.py` — **unverified.** Anchor generation and ROI
  alignment follow MediaPipe's documented BlazeFace config, but treat it as a
  starting point needing a debugging pass. You probably will not need it;
  see below.
- `camera.py`, `bin/*` — require a camera and a screen.

## The ARM64 question, resolved

The widely-repeated claim that MediaPipe does not run on ARM64 Linux was true
and is now stale. Checked against PyPI:

| package | aarch64 Linux wheel |
| --- | --- |
| `mediapipe` 0.10.x | no — macOS arm64 and x86_64 only |
| `mediapipe` 1.0.0 | **yes** — `manylinux_2_28_aarch64` |
| `ai-edge-litert` 2.1.6 | yes — `manylinux_2_27_aarch64`, cp310–cp314 |
| `tflite-runtime` 2.14.0 | yes |

`manylinux_2_28` needs glibc ≥ 2.28; Debian 12 ships 2.36. So both the primary
and the contingency path are plain pip installs, and the Bazel-build scenario —
the one that would have been ugly on a 2 GB board with 3 GB of free rootfs —
is off the table. `bin/probe` verifies the glibc version rather than assuming.

## Reading the calibration output

`bin/calibrate` fits on one grid and reports error on a *separate* validation
grid, because reporting error on the points you fitted to is self-flattery. It
converts to degrees and then to the thing you actually need:

```
minimum reliable target  52 mm  (189 px)
usable grid              10 x 5 cells
```

Rule of thumb: targets must exceed about 2× your p95 angular error. At 600 mm,
1° ≈ 10.5 mm on screen. If you land at 8+ columns, direct cursor pointing is
viable. At 4–8, the AAC grid is fine but desktop cursor work wants the
zoom-to-refine stage (gaze picks a region, puff magnifies it, second gaze picks
within it — two coarse gazes composing into one precise click). Below 4,
something is wrong: check that the face fills the frame, that exposure and
focus locked, and that `input_size` is not too small.

## Layout

```
spike/
  probe/bench/calibrate deps:
  camera.py       V4L2 + control locking that survives the C920
  backends/       mediapipe (primary) | litert (contingency)
  features.py     landmarks -> iris-in-socket + head pose feature vector
  calib.py        ridge polynomial fit + online recalibration
  oneeuro.py      adaptive smoothing for pointing
  protocol.py     CRC8 line protocol, UNO Q <-> breath board
  gesture.py      breath FSM (runs on CPython AND CircuitPython)
  metrics.py      percentile timing, not means
bin/              probe, bench, calibrate
circuitpython/    code.py for the breath board
config.toml       one file, shared by both sides
```

## Wiring

```
camera        -> UNO Q USB-C (through the powered hub on the bench)
UNO Q TX/RX   -> breath board RX/TX   (both 3.3 V — verify yours)
UNO Q GND     -> breath board GND
breath board  -> host PC USB (stays the HID mouse)
```

For the deployed build, drop the hub: power the UNO Q from its 7–24 V barrel
jack and give the USB-C entirely to the camera. Fewer parts, no PD negotiation
in the chain, and PD negotiation is exactly what fails intermittently at 6am.

## Next, once you have numbers

1. Build the on-device AAC grid before the cursor. Lower accuracy bar, no HID
   plumbing, runs entirely on the board — a demoable artifact weeks earlier.
2. Wire `observe_click()` to real clicks so drift correction runs live.
3. Then cursor mode, then zoom-to-refine if the calibration numbers call for it.

Keep `bin/calibrate` output from every session. A plot of accuracy over time,
with and without online recalibration, is the strongest single figure this
project could put in front of a judge.

## Data, images and privacy

`study_data/bff_gaze_study.jsonl` holds the Maker Faire sessions. It contains
**no names, faces, images or audio** — only gaze coordinates, head angles,
distances and timings, one row per carrot thrown. It is published so the
numbers above can be checked.

The camera frames in `board_artifacts/` were shot in the developer's home and
have been de-identified by [`tools/deidentify.py`](tools/deidentify.py): the
face and the drawn annotations are kept, everything else is downsampled to
1/44 scale and then blurred. Pixels are discarded rather than smoothed,
because a Gaussian blur alone is partly invertible. The raw frames inside the
`rims_*.npz` captures got the same treatment — they are unannotated shots of
the same room, so de-identifying only the PNGs would have been theatre.

**One consequence for reproducibility:** rim detection re-run on the
published `.npz` frames will find fewer spurious background candidates than
the original analysis did, because the background clutter that produced them
is gone. The false-positive findings in `RESULTS.md` were measured on the
unmodified frames.

## License

[MIT](LICENSE). Use it for anything, including commercially; keep the
copyright notice.

Third-party material shipped alongside keeps its own terms and is **not**
relicensed by this:

- `models/face_landmarker.task` and `models/bundle/*.tflite` — MediaPipe face
  landmarker, © Google, Apache License 2.0.
- Runtime dependencies (OpenCV, NumPy, `ai-edge-litert`, MediaPipe) are each
  under their own licenses.

The Maker Faire session data in `study_data/` is released under the same
terms; see **Data, images and privacy** above for what it does and does not
contain.

## Who this is for

This exists so that the sip-n-puff assistive device built by
[R.O.A.R. / TSSFAA](https://tssfaa.com) can gain eye tracking as a **bolt-on**
rather than a rewrite. The breath board stays the USB HID endpoint; the UNO Q
is a sensor that streams gaze coordinates over UART. That choice is
deliberate and is documented in `CLAUDE.md`, so existing builds are not
orphaned.
