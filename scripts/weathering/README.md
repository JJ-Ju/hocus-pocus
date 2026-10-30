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
| `weather_fields.py` | The generator: a shared cause field, the soiling film, marks (streaks, stains, base splash, algae, rust, cracks, efflorescence, wear, damage), and a solver that sets the soiling gain, film contrast and mark gain to the tone and coverage tables, then checks B2 at full resolution. Damage is nested: hotspots keep a fixed priority and each break its own random stream, so a higher amount keeps a lower amount's breaks and grows them. Breaks are jagged polygons with a 1 px edge, recessed 1–4 cm (the `dmg_h` relief map), stretched along their edge; from 8 cm the bar shows and rust bleeds from the lowest rim. |
| `material.py` | The painted wall's material terms in facade space: coat clouding (more with each repaint) and construction joints; shared by the clean albedo, the weathering, the previews and the engine shader. |
| `closeup.py` | 1 m close-ups at 1 mm per pixel: the facade atlas times the coat set at its own resolution, with the engine's height-lerp, so dirt sits in the coat's troughs. |
| `lit_preview.py` | Lit previews of a weathered building: albedo under a fixed sun and sky, the coat's normal map, joint grooves, break relief. |
| `wx_noise.py` | Seeded Gaussian fields, fBm by scale level, log-normal cascades. |
| `rules_to_md.py` | Renders the rulebook as Markdown. |

## The measures in one paragraph

Everything is measured in facade space at 50 px per metre, row 0 at the top. D = 1 − Y_weathered
/ Y_clean. D_local is the weathering's own local contrast: 1 − (1 − D) / ref, with ref the least
weathered 10 cm patch within ±1 m. Opacity tiers are bands of D_local: T1 ≥ 0.02, T2 ≥ 0.05,
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
