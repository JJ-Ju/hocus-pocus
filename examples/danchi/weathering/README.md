# Danchi weathering by rule

The round-7 danchi building weathered in facade space and checked against the rulebook in
`scripts/weathering/` (rendered as `.claude/skills/procedural-materials/references/weathering-rules.md`).
A build is shown for review only when the gate accepts it.

## Data

The scripts read the round-7 building as facade planes at 50 px per metre: `WX_DATA` (default
`./data`) holds `real/clean_{S,W,N}.npz` (albedo, depth, position, normal, class per pixel) and
`out/elev_r7/` (the capture conventions, frames and building plan). They are not committed: the
planes are about 0.4 GB each. Regenerate them with hython from the round-7 hip:

```
hython elevation_capture.py <WX_DATA>/out/elev_r7 clean,clean_dressed
hython export_building.py <WX_DATA>/out/elev_r7
hython clean_to_npz.py <WX_DATA>/out/elev_r7 <WX_DATA>/real
```

`elevation_capture.py` renders Karma orthographic elevations of the asset at exactly 50 px per
metre (set `WX_HIP` to the round-7 hip if it is not at `examples/danchi/work/danchi_v007.hiplc`).

The coat set the material terms and close-ups read is in `examples/danchi/tex/round_e/`
(`WX_TEX`).

## Running

```
python -I run_real.py <out_dir> <preset> [--seed N] [--override layer=value ...] [--gains gs,ga,k]
python -I ../../../scripts/weathering/weather_gate.py check <out_dir> --json <out_dir>/gate.json
./runset_real.sh <tag>                  # the seven preset builds, four at a time, each gated
./sweeps_all.sh <tag> <gs,ga,k>         # streaks, damage, grime, stain-field sweeps at fixed gains
./sweep_grime_fine.sh <tag> <gs,ga,k>   # grime at 0.1-0.6, the range the rules accept
python -I pipeline_g.py <tag> [N]       # round G: presets, then the six sweeps at Typical's gains, N builds at a time
python -I pipeline_h.py <tag> [N]       # round H: presets with matched seeds, then six sweeps (rust its own; no damage)
python -I pipeline_i.py <tag> [N]       # round I: presets, then the rust, streak and growth sweeps
python -I render_review.py <jobs.json>  # review images: the engine-mirror composite or the 50 px/m sheet of a build
```

Run them from this folder. Builds go to `$WX_OUT` (default `./builds`, not committed); use the gains
Typical solved for (`meta.json`, `gains`) so a sweep changes only its control.

Presets: `new` (0 years), `kept` (10 years, upkeep 1.0), `typical` (35 years, upkeep 0.9, the
default), `worn` (35 years, upkeep 0.5), `derelict` (45 years, upkeep 0.12). A build writes one
`<plane>.npz` per facade plane (darkening, each layer's own map, classes, sources, edges, joints,
the material field, clean and weathered albedo), `meta.json` (config, solved gains, coverage,
targets), lit JPG previews, and 1 m close-ups at 1 mm per pixel (`closeup_<plane>_<spot>`).

`crop_capture.py` (hython) renders the geometry of review crops at their own density (classes, albedo,
normal) for the compositor. `entry_images.py` cuts the review images (lit elevations at 2/5 scale and 1:1 crops at fixed
places). `real_planes.py` turns the captures into planes with their features: tops, sill ends,
corner heads, fixings, shelter, flow starts at depth steps, and the construction joints on the
solid walls. `run_proto.py` holds the build loop and the stand-in planes (`facade_synth.py`) used
for fast iteration.

## Accepted builds, round I

Rulebook 1.6 (round I), 78 rules. New this round: the texture stage (tiling detail revealed by the masks, checked by T1-T3), marks that grow in area with each preset (L5), streaks in the vertical lines (H6), one organic colour continuum in its own growth layer (I4-I6), and rust by water flow (R3-R6). Accepted presets: New, Kept, Typical, Worn, Derelict. Seeds were not rebuilt (round H: the same state). The round's review page shows the presets and the rust control; the streak and growth controls fail at their upper steps (below) and wait for the next round.

At Typical's solved gains (2.1024,1.3406,0.8365):

| Control | Accepted steps | Rejected steps | Series |
|---|---|---|---|
| rust | 0.25, 0.5, 0.75, 1 | 0 (B2) | accepted |
| streaks | 0, 0.5 | 0.25 (H4); 0.75 (D1); 1.0 (C3, D1, H6) | failed L4 |
| growth | 0, 0.25 | 0.5 (B2, G5, M3); 0.75 (G5); 1.0 (B2, C3, E1, F1, G4, G5, M1) | accepted (two steps) |

## Accepted builds, round H

Rulebook 1.5 (round H), 68 rules. The presets follow the user's rename through the soiling clock: Typical (35 years, upkeep 0.9) has round G's Kept look, Worn round G's Typical, Derelict (45 years, upkeep 0.12, was Neglected) round G's Worn, and Kept (10 years, upkeep 1.0) is new, halfway from New. Accepted presets: New, Kept, Typical, Worn, Derelict. Typical seeds 2-6 are matched to seed 1 (A5); accepted seeds: 1, 6 (rejected: seed 2 G6; seed 3 G6; seed 4 F1; seed 5 C3). Damage has no sweep this round (the user asked for the other areas first); rust is its own control.

At Typical's solved gains (2.0538, 0.9861, 0.6411):

| Control | Accepted steps | Rejected steps | Series |
|---|---|---|---|
| rust | 0-1 | none | accepted |
| growth | 0-0.25 | 0.5 (M2); 0.75 (G5); 1.0 (B2, C3, E1, G5, M1) | accepted, but two steps: not reviewed |
| stain fields | 0-0.5 | 0.75 (C3, E1, I3); 1.0 (A3, C3, D1, G6, I3) | accepted |
| edges | 0-1 | none | accepted |
| grime | 0.2-0.6 | 0.1 (B3, G5); 0.3 (B2) | failed L3: not reviewed |
| streaks | 0.25-0.75 | 0 (B2); 1.0 (C3, H1) | accepted |

## Accepted builds, round G

Rulebook 1.4 (round G), 61 rules. The presets, the Typical seeds and each control sweep's steps listed as accepted passed every single-building rule; the accepted presets passed A4 together. A sweep is reviewed only when its accepted steps also pass its series rules (L1-L4, K2 for damage, M5 and M8 for growth); grime and growth did not. Rejected preset: Neglected (C3, D1).

At Typical's solved gains (2.4478, 0.7312, 0.6851):

| Control | Accepted steps | Rejected steps | Series |
|---|---|---|---|
| streaks | 0.25-1.0 | 0 (B2) | accepted |
| damage | 0-0.75 | 1.0 (M1) | accepted |
| grime | 0.2-0.5 | 0.1 (B2, B3, G5, I3); 0.6 (F3) | failed L3 (uneven cover steps): not reviewed |
| stain fields | 0-0.75 | 1.0 (C3, G6) | accepted |
| growth | 0-0.5 | 0.75 (M3); 1.0 (B2, C3, M1) | failed M8: not reviewed |
| edges | 0-1.0 | none | accepted |

Growth is time unattended: 3.7, 5.9, 10.2 and 22 years at 0.25-1.0. Damage carries cracks and rail rust with it.

## Accepted builds, round F

Rulebook 1.2. All 30 single-building rules passed on New, Kept, Typical (seeds 1-3), Worn and
Neglected; the presets passed A4 and each control sweep passed L1, L2 (and K2 for damage) over
the steps it shows. The steps the gate accepts, at Typical's solved gains:

| Control | Accepted | Rejected |
|---|---|---|
| streaks | 0-1 | none |
| edge damage | 0-1 | none |
| grime (soiling) | 0.3-0.5 | 0.1, 0.2 (B3 flat tint), 0.6 (F3 darker base); on the coarse sweep 0 (A2, D1), 0.75 (D1, F3), 1 (D1, F1, F3) |
| stain fields | 0.25-1 | 0 (C3, G4) |

Damage is nested, so a review crop at one place shows the control's progression: the pier
between two windows on the south front (x 923-1323, y 905-1105 at 50 px/m).
