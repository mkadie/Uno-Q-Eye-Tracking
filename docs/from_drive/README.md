# Pulled from Google Drive

These came from `claude/sip-n-puff/` on Drive and existed **nowhere else**.
A Drive folder is one accidental delete from gone, so they are versioned here
too. Drive stays the working copy; this is the backup.

| file | what it is |
|---|---|
| `head_track.md` | the spec for head tracking, written 2026-09-29 |
| `headtrack.py` | the standalone reference implementation it points at |

**`headtrack.py` is NOT what runs.** The shipped implementation is
`spike/tagtrack.py` plus `--mode head` in `bin/talker`, which follows the
spec's "reuse, don't duplicate" rule: it uses the repo's own camera, One Euro
filter, calibration UI and dwell rather than this file's parallel versions.
Kept because it is the reference the spec cites, and because its `Link` class
is the uinput/serial/App-Lab-Bridge path we deliberately did not take -- if
the pointer ever has to leave this process, that is where to start.

Two places the spec and the measurements disagree, both recorded in
`RESULTS.md` and `CLAUDE.md`:

- The spec says tag **ID 0**. The tag physically on the glasses is **ID 2**,
  and a wrong id reads exactly like bad lighting.
- The spec says drop to 960x540 if fps < 25. Measured, that costs a third of
  the detections for 2 fps. Do not.
