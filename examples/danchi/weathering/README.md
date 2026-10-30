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
```

Run them from this folder. Builds go to `$WX_OUT` (default `./builds`, not committed); use the gains
Typical solved for (`meta.json`, `gains`) so a sweep changes only its control.

Presets: `new` (0 years), `kept` (15 years, upkeep 0.85), `typical` (35 years, upkeep 0.9, the
default), `worn` (35 years, upkeep 0.5), `neglected` (45 years, upkeep 0.12). A build writes one
`<plane>.npz` per facade plane (darkening, each layer's own map, classes, sources, edges, joints,
the material field, clean and weathered albedo), `meta.json` (config, solved gains, coverage,
targets), lit JPG previews, and 1 m close-ups at 1 mm per pixel (`closeup_<plane>_<spot>`).

`entry_images.py` cuts the review images (lit elevations at 2/5 scale and 1:1 crops at fixed
places). `real_planes.py` turns the captures into planes with their features: tops, sill ends,
corner heads, fixings, shelter, flow starts at depth steps, and the construction joints on the
solid walls. `run_proto.py` holds the build loop and the stand-in planes (`facade_synth.py`) used
for fast iteration.

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
