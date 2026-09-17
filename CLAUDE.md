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
