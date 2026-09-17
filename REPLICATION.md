# Replication log

Every manual step, dead end, and wasted hour, recorded while it still stings.

**Why this file exists.** This is an open-source assistive device. An hour spent
on setup is not an hour *you* lost — it is an hour that every person who tries
to build one will lose, and three times over for your own units. So the log has
two jobs at once:

1. It is the backlog of things the flashable image has to delete.
2. It is the honest-journey section of the maker.io post. Documentation quality
   is an explicit judging criterion, and a build log that includes the dead ends
   reads as more credible than one assembled from memory in September.

Write entries *as they happen*. You will not reconstruct the detail later, and
the detail is the whole value — "SSH wasn't enabled" is worthless, "the board
pings but every port is closed and there is no way to get a first shell without
physically attaching a keyboard" is the thing that saves somebody an evening.

**Format.** Newest last. Each entry: what happened, what it cost, and — the part
that matters — **what deletes it for the next builder**.

---

## Target: steps a builder should have to perform

The scoreboard. Everything else on this page is an argument for shortening it.

| Step | Status |
|---|---|
| Flash image to the board | required, irreducible |
| Plug in camera, hub, power | required, irreducible |
| Wire UART to the breath board (3 jumpers) | required, irreducible |
| Set unit identity | **should become a jumper or first-boot prompt** |
| Calibrate (per user, not per unit) | required, runtime |
| *Everything below this line should be zero* | |
| Attach keyboard + monitor | ❌ currently required — see 2026-08-08 |
| Enable sshd by hand | ❌ currently required — see 2026-08-08 |
| Run `setup.sh`, wait on apt/PyPI/CDN | ❌ currently required — see below |

---

## 2026-08-08 · USB-C is not a control path — ~1 h

**What happened.** Spent an hour trying to reach the board from the dev machine
over USB-C before switching to Ethernet.

The board's USB-C is a **power sink and a USB host** — it is the port the camera
hub hangs off. It does not present a device to a PC the way a classic Arduino's
ATmega does. Symptoms, all of which look like a broken cable and are not:

```
lsusb                  → no Arduino (2341:*), Qualcomm (05c6:*) or adb (18d1:*) device
/dev/ttyACM* ttyUSB*   → do not exist
adb devices            → empty
arduino-cli board list → "No boards found"
ip link                → no RNDIS/ECM gadget interface appears
```

**Cost.** ~1 h, plus the temptation to unplug the camera to free the port —
which would have cost the camera, keyboard, monitor and Ethernet in exchange for
nothing.

**Caveat on the evidence.** A 3-minute `udevadm monitor` capture recorded zero
events, but no USB replug was actually performed during that window, so it
proves less than it appears to. The state scans above are the real evidence.
A deliberate plug-while-watching test has not been run.

**What deletes it.** A sentence in the README, near the top, before anyone
reaches for a cable: *the UNO Q is reached over the network, not over USB.*

---

## 2026-08-08 · No first shell without a keyboard — blocking

**What happened.** Ethernet works immediately. With the dev machine sharing its
connection, the board appears without any configuration:

```
enp1s0        10.42.0.1/24        (dev machine, NetworkManager shared mode)
board         10.42.0.119         1.8 ms, 0% loss
```

Connection sharing also NATs, so the board reaches the internet through the dev
machine's wifi — apt and pip work with no router configuration. That part is
genuinely frictionless and worth keeping in the instructions.

**But nothing is listening.** All 30 common ports closed — 22, 80, 443, 5555,
8080, 3000, 9090 among them. The image does not ship `sshd` enabled.

**Why this is the worst kind of blocker: it is circular.** Every remote path
needs a daemon that is already running.

| Path | Needs |
|---|---|
| SSH | `sshd` running |
| adb over USB | `adbd` running, USB in device mode |
| USB serial gadget | `g_serial` configured in the kernel |

You need a shell to enable the thing that gives you a shell. So even if USB-C
*did* enumerate, the first step would still be attaching a keyboard to turn
`adbd` on. There is no ordering in which the monitor is avoidable.

The only genuine alternative is a USB-TTL adapter on the UART header, and only
if the board exposes a login console there — unverified, and probably a longer
gamble than just fetching a keyboard.

**Current workaround.** Once, at the board's own keyboard:

```bash
sudo apt update && sudo apt install -y openssh-server
sudo systemctl enable --now ssh
```

**Cost.** A keyboard, a monitor, an HDMI cable and a free USB port, for every
builder — on a device explicitly aimed at people for whom a spare monitor is not
a given.

**What deletes it.** `sshd` baked into the flashable image, enabled on first
boot. This is the single strongest argument for the image strategy: it converts
the worst step in the build from *find a monitor* to *nothing at all*.

---

## 2026-08-08 · Board dies after ~20 min / mid-boot — three occurrences, unresolved

**What happened.** After ~20 minutes reachable, the board stopped responding
entirely. The Ethernet carrier stayed up, so the cable and hub were still
electrically fine — the host was simply gone.

```
ping 10.42.0.119    → 4 sent, 0 received, 100% loss   (was 0% loss @ 1.8 ms)
enp1s0 carrier      → 1
sweep 10.42.0.100–130 → nothing alive
```

A useful diagnostic side-effect: a machine that has vanished mimics a firewall.
Port 22 timed out at 5000 ms (reads as "filtered") while other ports returned
quickly (reads as "refused"). Neither was true. **Re-verify liveness before
interpreting any port scan.**

**Cause.** Not yet established. Candidates, most likely first:

1. Undervoltage. `CLAUDE.md` warns that the board wants 5 V @ 3 A and that
   brownout presents as random instability resembling a software bug. Check the
   hub is powered from the PD brick and *not* from the board.
2. Cables moved during the USB experiments above.
3. Thermal or a kernel panic — `dmesg` after reboot, and check uptime.

### Occurrences 2 and 3 — 2026-08-08 evening, after a dev-machine crash

The same fault, now with a sharper signature. The board no longer merely drops
off after 20 minutes; it **dies partway through boot**, twice, identically:

```
17:43:18  enp1s0 carrier: link connected      <- board powered on
17:43:44  DHCPDISCOVER 00:e0:6b:67:24:6a      <- +26 s: networking came up
17:43:44  DHCPOFFER    10.42.0.250
          (no DHCPREQUEST, no DHCPACK, ever)  <- it died right here
17:53:38  rx_packets = 2, silent 10 min, link still detected
```

A power cycle reproduced it exactly (17:13 run: 7 carrier flaps in 2 min, one
DISCOVER, no ACK). **This is now reproducible on demand**, which the first
occurrence was not.

**Why this points harder at power than the first occurrence did.** A DHCP client
that broadcasts DISCOVER, receives an OFFER, and never sends REQUEST is not a
network misconfiguration — it is a machine that was running and then abruptly
was not, ~26 seconds into boot. Boot is also when draw peaks: eMMC, all four
cores, USB enumeration and the camera spinning up at once.

**The Ethernet PHY sits on the powered hub, not the board.** That is why `Link
detected: yes` throughout, and why carrier is worthless as evidence the board is
alive. Only `DHCPACK` (or a ping reply) proves that.

### Likely cause found — hub power — 2026-08-08 20:05

**Re-cabling the hub's power brought the board straight back**, first try, after
three consecutive failed boots. The hub had been fed from the board, so the
C920's inrush was landing on the board's own rail — candidate 1 in the list
above, and the arrangement this file already warned about.

Confidence: **one success against three failures.** The mechanism fits every
observation (dies ~26 s in, at peak boot draw; no board-side error logged; every
prior session ends in `crash` with no clean shutdown), but a single good boot is
not proof. Treat as *likely* until it survives a soak under load.

**Why the board-side logs will never confirm this.** The QRB2210 does not emit
Pi-style undervoltage warnings, `dmesg` was clean after recovery, and
`/sys/fs/pstore` was empty. Absence of evidence here is not evidence of absence
— a brown-out leaves no trace by definition. **Do not go looking for a software
cause on the strength of a clean `dmesg`.**

**Why it cannot be left unresolved.** Three units on a shared booth power strip,
running for hours, with a hub and PD negotiation in every chain, is the same
failure in public. `PLAN.md` already specifies barrel-jack power and no hub for
the deployed build; this is an argument for pulling that decision forward, since
it is simultaneously the reliability fix, the replication fix (fewer parts, no
PD negotiation) and a cheaper BOM.

**What deletes it.** Barrel-jack power in the deployed configuration, and a
documented known-good power arrangement for the bench.

---

## 2026-08-08 · MediaPipe's aarch64 wheel needs ARMv8.1; the board is ARMv8.0 — ~2 h

**The big one.** `mediapipe` 1.0.0 installs cleanly, imports cleanly, and then
kills the process the instant it runs.

```
FATAL ERROR: This binary was compiled with lse enabled, but this feature is
not available on this processor (go/sigill-fail-fast).
```

LSE (Large System Extensions) atomics are ARMv8.1. The QRB2210's core is
ARMv8.0:

```
/proc/cpuinfo Features:  fp asimd crc32     <- no "atomics"
CPU architecture:        8
```

**Why it is nastier than an ordinary missing dependency.** `libmediapipe.so` is
loaded lazily, so `import mediapipe` succeeds and reports version 1.0.0. Every
natural way of asking "is mediapipe available?" therefore answers yes. The
failure only arrives when native code executes — and it arrives as **SIGILL**,
which is not a Python exception. `try/except` cannot catch it; there is no
stack left to unwind. `backends/__init__.py` had exactly that shape of check
and had to be rewritten to run a smoke test in a **child process**, because
watching a child die is the only way to observe this.

**It also invalidates a documented conclusion.** README.md § "The ARM64
question, resolved" argued the primary path is a plain pip install because the
`manylinux_2_28_aarch64` wheel exists and Debian's glibc is new enough. Both
premises are true. The conclusion does not follow. **On ARM, "installs" and
"runs" are different questions**, and the wheel tag encodes only the first.

**Cost.** ~2 h, most of it spent believing Gate 0 was a camera or config
problem. Also the reason `bin/probe` crashed rather than reporting.

**What deletes it.** Three things, all now in the tree:

1. `backends.mediapipe_runs()` — subprocess smoke test that constructs a
   landmarker and runs one frame. Reports *"killed by signal 4 — binary needs
   ARMv8.1 LSE atomics, this CPU lacks them"* instead of dying.
2. `bin/probe` now names the cause in its runtime table.
3. This entry, so nobody re-derives it. As far as we can tell no public write-up
   mentions the LSE requirement — it only shows up on a real A53.

**Downstream consequence.** `litert_backend.py`, written as a contingency and
shipped explicitly unverified, is now the *only* path. It has since been
verified on hardware (10/10 geometry checks, see RESULTS.md), but one real bug
had to be fixed first: `LM_SIZE` was 192, taken from MediaPipe's older
standalone `face_landmark.tflite`, while the `face_landmarker.task` bundle
ships a **256x256** landmark model. It now reads the size from the model. That
bug could only fire once detection *succeeded*, which is the worst possible
moment to discover it.

---

## 2026-08-08 · setup.sh creates swap the board already has — minor

`setup.sh` guards its 2 GB swapfile on `swapon --show` finding nothing. But
`/usr/sbin` is not on the PATH of a non-login SSH shell, so `swapon` is not
found, the check reads as "no swap", and it allocates 2 GB on a 10 GB disk that
already had 1.8 GB of zram swap.

Harmless here. Wasteful for every builder, on the partition CLAUDE.md already
warns is tight.

**What deletes it.** Use an absolute path in the guard, and detect zram
specifically rather than treating all swap as equivalent. Same fix applied to
`hil`, which hit the identical problem.

---

## 2026-08-08 · C920 exposure quantised to EV stops while streaming — ~40 min

`bin/probe` reported `exposure_time_absolute want=250 got=156`, reproducibly.
That is the exact signature of the C920 STREAMON reset this project is built
around, and PLAN.md's Gate 0 table prescribes raising `warmup_frames` to 15.

**That fix would never have worked**, and the time would have been spent
wondering why.

With no stream open, every value sticks. While streaming, writes land on
`39, 78, 156, 312, 625, 1250, 2500` — factor-of-two steps, one EV apart — and
anything in between is floored to the stop below. The control advertises
`min=3 max=2047 step=1` and defaults to 250, so the interface gives no hint.

Two lessons worth keeping:

1. **A control that reads back wrong is not necessarily a control being
   ignored.** Sweep the value space before assuming a reset. The sweep took two
   minutes and answered it outright.
2. **Verify with a live capture, not a configuration check.** Every value
   worked when nothing was streaming.

`config.toml` now uses 156 with the ladder documented beside it, and
`camera.py` distinguishes quantisation from a reset in its report so the next
person is not sent to `warmup_frames`.

Also found alongside it: `exposure_dynamic_framerate` was **1** on this board
(default 0). It permits the camera to shorten exposure to hold frame rate,
overriding manual exposure. Now forced to 0 before exposure is written.

---

## Open — not yet friction, but will be

- **`setup.sh` depends on the internet working.** apt mirrors, PyPI, and a
  Google CDN for the model bundle: four things that can each fail on somebody
  else's Saturday, in ways that cannot be debugged remotely. The image removes
  all four. Keep the script published anyway — it is the reproducible recipe for
  how the image was made, and it proves the image is not a black box.
- **Can the UNO Q's eMMC be imaged at all?** The entire replication strategy
  rests on this and it is unverified. Find out in August, not in week 5.
- **Unit identity is the only per-unit variable.** `name`, `usb_label`, `glyph`
  in `config.toml`. One variable should mean one action: a first-boot prompt, or
  better, two GPIO jumpers giving four identities with no software step at all.
- **Camera choice is a replication decision, not just an optics one.** If the
  numbers land in Path C and the fix is a narrower lens, whatever replaces the
  C920 has to be something a builder can actually buy.
