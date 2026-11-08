# Research notes

Research behind the skills (`.claude/skills/`) and the danchi weathering rulebook
(`scripts/weathering/weather_rules.json`, rendered as
`.claude/skills/procedural-materials/references/weathering-rules.md`). Each note cites its sources
and tags its claims: S or L sourced, M measured, I inferred, C a craft estimate, P from photos,
U from the user's reviews.

## Every note ends in actions

A note is finished when each of its recommendations is one of:

- `done (<file or commit>)`: a check or rule with a number that the pipeline runs on what ships, or
  a skill step that says what to do;
- `parked (<reason>; revisit when <trigger>)`;
- `open`: not yet either.

The action table is any table in the note with a `Status` column. Notes written before round J
have no table of their own: the audit's ranked list and its per-note counts stand in for them
(`research-to-practice-audit.md`, "Actions"). A round closes only when

```
python -I scripts/research_actions.py
```

reports no open row. `scripts/skill_lint.py` (run by the unit tests) fails when skill text repeats a
value that a later rule or measurement replaced; add an entry whenever a note corrects a number.

## What round J found missing

The texturing miss of rounds F-I came from judging textures at the generator's own density: an
image at 50 px/m always looks 1:1, so nobody saw that a player at 1 m on a 4K screen gets 1,920 px
per metre. Studios catch this with a metrics sheet that names the nearest approach and the screen,
player-camera reviews and density debug views. The fixes: check T0 (magnification at each surface
class's nearest approach), 1:1 player views first on every review page, and the action tables and
lint above, so research turns into checks instead of sentences.

## Index

**Pipeline, review and standards (round J, 2026-11-07)**

| Note | What it covers |
|---|---|
| `pro-asset-pipeline.md` | The professional pipeline for large modular architecture in UE5 and Godot 4: spec, kits, validation, two builds |
| `art-review-and-qa.md` | How studios catch texel-density misses early: player views, magnification, debug views, motion, definition of done |
| `texture-and-material-standards.md` | Encodings, import settings, mips, streaming and engine limits we had not enforced |
| `surface-detail-techniques.md` | Pro surface-detail techniques (mesh-map masks, paint stacks, rust anatomy, flecks) against our generator |
| `coatings-concrete-corrosion.md` | The physics behind round I's notes: concrete pits and aggregate, paint failure, painted-steel rust, tops and corners |
| `research-to-practice-audit.md` | Which findings of the earlier notes never became a step, rule or check, ranked, with their actions |

**Rust on thin members, the sheen, Decayed (round K, 2026-11-08)**

| Note | What it covers |
|---|---|
| `member-rust-and-geometry-aware-wear.md` | Why runs never showed on 16 mm bars, the Ts first, tarnished metal; patterns keyed to surfaces, grooves |
| `rust-blue-sheen.md` | Rust's blue sheen: dense dark scale reflecting the sky; F0 and roughness under a mask, the engine recipes, the preview |
| `decayed-preset-evaluation.md` | A Decayed level past Derelict: real decay in numbers, a years-vacant control against a sixth preset, a staged plan |

**Texturing at scale**

| Note | What it covers |
|---|---|
| `texturing-at-scale.md` | Texturing very large architecture at game fidelity: carriers, densities, budgets |
| `tiling-and-distribution-algorithms.md` | Hex tiling, height blending, coverage-preserving reveals, scatter |
| `r5-texture-layering.md` | Texture layering, mixing and pattern practice |

**Weathering (the danchi rulebook)**

| Note | What it covers |
|---|---|
| `weathering-water-layers.md` | Water, deposits and growth on panel facades (round I) |
| `weathering-rust-water.md` | Rust on balcony rails: water paths, runs and concrete stains |
| `weathering-organic-growth.md` | Algae, moulds, lichens and mosses (round G) |
| `weathering-cracks-edges-damage.md` | Cracks, edges and damage (round G) |
| `weathering-structural-damage.md` | Structural damage: shrinkage, settlement, bar corrosion (round H) |
| `weathering-grid-breakup.md` | Breaking up the grid in the generator (round G) |
| `r4-weather.md` | How environment and weather act on objects, edges first |
| `r3-clustering.md` | Clustered, caused wear: how artists distribute damage, dirt and detail |
| `r5-wear-simulation.md` | Where simulating wear beats rules, in Houdini 22 |
| `r4-human-industrial.md` | Human contact, traffic and industrial wear |

**Materials and micro detail**

| Note | What it covers |
|---|---|
| `rE-concrete.md` | Realistic concrete textures: values, roughness, relief, traps |
| `r4-noise.md` | Micro noise: non-stationary detail and per-surface patterns |
| `r3-believable-textures.md` | What reads as real rather than procedural |
| `r4-visual-reference.md` | Visual reference study: edges, streaks, metal, touch, micro detail |
| `rR-reference-photos.md` | Reference photos measured for `frame_critique.py` |

**Assets and critique**

| Note | What it covers |
|---|---|
| `r3-believable-assets.md` | Believable assets: construction, clutter, interiors, presentation |
| `r5-meta.md` | Gaps in our research, and a self-critique toolkit for agents |
| `rA-critique-results.md` | `frame_critique.py` on the danchi renders (round A) |

**Styles and scoping**

| Note | What it covers |
|---|---|
| `rC-anime-background.md` | 1980s-90s anime urban backgrounds, and the look from 3D (an optional mode; realism is the default) |
| `rD-painterly-surface.md` | Painterly surface treatments that ship to an engine (deferred by the user) |
| `vine-growth-generators.md` | Scoping a vine generator (parked: vines are rare on public housing) |
