# board_artifacts

Pulled off the board (eMMC is not imaged; treat board-only files as at risk).

| file | run | note |
|---|---|---|
| `soak_watch_2026-08-16.log` | soak **PASS** | host-side 60 s poll, the primary evidence |
| `soak.log.2026-08-16` | soak PASS | 18 bench runs, 0 tracebacks |
| `load.log.2026-08-16` | soak PASS | banner only — that command prints no progress |
| `soak.done.2026-08-09-VOID` | soak FAIL | **`FINISHED` from the VOID run.** Kept as the example of why `soak.done` alone proves nothing: the camera node had moved, every bench died in ~1 s, and the loop "finished" in 20 s. |
| `bench_*.json` | Gate 1b | see RESULTS.md |

Still board-only: `ref_frames.npz` (39 MB).

## Gate 1c calibration runs — 2026-08-16

Validation = the STALE mapping. Run 4 leave-one-out (fresh mapping) = **2.73° mean / 7.75° p95**.

| file | grid | protocol | val mean | val p95 |
|---|---|---|---|---|
| `cal_2026-08-16_run1_9pt.npz` | 9 | normal | 16.49° | 27.79° |
| `cal_2026-08-16_run2_25pt.npz` | 25 | normal | 15.21° | 19.32° |
| `cal_2026-08-16_run3_headstill.npz` | 25 | "head still" (not achieved) | 8.97° | 13.90° |
| `cal_2026-08-16_run4_chinrest.npz` | 25 | **chin rest** (worked: ty 32.9→12.3 mm) | 11.64° | 18.65° |
| `cal_2026-08-16_run5_chinrest_drift.npz` | 25 | chin rest + **`vX`/`vy`/timestamps** | 14.41° | 21.32° |

| `cal_2026-08-16_run6_denseval.npz` | 25 | chin rest, 26 val, **raster** | 38.83° | 61.41° |
| `cal_2026-08-16_run7_random.npz` | 25 | chin rest, 26 val, **RANDOMISED** | 8.12° | 16.12° |

**Run 7 is the authoritative one.** Runs 1-6 presented both grids in raster
order, making elapsed time collinear with target y (r = +0.98) — every
head-pose/time correlation from them is inflated. Run 7 randomises presentation
(seed 20260816, stored in the file). Clean result: 8.22° at 0 clicks against
7.78° chance, falling to 5.12° mean / 7.95° p95 by 20 online clicks. Run 6 also
overfit badly because `config.toml` still had `ridge = 0.001`, which became
near-zero regularisation once the design matrix was standardised.

| `cal_2026-08-16_run8_fullres.npz` | 25 | 1080p + **full-res ROI crop** | 18.20° | 35.35° |

**Run 8 is the negative result**: more iris pixels (8.3→10.0 px) gave a *worse*
raw gaze signal (iris↔target x 0.902→0.664). Config reverted to 720p.

**Superseded by run 7** — it is the only file carrying the
validation block's own features (`vX`, `vy`) plus per-point timestamps
(`t_cal`, `t_val`), so a fix can be evaluated on real held-out data with no
chair time. Its finding: predicted-vs-true `r = 0.992` on x, but output
compressed ~2.5× toward centre; rescaled, 2.42° mean / 3.87° p95.
| — | — | **chance on that validation grid** | **7.84°** | **12.53°** |

Each holds `aX` (points × 10 features) and `ay` (targets), so the ridge /
capacity / head-pose analysis in RESULTS.md can be redone with no new sitting.
Kept per CLAUDE.md "keep every calibration run" — the without-recalibration arm
is recordable only once.

## Repeatability

| file | what |
|---|---|
| `repeat_2026-08-18.npz` | 9 targets x 3 passes, `bin/repeat`. **Confounded** — subject at 442 mm (vs 730 mm in run 7), 6-9 mm head movement between passes, iris excursion 2-4x smaller than geometry predicts. Head-turning, not eye movement. Redo on a chin rest at fixed distance. |
