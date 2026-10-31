# Weathering by rule

Numeric rules for building weathering, a generator that builds weathering layers in facade space,
and a gate that accepts or rejects a weathered building against the rules. Nothing is shown for
review until the gate accepts it.

The rules are in `weather_rules.json`, rendered for reading as
`.claude/skills/procedural-materials/references/weathering-rules.md` (`rules_to_md.py`).

## Files

| File | What it does |
|---|---|
| `weather_rules.json` | The rulebook: measures, presets, tone and coverage tables by the soiling clock E, the rules, and every revision with its evidence. |
| `weather_measure.py` | The measures: darkening D, local contrast D_local, opacity tiers T1–T6, scale levels S1–S8, band energy, clustering, marks, material bands. numpy only. |
| `weather_gate.py` | `check` one weathered building, or `series` over presets or a control sweep. Exit code 0 only when accepted. |
| `gate_g.py`, `gate_m.py`, `gate_c.py`, `gate_p.py`, `gate_k.py`, `gate_n.py` | Round-G rules the gate imports: streaks (G5, H4, H5, L3, L4), growth (M1-M8), colour variety (I3), no accidental lattice (G6), damage (K5-K11) and edges (N1-N5). |
| `test_noise.py` | Unit test for the noise: no lattice or edge excess in `gfield` (G-3), pattern fields restart from storey to storey (G-2). |
| `weather_fields.py` | The generator: a shared cause field, the soiling film, marks (streaks, stains, base splash, algae, rust, cracks, efflorescence, wear, damage), and a solver that sets the soiling gain, film contrast and mark gain to the tone and coverage tables, then checks B2 at full resolution. Growth is nucleation and outward fronts timed by the growth research's wetness classes; cracks run from hairlines to pattern cracks with T junctions, widths tapering and repairs; spalls reach the derelict share at 1.0; edges read through their 1 px row; dirt takes a palette of warm dust, soot and damp green-grey. The coat tile is sampled per plane (tile-and-blend) and the laps follow the scaffold lifts, so nothing repeats every 3.6 m. Channel streaks follow a power law from 3.5 m and stop within three storeys (7.5 m); each wall's main water path, a faint film, runs most of its height on solid wall. A source's extra runs split into rivulets a few cm apart, most runs stop short of the next drip edge, and a higher streak amount adds and widens runs more than it darkens them (C3, H5, L4); on wet walls (streak amount over 0.4, fully from 0.55) half the ordinary channels start at a floor line instead of the top of the wall, so heavy streaking does not pile into the top storeys (D1). Deposits in the soiling film are grainy inside, the grain following the coat's own texture so the dirt sits in the material (B2, J2); the foot takes splash soil that scales with the grime (F3). Damp bands under edges break at drip points; corner cracks keep 45 degrees for 0.5-1 opening width before turning vertical; growth tints a dirty wall but never brightens it, ink stripes run on the streak paths (not on south faces, which grow moulds) and dry films keep their family's hue (M1, M2). The edge band runs along 48 % of each edge at 0.25; above that each step of 0.25 widens it 1.27x and deepens it 1.1x, so every step adds coverage and shows (N1, N2, L1, L2). The solver checks B1 and B3 at full resolution, keeps B2 a margin inside its thresholds and keeps J2 (dirt following the material) at 0.255 or more, so the sweeps at Typical's gains do not fall off the edge. Damage is nested: hotspots keep a fixed priority and each break its own random stream, so a higher amount keeps a lower amount's breaks and grows them. Breaks are jagged polygons with a 1 px edge, recessed 1–4 cm (the `dmg_h` relief map), stretched along their edge; from 8 cm the bar shows and rust bleeds from the lowest rim. |
| `material.py` | The painted wall's material terms in facade space: coat clouding (more with each repaint) and construction joints; shared by the clean albedo, the weathering, the previews and the engine shader. |
| `closeup.py` | 1 m close-ups at 1 mm per pixel: the facade atlas times the coat set at its own resolution, with the engine's height-lerp, so dirt sits in the coat's troughs. |
| `lit_preview.py` | Lit previews of a weathered building: albedo under a fixed sun and sky, the coat's normal map, joint grooves, break relief. |
| `wx_noise.py` | Seeded Gaussian fields, fBm by scale level, log-normal cascades. |
| `rules_to_md.py` | Renders the rulebook as Markdown. |

## The measures in one paragraph

Everything is measured in facade space at 50 px per metre, row 0 at the top. D = 1 − Y_weathered
/ Y_clean. D_local is the weathering's own local contrast: 1 − (1 − D) / ref, with ref the least
weathered 10 cm patch within ±1 m (arris rows and the edge layer left out: the edge rules measure them). Opacity tiers are bands of D_local: T1 ≥ 0.02, T2 ≥ 0.05,
T3 ≥ 0.10, T4 ≥ 0.18, T5 ≥ 0.30, T6 ≥ 0.45. Scale levels are octaves of feature size, S1 16–32 m
down to S8 12.5–25 cm. The soiling clock is E = R + 0.22 (age − R), where R is the years since
the last repaint (cycle = lerp(24, 7, upkeep) years). Amount tables are given at the five presets'
E and interpolated between them.

## Running it

```
python -I weather_gate.py check <config_dir> [--json out.json] [--sweep] [--allow-na]
python -I weather_gate.py series presets <new> <kept> <typical> <worn> <neglected>
python -I weather_gate.py series sweep:<layer> <dir_0> <dir_0.25> <dir_0.5> <dir_0.75> <dir_1>
python -I rules_to_md.py weather_rules.json ../../.claude/skills/procedural-materials/references/weathering-rules.md
```

A config folder holds one `<plane>.npz` per facade plane and a `meta.json`; see the docstring of
`weather_gate.py` for the arrays. The danchi example (`examples/danchi/weathering/`) builds such
folders for the round-7 building.

Set `WX_TEX` to the folder with the round-E coat set (default: `examples/danchi/tex/round_e`).
