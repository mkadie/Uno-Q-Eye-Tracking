# Superseded digests

Snapshots of `DIGEST.md` as it stood on a given date. Kept because the record
of what the project believed *when* is data: several conclusions here were
later overturned by measurement, and the dates are what let anyone reconstruct
the order in which that happened.

Git history holds these too, but a git log is not something a collaborator or
a future chat will think to search. A file with a date in its name is.

**These are not current.** The live version is `DIGEST.md` in the repo root.

| snapshot | superseded by | what changed |
|---|---|---|
| `DIGEST-2026-09-21.md` | 2026-09-23 | fixation noise measured (and the instrument rebuilt to do it); the red lamp measured at 3.2x steadier; `radius_mm` suspicion retracted |

## The retractions, specifically

Worth reading for the reasoning rather than the conclusions:

- **"Nobody has measured fixation noise"** was true, but the measurement was
  not merely missing — the tool that existed for it was wrong. It held one
  fixation for 15 s and reported scatter about its single mean, which on
  synthetic data with a known answer of 42 px returned 169, because the
  subject's own ocular drift counted as tracker noise.
- **`radius_mm` suspected ~2% high** came from one distance, where a plane
  offset and a scale error look identical. Six ladder rungs separated them.
- **The talker's jumpiness** was attributed to the tracker. It was largely
  the light.

A copy of this archive also lives in Google Drive alongside the digests
themselves, for contexts with no repo access.
