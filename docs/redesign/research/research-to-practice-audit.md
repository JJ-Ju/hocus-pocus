# Research-to-practice audit: findings that never became a step, rule or check

**2026-11-07, after round I.** This audit asks whether the findings in the 24 research notes in
`docs/redesign/research/` were put into practice. It checks them against four sources: the four skills
(`procedural-assets`, `procedural-materials`, `procedural-mesh-damage`, `large-scale-texturing`, with
their SKILL.md files, references and scripts); the rulebook `scripts/weathering/weather_rules.json`
(1.6: 78 rules, 71 revisions); and the two READMEs (`scripts/weathering/README.md`,
`examples/danchi/weathering/README.md`). Code in `scripts/weathering/` was read only to confirm what a
check does. The audit was prompted by the user's round-I verdict that the texturing was "a big miss".
The findings that would have caught it were already in `r5-texture-layering` and `r5-meta`, but they
never became a step, a rule or a check.

Each finding gets one of four labels:
- **applied**: a skill step, rule or check uses it;
- **partial**: it is mentioned but not enforced, or only part of it is used;
- **not applied**;
- **superseded/contradicted**.

Two flags qualify a label. *[danchi-gate only]* means the check runs only in the danchi facade gate. *[never run]* means the skill says it has never been run.

The notes were read in full, in parallel batches. The top-ranked claims were then re-checked in the files: the shader lines, the export's decal kinds, the gate's modes and the rules' pass texts. The counts depend on how findings were grouped, so read them as proportions.

Shorthand used below:
- **LST** is `large-scale-texturing`.
- **Both shaders** means `large-scale-texturing/scripts/layered_facade.gdshader` and `layered_facade_ue.hlsl`.
- **The mirror** is the numpy engine-mirror compositor `wx_hires.py`.
- A script named without a folder is in `scripts/weathering/`.

## Summary

1. **Most findings were written down but never enforced.** The 24 notes hold about 615 actionable
   findings:
   - about 23 % are applied;
   - about 48 % are partial, mostly advice with no check;
   - about 17 % are not applied;
   - about 11 % are superseded or contradicted.

   About half of the applied ones are rules that run only in the danchi facade gate, on albedo at
   50 px/m.
2. **The texturing miss has a successor: the engine path.** Round I designed the right split, but only
   the numpy mirror builds it. Neither shader has run in an engine. They differ from the mirror in ways
   no review image can show:
   - every mark becomes a 62.5 % speckle with edges as soft as the mask (the shaders compute pk as 1.6 × the mask value);
   - reveal details go through plain mips;
   - the coat normal repeats every 3.6 m, and Unreal gets no normal at all;
   - the Unreal graph works in metres.

   There is no parity check, and no shader contract file (ranks 1 to 1d).
3. **The gate accepts layers that never ship.** None of these has an export carrier: damage, spalls and
   their relief, short and horizontal cracks, edge wear, peeling, washed streaks, and black growth. No
   trim sheet, decal atlas or per-class material set was ever made (ranks 2–3).
4. **Only albedo is weathered.** All 78 rules, T1–T3 included, measure albedo. Roughness, normal and
   height from causes appear in five notes as advice only. The shaders' roughness is 0.88 − 0.25 × damp,
   and every preview is diffuse-only, so no review could have shown the gap (rank 4).
5. **The research answered the user's complaints, but the answers were not used or were weakened.**
   - The structural-damage note is 0 of 10 rules applied. K7 still asks for an amount of crack length
     that the generator meets with the webbing the user asked to reduce.
   - The water-layers rules for area growth, Derelict spread and colour flips went in at about half
     strength, with no revision to say why (ranks 5–7).
6. **Some checks exist but nothing runs them.** No pipeline calls `wx_texcheck.py` (T1–T3),
   `wx_export.py`'s budgets, `test_noise.py` or `frame_critique.py`. The `weather_gate.py texture` mode
   that `wx_texcheck.py` names does not exist (ranks 9, 11).
7. **Why it happened:**
   - The gate sees one channel of one building.
   - Review images come from stand-in renderers that hide the next defect.
   - 13 of 24 notes are not linked from any skill, rule file or README by their file name.
   - Deferrals live in session memory, not in the repo.
   - Weaker adoptions leave no revision.

   Five process changes follow, starting with an action table at the end of every note.

## Ranked unapplied findings

Ranks 1–13 are high impact: they show in ordinary review views or break in the engine. Ranks 14–26 are
medium. Ranks 27–29 are decisions that still have to be made.

| Rank | Finding | Source note and section | Finding status | What would apply it | Target file |
|---|---|---|---|---|---|
| 1 | The engine path has never run, and nothing compares it with the review images. Neither shader has run in Godot or Unreal. Parity (ΔE00 ≤ 2) is a table row with no code. The `shader_contract.json` both shaders cite does not exist. The mirror composes from the generator's float stack, not from the exported masks | texturing-at-scale §10.8–10.9 (T8); r5-texture-layering §6; rD-painterly-surface §8 | partial [never run] | A release check: a Godot 4 headless render of one golden crop per surface class against the mirror, with mean ΔE00 ≤ 2 and normal angle ≤ 5°. Write the contract and generate both shaders' constants from it. Make the mirror read the export folder | LST SKILL.md › Checks; a new parity script; `wx_hires.py`; both shaders |
| 1a | The shaders' edge rule computes pk = clamp(1.6·a, 0.05, 1). For masks of 3–62 % every mark becomes a 62.5 % speckle with edges as soft as the 2 cm mask, which is the blurry-blob failure LST was written to prevent | texturing-at-scale §5, §10.8 | contradicts LST › The edge rule [never run] | Export the 10 cm smoothed local maximum per channel and use it as pk. Check with a parity crop across a stain edge | `wx_export.py`; `layered_facade.gdshader` lines 180–193; `layered_facade_ue.hlsl` |
| 1b | The shaders sample differently from the mirror. Reveal details use plain engine mips, so a 10 % layer covers about 2 % by mip 2. There is no `textureGrad`/`SampleGrad`, so mips seam along hex cells. There is no `fwidth` floor on edge width. Masks are bilinear from 8-bit, so edges kink | tiling-and-distribution-algorithms §1, §2 (Width, distance and mips), §5; weathering-grid-breakup §1.3, §2; r5-texture-layering §5 | partial (numpy only) | Ship re-equalised mip chains or a per-LOD LUT, with cover checked to ±0.01 per mip. Sample with rotated derivatives. Keep the edge width ≥ fwidth(h). Upsample masks with a 4-fetch B-spline from 16-bit | `wx_export.py`; both shaders |
| 1c | Normals. Godot samples the coat normal plain-tiled every 3.6 m, beside a hex-tiled albedo. The Unreal graph has no normal. There is no micro normal. A facade-projected normal goes into the tangent-space slot with no basis | r5-texture-layering §1.4; tiling-and-distribution-algorithms §1 (Normals); rE-concrete §2.6; rD-painterly-surface §8 | partial/contradicted [never run] | Hex-sample the coat and micro normals with the albedo's weights, blended as slopes. Build the tangent basis from the facade axes. Run T2 on the normal channel (≤ 0.15) | both shaders; `wx_texcheck.py` |
| 1d | Unreal units and colour space. Unreal works in centimetres with Z up, but the HLSL graph and concrete.md's macro factor assume metres: there is no ÷100, so the 8–25 m fade ends at 25 cm. No rule turns sRGB off for masks, growth stage and detail fields, so a 0.5 mask reads 0.21 | rD-painterly-surface §5.5 | not applied/contradicted | Add a units-and-axes line, plus an import table (sRGB, compression) for each texture class | LST SKILL.md › Engine hookup; `layered_facade_ue.hlsl`; concrete.md › Engine path |
| 2 | Layers the gate measures have no engine carrier: breaks, spalls and their relief; every crack under 0.30 m tall, which is every horizontal crack; edge wear (exported in M_lo.A, read by neither shader); peeling and washed streaks (never drawn); growth black (the ramp has no black stop, so ink stripes ship dark green). Each rust run is one box | weathering-cracks-edges-damage §7.3–7.4; weathering-structural-damage §5.2 (step 5); texturing-at-scale §6, §10.5; r5-texture-layering §1.2; weathering-organic-growth §1.3 | partial/not applied | A carrier check: every layer the gate measures or the mirror draws needs a mask channel, a decal kind with an atlas cell, or a trim, or the export fails. Also check growth ΔE00 ≤ 3 between export and build | `wx_export.py`; `wx_texcheck.py`; both shaders |
| 3 | No trim sheet, decal atlas or per-class set was made, and no step or check requires one. In the engine, bevels, copings, slab edges, drip grooves, 20 × 10 mm joints and sills are plain wall. The detail tiles exist only as numpy caches. Copings and soffits use the wall coat, against the finish-per-element rule | texturing-at-scale §3, §6, §8, §10.1–10.5; rE-concrete §1.1 (Table 1), §1.8 | partial (described only) | A gate: every edge face maps to a trim strip at 1,024 px/m ±25 %; every surface class has a named set; every decal kind has an atlas cell. Export the tiles | procedural-materials `scripts/`; LST SKILL.md › The method; `wx_export.py` |
| 4 | Only albedo is weathered. No rule measures roughness, normal or height. No roughness map is exported. The shaders use 0.88 − 0.25 × damp. Every preview is diffuse-only | r3-believable-textures §1; r5-texture-layering §1.5; rE-concrete §1.6; weathering-organic-growth §5 (O15) | partial (advice) | Rule J3 on the exported ORM: p5–p95 ≥ 0.06 per wall; damp −0.05 to −0.15; dust +0.05 to +0.1; repaint −0.05 to −0.1; growth by subtype. Add a GGX specular term to the mirror | `weather_rules.json`; `wx_export.py`; both shaders; `wx_hires.py` |
| 5 | The structural-damage note was never applied: K12–K21 and the K7 revision (0.8–2.0 m/m² of cracks at 1.0, not 1.5–3.5). K12–K21 cover: storey-long chains; webbing at most 0.3 × chain length at 1.0; surface loss along cracks; spall patches; exposed bars; visibility (K19); one crack graph shared by texture and mesh (K20); chunks (K21). The generator meets K7 by seeding pattern-crack webbing from amount 0.35 and caps cracks at 2.5 m | weathering-structural-damage §5.5, §6.1–6.2; weathering-cracks-edges-damage §8.2 (C3, C4) | not applied/contradicted | Now: revise K7 and add K14, so the gate stops rewarding webbing. Then build the crack graph, K12–K21 and the tracer, or record a decision to park them | `weather_rules.json`; `gate_k.py`; `weather_fields.py` |
| 6 | The water-layer rules went in at about half strength, with no revision (the note's values in brackets): L5 ×1.15 and +5 cm (×1.3 and +0.1 m; L5's own origin cites ×1.3–1.6); H6 0.3 m and 40 % (0.15 m, 0.50–0.70); I5 lets 8 % go back (2 %); A1 Derelict T2+ 0.50 and T3+ 0.28 (0.60, 0.32); Kept T5+ up to 1 % (0.3 %). These are the rules behind the user's "not expanding", "too light" and "flipping" complaints | weathering-water-layers §5.3, §7 (V2–V5) | superseded (weaker), unrecorded | Adopt the note's numbers, or record each change as a revision with its reason. Re-gate round I's accepted builds | `weather_rules.json`; `gate_i.py` |
| 7 | Growth per preset is unchecked. No rule sets growth area by E: Derelict north faces are about 10–16 %, an estimate, against the note's 30–60 %. The wet map is never validated: W2–W3 cover 5.6 % of the wall against 10–26 %, and there are no downpipe, scupper or AC sources. G4 has no cover clause, and it blocks the growth control (which has failed from 0.5 up in rounds G to I). The calibration plan never ran, yet every band is binding | weathering-organic-growth §2.2, §3.3, §5 (O4), §6 | partial/not applied | A rule for north-plane growth at T2+ by E. A wet-map check per plane (W3 2–6 %, W2 8–20 %). Give G4 the cover clause M3 has. Mark uncalibrated clauses advisory until photo calibration | `weather_rules.json`; `gate_m.py`; `weather_fields.py` |
| 8 | Texel density is checked only on the danchi detail tiles. T1 reads tile files, and it exempts the 569 px/m coat base. Nothing measures exported UVs, trims, decals, props or bakes; round D's bake was about 342 px/m against a 512 px/m contract | r5-texture-layering §5; texturing-at-scale §2, §10.10 (T1); rD-painterly-surface §5.2; r5-meta §1 (gap 13) | partial | A gate item at phases 3, 5 and 7, measured from exported UVs: 1,024 px/m ±25 % (512 for third person), neighbours within 1.25×, bakes at or above the contract. Drop the coat-base exemption | procedural-assets SKILL.md › 3, › 5, › 7; hocuspocus-recipes.md; `wx_texcheck.py` |
| 9 | The texture checks sit outside the gate. T1–T3 run by hand. The note's T5–T8 are missing: decals (≤ 0.5/m², ≤ 3 deep), distance (the 40 m mip within 2 %), memory (≤ 40 MB unique, ≤ 128 MB shared; 10 and 28 on Mobile) and parity. `wx_export.py` reports budgets but judges none. T2's 4 × 4 m windows are too small for the 3.6 m and 4.1 m tile periods | texturing-at-scale §10.10–10.11; tiling-and-distribution-algorithms §4 | partial | Add the `texture` mode and call it from the pipeline before any review page. Add T5–T8. Use windows of at least 4 periods, fail any period that cannot be tested, and add a blind ACF check (≤ 0.2) | `weather_gate.py`; `wx_texcheck.py`; `pipeline_i.py` |
| 10 | Facade damage never reaches the geometry, and derelict elements are absent. Breaks ≥ 30 mm are not handed to `chip_points_edge`. Kit chips follow the round-7 formula, not K5/K6. There are no bent rails, missing balusters, broken panes (70–100 % at 1.0) or broken partitions | weathering-cracks-edges-damage §7.4 (step 8), §8.3 (S12), §8.4 (X2–X6); weathering-structural-damage §5.3 (K20, K21) | not applied | Export breaks ≥ 30 mm as cutter points. Add K20: ≥ 0.9 of mesh loss lies within 4 cm of a graph spall. Add a derelict stage with its own rule family | `wx_export.py`; procedural-mesh-damage SKILL.md › Workflow; `weather_rules.json` |
| 11 | The photo-calibrated picture tests never run on the images the user reviews or on what ships. `frame_critique.py` (value range, saturation, micro floor, reference match) runs only on Karma looks. No weathering script calls it, and it has not changed since round R | rR-reference-photos §2, §6; rA-critique-results (Summary) | not applied (for what ships) | Run value_range, saturation_budget and the micro floor on every review crop, with the mask taken from `cls`. Run the full set on lit elevations and engine renders | `render_review.py`; LST SKILL.md › Checks; procedural-assets SKILL.md › 7 |
| 12 | Rail rust has no engine carrier. At 50 px/m rails are 1–2 px wide, balusters under 1 px, and top faces don't show in elevation, yet R3–R6 measure those pixels. In the engine the rails get a planar facade mask. The presets' steel clock is also low: Derelict has rust on about 14 % of the steel, against about 41 % (Ri 5) on the note's repaint cycle (an estimate) | weathering-rust-water Conventions, §1.1–1.2, §5, §7.1 (rule 11) | not applied | Run the arrival-time model on the rail mesh, and store rust age per vertex or in a rail-UV mask. Put a steel clock in the presets and add a preset clause to R1 | `wx_export.py`; texturing-at-scale.md › The stack per wall; `weather_fields.py` |
| 13 | There is one mask set per plane, so walls, doors and windows behind parapets read the parapet's masks in oblique views | texturing-at-scale §10.2 | partial (advice) | Weather a second, recessed layer (L1) from depth and shelter. Export `_L1_` masks (25 px/m, about +6 MB); the shaders pick a layer by id. Check with an oblique parity crop | `weather_fields.py`; `wx_export.py`; both shaders |
| 14 | There is no use layer: touch at code heights (latch band 0.9–1.5 m, handrails 865–965 mm, lift buttons), the few hot points holding 70–85 % of the wear, floor lanes, stair dishing. Review 31's mismatch #5, "There is no touch layer", is still true | r4-human-industrial §1, §5, §6; r4-visual-reference §4; r5-wear-simulation §5 (d) | partial (prose; its "Checks:" line never runs) | Plan-stage `interaction` points and a `traffic` field; a touch mask channel. Rule U1: ≥ 80 % of touch wear inside each kind's code band, with the top 20 % of points holding 70–85 % | generator-architecture.md; `weather_fields.py`; both shaders; `weather_rules.json` |
| 15 | Grain stationarity and the stucco signature are not checked on the fine composite. Micro stationarity is reported as `info` only. The round-E coat's kurtosis (3.1) fails concrete.md's own ≥ 4. Nothing checks the spectrum slope of a wall crop | r4-noise §6; rA-critique-results (Micro non-uniformity); rE-concrete Summary, §1.3, §2.5 | partial | A T4 check on the plain-wall window at 1,000 px/m: local-std CV ≥ 0.2, p90/p10 ≥ 3, kurtosis ≥ 4, spectrum slope < −0.1 at 3–48 mm | `wx_texcheck.py`; `weather_rules.json` (J1) |
| 16 | The skill text contradicts later rules (correct value in brackets): micro p90/p10 "3–6" in four passages (photos run 3–30, median 12.5); "70–80 % within ±3 %" (A1); normal strength "1.5–3×" and cop_lib's default 2.0 (×1.0–1.5); fresh-concrete roughness 0.75–0.95 (0.55–0.7); "half to two thirds of each edge clean" (N2: 85–100 % at 1.0); rust runs that fan out (R5: they narrow); "No crack starts mid-face"; layering.md's biased MaterialX R1 row | rR-reference-photos §3.8; r3-believable-textures §5; rE-concrete §1.6; r3-clustering §3; weathering-rust-water §3, §6; weathering-structural-damage §2.2; tiling-and-distribution-algorithms §2 | contradicted | One pass to reconcile the text, then a lint that fails on the old values | procedural-materials SKILL.md; procedural-mesh-damage SKILL.md; art-direction.md; micro-noise.md; realism.md; weather-and-use.md; layering.md; `cop_lib.py` |
| 17 | Some layers are named but never drawn. `peeling` and `washed` appear in the layer list, I2 and G3, with amount tables, but no function draws them, so G3 passes trivially. Repaint patches are off in every preset | r4-weather §4; r4-visual-reference §3; r3-believable-assets §2; rE-concrete §1.1 | partial (stubs) | Draw the layers and add rules: ≥ 70 % of peeled area within 0.3 m of a water source, panel bottom or lock edge; 1–3 repaint patches per front, 0.5–4 m², ΔL 2–5 %. Add a gate test that each listed layer has pixels at its preset amount | `weather_fields.py`; `weather_rules.json` |
| 18 | Windows and dressing are never counted. The note's bands: pane tilt 0.05–0.3°; sash states 60/30/10 %; lace curtains in 70–90 % of flats; 2–10 % of flats vacant; clutter on 60–80 % of balconies; AC units in 50–80 % of bays | r3-believable-assets §1, §3, §4 | partial (reference tables) | Count checks on the plan at the phase 4 and phase 6 gates. A per-pane normal spread ≥ 0.1°, set by per-instance rotation | procedural-assets SKILL.md › 4, › 6 |
| 19 | Some surfaces are invisible to the elevation gate: glass (run-off at frames, water-spot rings), horizontal tops (dust ∝ N.y²), soffits, and the inner faces of parapets | r4-noise §4; r4-weather §2, §5, §6; r4-visual-reference §2, §6; r3-believable-textures §1 | partial | Classes or planes with rules: the bottom 10 % of glass ≥ 1.5× its middle; soffit CV ≤ 0.5× the open wall's; a fringe on inner faces. Add N.y² dust in the shaders | `real_planes.py`; `weather_rules.json`; both shaders |
| 20 | There is no moss, and growth has no relief or sheen. The note gives moss cushions of 5–20 mm on ledges after 8–15 years, and roughness 0.60–1.0 and height 0.3–20 mm by subtype. weather-and-use.md puts lichen on "damp, shaded tops"; the note puts it on sunny faces sheltered from run-off | weathering-organic-growth §1.1–1.2, §3.7, §5 (O15) | not applied/contradicted | A moss subtype with a relief carrier, and a rule: ≥ 90 % within 5 cm of ledges and joints. Per-subtype roughness. Fix the lichen line | `weather_fields.py`; both shaders; weather-and-use.md |
| 21 | Cracks and edges at close range. In 1:1 crops a crack is the 2 cm mask revealed against generic noise, with no true-width core, halo, lips, groove or roughness. No corrosion cracks run along noses and bars. The user called the middle edge-wear steps "too subtle" in round G, and no N rule was revised | weathering-cracks-edges-damage §3.1–3.6 (C20, C22), §5.5, §8.1; weathering-structural-damage §5.2 | partial/not applied | Draw cracks from their polylines at review density: core within ±50 % of `crk_w`, halo ΔL* 5–15. Add a bar-line crack kind with rule C22. Recalibrate N1–N3's middle bands on a user pick | `wx_hires.py`; `wx_texcheck.py`; `weather_fields.py`; `gate_n.py` |
| 22 | Facade stories and undamaged instances. The note asks for 3–7 clusters per facade, each with a typed cause; but the cause field is stationary noise and hotspots carry no cause type. `cluster_mask.vfl` always places a strength-1 hotspot, so "30–50 % of instances undamaged" cannot happen | r3-clustering §2, §4A, §4D, §5 | partial | A rule: 3–7 hot regions per front at 30–60 m, each over a typed cause. A per-instance draw that can give zero hotspots, checked at 0.3–0.5 undamaged per piece type | `weather_fields.py`; `cluster_mask.vfl`; procedural-mesh-damage SKILL.md › Workflow 12 |
| 23 | Shader terms and instance data are missing: a world macro at two incommensurate scales (about 9.7 m and 31 m); a per-panel and per-bay tint; per-instance custom data (UE custom floats, Godot `INSTANCE_CUSTOM`) | texturing-at-scale §4, §8; rE-concrete §1.8, §2.4; r3-believable-textures §3; weathering-grid-breakup §4 (R6) | partial | Add the terms. On the engine crop, check S1–S3 band std ≥ 0.03 and per-bay tone std of 1–3 % | both shaders; `wx_hires.py`; game-output.md › Engine attributes (Houdini Engine) |
| 24 | Engine limits are not encoded. Godot's Compatibility renderer has no Decal nodes. A mask side over 4,096 px (a facade over 81.9 m at 50 px/m) breaks Mobile and web. Masks are not padded to a power of two. 8-bit vertex colour clamps at 1 | texturing-at-scale §6, §7; rD-painterly-surface §5.3 | partial | The export fails on a side over 4,096 (split it, or use 25 px/m) and pads masks. Add a vertex-data encoding check | `wx_export.py`; LST SKILL.md › Engine hookup; game-output.md › Export routes |
| 25 | GPU cost and motion. There is no runtime budget: the Godot shader uses 13 samplers and 5 layers, where the notes say ≤ 4 layers. Specular aliasing is not handled (Toksvig or Composite Texture). Nothing is reviewed in motion for shimmer | r5-texture-layering §1.6, §5; rE-concrete §1.2; tiling-and-distribution-algorithms §1; rD-painterly-surface §8; r5-meta §2 (T12) | partial/not applied | A budget row: ≤ 4 revealed layers, ≤ 16 samplers, GPU ms measured at the first engine run. Toksvig roughness mips. A 2 s camera move at each level gate | LST SKILL.md › Checks; `wx_export.py`; procedural-assets SKILL.md › 6 |
| 26 | Generators are judged on one seed and on in-sample picks. Expressive range (≥ 50 seeds) and the `--grid` seed spread are not in the phase 8 gate. Hold-out picks never ran, so the binding thresholds are scored on the same picks they were fitted to. A new subject gets the danchi and Tokyo limits | r5-meta §2 (T11); rA-critique-results (Seed spread); rR-reference-photos §2, §4.1, §5 | partial | Phase 8: ≥ 50 seeds; fail on collapse (metric CV < 0.05) or when ≥ 5 of 9 tiles fail one test. Phase 0: a photo set per view. A hold-out pick round before any threshold moves | procedural-assets SKILL.md › 0, › 8; art-direction.md › 5 |
| 27 | Vines have no place in the skills: no foliage carrier, delivery, LOD, budget or gate. None of the note's 10 design steps was done | vine-growth-generators §3, §5 | not applied | Decide. Either park them with the note's own reason (vines on public housing are rare: 2 of 827 sites) and a trigger to revisit, or add `references/vines.md` with the §3 delivery table and the V1–V8 gate | procedural-assets SKILL.md; a new `references/vines.md` |
| 28 | The rulebook is hard to trace. It cites `roundG/research/*.md` 22 times, which is not a repo path. Estimates are tagged L. All 78 rules are binding, with no advisory state. The revisions claim "O1–O12", "C1–C23" and "E5–E9", but 9 of 12 O rules (2 in part), 7 of 23 C rules and 4 of 5 E rules went in | weathering-cracks-edges-damage (header, §9); weathering-organic-growth §5–6 | partial | Fix the paths. Add a `status` field (binding or advisory). Tag estimates with origin C. Correct the revision text | `weather_rules.json`; `rules_to_md.py` |
| 29 | Items to park explicitly: industrial wear (racks, docks, forklift floors); the painterly surface layers (brush strokes, Ruan Jia rules, hue drift; the user deferred them, but no repo file says so); research-grade metrics (DISTS, saliency, inverse fitting) | r4-human-industrial §4, §6; rD-painterly-surface §2–4; r5-meta §1 (gaps 14, 16) | not applied | One parked row per item, with its reason and a trigger to revisit | each note's action table; stylisation-anime.md › 1 |

## Applied findings

Counts per note, from the audit tables ("sup." = superseded or contradicted):

| Note | Findings | Applied | Partial | Not | Sup. | Linked from, by file name | Own action list |
|---|---|---|---|---|---|---|---|
| r3-believable-assets | 27 | 8 | 15 | 0 | 4 | none | none (closing critique table: 3 of 8 rows checked) |
| r3-believable-textures | 30 | 7 | 18 | 0 | 5 | none | none (failure table: 4 of 10 enforced) |
| r3-clustering | 24 | 16 | 6 | 1 | 1 | none | §5 Checks: 1 of 3 |
| r4-human-industrial | 17 | 0 | 15 | 2 | 0 | none | §6 rules: 0 of 17 checked |
| r4-noise | 21 | 5 | 11 | 0 | 5 | `frame_critique.py` | §7 fixes: 3 of 6 |
| r4-visual-reference | 25 | 8 | 13 | 1 | 3 | none | mismatch list: 6 of 9; #5 open |
| r4-weather | 29 | 11 | 13 | 2 | 3 | none | §7: 4 of 11 |
| r5-meta | 26 | 6 | 17 | 3 | 0 | critique_questions.md, `frame_critique.py` | §3: R5 and R6 done, R7 in part; follow-ups 0 of 3 |
| r5-texture-layering | 29 | 10 | 14 | 1 | 4 | layering.md | none (§7 fixes: 4 of 9 checked) |
| r5-wear-simulation | 21 | 6 | 13 | 0 | 2 | wear-simulation.md | none; recipes 0 of 7 run |
| rA-critique-results | 17 | 2 | 8 | 2 | 5 | none | none |
| rR-reference-photos | 18 | 9 | 2 | 6 | 1 | art-direction.md, realism.md, `frame_critique.py` | §3–4: 11 of 11 in the script; skill text not updated |
| rC-anime-background | 23 | 5 | 7 | 3 | 8 | stylisation-anime.md, `build_anime_post.py` | §5: 1 of 2 |
| rD-painterly-surface | 27 | 4 | 12 | 11 | 0 | none | §8: 1 of 8, in part; deferral not in the repo |
| rE-concrete | 39 | 8 | 18 | 2 | 11 | concrete.md | §2.7 traps: 8 of 8; §2.8 open items: about 1 of 7 |
| texturing-at-scale | 35 | 5 | 23 | 4 | 3 | LST SKILL.md and reference, rule T1 | §10.11: 0 of 7 in full; T1–T8 became 3 |
| tiling-and-distribution-algorithms | 30 | 6 | 15 | 7 | 2 | LST SKILL.md and reference, rule T2, `wx_texcheck.py` | §0 table: 1 of 6 |
| vine-growth-generators | 16 | 0 | 0 | 16 | 0 | none | §5: 0 of 10 |
| weathering-cracks-edges-damage | 41 | 6 | 23 | 10 | 2 | none (cited as `roundG/research/…`) | §8: 12 of 60 rules |
| weathering-grid-breakup | 17 | 3 | 9 | 5 | 0 | none (cited as `roundG/research/…`) | §4–5: 2 of 8 in full |
| weathering-organic-growth | 28 | 6 | 15 | 6 | 1 | none (cited as `roundG/research/…`) | §5: 7 of 15 rules, 2 in part; §6: 0 of 4 |
| weathering-rust-water | 15 | 6 | 3 | 5 | 1 | weathering-rules.md, wear-simulation.md, scripts README, `gate_r.py` | §7: 13 of 15 |
| weathering-structural-damage | 38 | 3 | 17 | 17 | 1 | none | §5.5: 0 of 6; §6.1: 0 of 10 |
| weathering-water-layers | 22 | 3 | 11 | 2 | 6 | rulebook, by name with no path | §6–7: 2 of 19 in full |
| **Total** | **615** | **143** | **298** | **106** | **68** | | |

What is applied, and where:

- **r3-believable-assets:**
  - History events, in procedural-assets SKILL.md › 6. Up the levels ("History").
  - Unit personas, soft goods and muted props, in › 4. Golden bay, with the `saturation_budget` test.
  - Scale and ground context, a sun 15–35° high and eye-height lenses, in › 9. Final review, with `frame_critique` `camera` (bare-plane and void fails).

  These are steps, but none has a check.
- **r3-believable-textures:**
  - Dirt as a colour: I1, I3, I4, I6.
  - Rust bloom to run: R1–R6.
  - Streams at recurring spots: G1, G5, H6.
  - Splash zone: F3, M4.
  - A background floor: A2, and `cluster_mask.vfl` background 0.12.
  - One cause field: `weather_fields.py`, G4, M3, R3.

  All of these are [danchi-gate only].
- **r3-clustering:**
  - 80/20 with a background: procedural-assets SKILL.md › Distributing detail: clusters with a background.
  - The hotspot field, power-law sizes, exposure weights and the 0.3–1.2 m contact band: `cluster_mask.vfl` and `chip_points_edge.vfl` (procedural-mesh-damage SKILL.md › Workflow 2, 4).
  - Bevels widened only around hotspots: › Workflow 5.
  - Rest areas: the binding `detail_density` test.
  - 7 of 9 failure modes: as › Traps entries or as A/B questions.
- **r4-human-industrial:** nothing applied. Its tables were copied as prose into weather-and-use.md
  › People: touch points come from building codes, and causes.md › Use and industry: where strikes land.
- **r4-noise:**
  - Multiplicative cascades: `wx_noise.lognormal`, checked by C1/C2.
  - Bug holes at lift tops: `micro_fields.vfl`, and concrete.md › Checks.
  - Crack causes: K8, K9.
  - Rust by ISO grade: R1.
  - Hex tiling: T2.
- **r4-visual-reference:**
  - Counting recurring features in photos: procedural-assets SKILL.md › 0. Brief, reference, de-risk.
  - Chip runs, one face losing, no opposite removals: `chip_points_edge.vfl`, and `damage_measure.vfl` `flank_runs` = 0.
  - Every streak starts at a feature: G1 and `streak_sources.vfl`.
  - Sill V-fans and fringes only on tops with no drip: `streak_mask.vfl`, F2.
  - Rail rust at tops, joints and feet: R3, R5.
  - Dirt in coat troughs: J2.
- **r4-weather:**
  - Edges first: procedural-materials SKILL.md › What makes it read as real 8, K3 and N1–N5.
  - Chip mechanics and the corner boost: `chip_points_edge.vfl`.
  - 90 % of damage within 40 mm of the edge, face pits ≤ 0.3× nearby chips: `damage_measure.vfl`.
  - Streak sources, with length k·√catchment: `streak_sources.vfl`, G1.
  - Vertical edges gather run-off: H6.
  - North and east faces grow more: F4, G4.
  - Joints and welds rust first: R3.
  - Corner cracks: K9.
- **r5-meta:**
  - Value range, saturation budget and detail density: binding `frame_critique.py` tests.
  - The VLM pass: critique_questions.md.
  - The order of use: art-direction.md › 2. Running the critique at each gate.
  - The studio critique conventions: procedural-assets SKILL.md › 4, the gate.
  - Rounds R5 and R6: done, as rounds A, B and R.
- **r5-texture-layering:**
  - Equalised heights: LST › The method 3.
  - Dirt lerped to a colour: procedural-materials SKILL.md › What makes it read as real 6, and I1.
  - ORM packing: `cop_lib.py` `write_map`.
  - Per-element variation: › Workflow in Copernicus 5.
  - The split into tiling sets plus up to 4 runtime layers: LST › The method, since round I only [never run in an engine].
  - Streaks from sources: G1, H4–H6.
  - No "Substance look": D1, K3, N2.
- **r5-wear-simulation:**
  - When to simulate: wear-simulation.md › When to simulate.
  - Masks say where and tiling detail says how: LST.
  - Grunge masked by sources: G1.
  - Instances read baked fields: LST › Engine hookup.
  - Determinism: generator-architecture.md › Seeds, determinism and variation.

  Recipe (f) was superseded by `rust_flow.py`; recipes (a)–(g) were never run.
- **rA-critique-results:**
  - Run the useful tests at every gate: procedural-assets SKILL.md › Rules, and art-direction.md › 2.
  - The `camera` bare-plane and void fails: in `frame_critique.py`.

  Its thresholds were later replaced in rounds B and R.
- **rR-reference-photos:** all in `frame_critique.py` 0.3, with the photos named in art-direction.md
  › 2 (the photos are not in git):
  - 39 photos used as `--ref` per view;
  - wall L* warn 97.5 / fail 98.5;
  - sky detection;
  - crushed blacks at 5 %;
  - vegetation and sky left out of the accent share;
  - detail density by view;
  - reference match EMD 13/20 (L*) and 10/15 (C*).
- **rC-anime-background:**
  - The paint as a switchable layer: stylisation-anime.md › 1. What goes where.
  - Coloured shadows, no pure black and the grain ceiling: the painterly profile in `frame_critique.py`.
  - Edge-detection numbers: › 6. Traps.
  - Values first: procedural-materials SKILL.md › The method.
- **rD-painterly-surface:**
  - Detail ≤ 0.40 at the focus: the painterly profile.
  - Low-frequency fields as vertex attributes: procedural-materials SKILL.md › Story on tiling kits: in the shader.
  - Weathering as engine data: LST [never run].
  - The DirectX green flip: concrete.md › Engine path.
- **rE-concrete:**
  - Repaint laps and scaffold lifts: J2 (a).
  - Value bands: J1.
  - Dirt in troughs first: J2 (c), and LST › The edge rule.
  - The 8 Copernicus trap fixes: procedural-materials SKILL.md › Traps, and concrete.md › Traps (verified in 22.0.466).
  - Density and hex tiling: T1, T2, run by hand.
- **texturing-at-scale:**
  - The five carriers: LST SKILL.md, the intro table and › The method 1–2, 6.
  - Unique PBR ruled out on budget: LST reference › Memory: why not unique textures.
  - Facade masks rather than vertex colour, and no UDIM or RVT on walls: LST › Engine hookup.
  - T1–T3, run by hand.
- **tiling-and-distribution-algorithms:**
  - Hex tiling with the corrected triangle grid: `wx_detail.py`, and LST › Traps (found the hard way).
  - Band offsets for directional detail.
  - The coverage-preserving reveal: LST › The edge rule; layering.md was rewritten for it.
  - Mean-kept detail.
  - Pareto sizes: C3, K1.

  The note's repetition tests were superseded by T2's correlation excess (revision "T2 (text)").
- **weathering-cracks-edges-damage:** 12 of 60 proposed rules, plus the generator design of §7.4
  (now `layer_cracks`):
  - S1 became K5 and S5 became K6;
  - C1, C2 and C4 became K7, C7 K8, C8 K9, C19 K10 and C23 K11;
  - E5 became N4, E6 N3, E8 N2, and E9 became N1 and N5.
- **weathering-grid-breakup:** per-plane tile-and-blend, with one map shared by the base and the
  weathering (`wx_noise.tile_blend`), and the lattice detector (G6, pass ≤ 9).
- **weathering-organic-growth:** O1 became M1, O2 M2 (some clauses dropped), O4 M3 (revised),
  O5 M4 (ratio only), O8 F4 (ratio only), O9 M5, O10 M8, O11 M7 and O12 M6.
- **weathering-rust-water:** the whole §7.2 rule set, in the rulebook's own format, with 13 of the
  note's 15 actions done:
  - rust by part of the railing: R3;
  - rust growing along the members: R4 and `rust_flow.py`;
  - stains below the post feet and the drip curtain: R5;
  - colour by age and density: R6.
- **weathering-structural-damage:** nothing beyond what already held (K6 kept; damage validation).
- **weathering-water-layers:**
  - Colour by mark age, with water marks in the dirt palette: I4–I6.
  - Face streaks start at grooves: G1.
  - Organic colour measured on the growth layer.

## Why findings went unapplied

1. **They landed as advice, not as checks, which is the same shape as the texel-density miss.**
   - Findings usually went into a reference table: believability.md, realism.md,
     weather-and-use.md, micro-noise.md, concrete.md or texturing-at-scale.md.
   - The SKILL.md steps that point at those tables drop the numbers ("exaggerated a little",
     "per-flat variation such as curtains") and end in a visual gate.
   - Examples: texel density sat in metrics-and-kits.md for four rounds. Of r4-human-industrial's 17
     procedural rules, none is in a script, rule or check; its "Checks:" line in weather-and-use.md
     › Shader layers that read these fields is never run. `wx_export.py` reports the decal and memory
     budgets but judges neither.
   - About half of all findings are in this state (298 of 615).
2. **There is one instrument: albedo, on the elevations of one building, at 50 px/m.** Whatever it
   cannot see stayed prose:
   - roughness, normal and height (every rule, T1–T3 included, is computed from albedo);
   - tops, soffits, glass and inner faces;
   - geometry and dressing;
   - anything under 2 cm: true-width cracks, paint islands, rail members;
   - every asset other than the danchi.

   Rules were adopted when they could be computed on the sheet. All 12 rules adopted from
   cracks-edges-damage are 2D; its geometry, network and 1 mm/px rules were left out.
3. **The review image is not the product, so review cannot catch the gap.** Each round's images came
   from a stand-in that hid the next defect:
   - the 50 px/m sheet hid texel density;
   - the diffuse-only previews (`lit_preview.py`, the mirror's `lit()`) hide roughness;
   - a wrong normal sign silently removed the sun from the previews (LST › Traps, "Capture conventions");
   - the numpy mirror, with its B-spline masks, re-standardised mips, 10 cm local maximum and the
     generator's own float stack, hides the shaders' bilinear masks, plain mips, pk = 1.6·a and
     plain-tiled normal, and the export's missing damage and black growth.

   The parity check that would compare the two has no code.
4. **Some checks exist but nothing runs them.**
   - No pipeline calls `wx_texcheck.py` or `wx_export.py`. The `weather_gate.py texture` mode the
     former names does not exist: the gate has only `check` and `series`.
   - `test_noise.py` (G-2, G-3) is in no pipeline.
   - `frame_critique.py` never runs on weathering reviews, and it has not changed since round R.
   - The damage hot-share check is done by hand.
   - Two tests bind only with inputs that nothing produces. `streak_evenness` needs a wall mask whose
     recipe is marked never run. `reference_match` needs photos that are not in git.
5. **Notes have no owner, and decisions live outside the repo.**
   - 13 of 24 notes are not linked from any skill, rule file or README by their file name.
   - The three round-G notes are cited 22 times by a scratchpad path.
   - Deferrals exist only in session memory: the painterly round D, and "next round is damage
     (K12–K21)".
   - Review 35 parked round E's open items as "run 2's brief", and run 2 never ran.
   - Nothing in the repo tells the next agent that the structural-damage note is waiting.
6. **Proposals were trimmed or weakened without a record.**
   - texturing-at-scale's T1–T8 became T1–T3.
   - cracks-edges-damage proposed 60 rules and 12 went in; organic-growth proposed 15 and 7 went in
     (2 more in part). The revisions still claim "C1–C23", "E5–E9" and "O1–O12".
   - water-layers' V2–V5 went in at about half strength.
   - Edge-rule widths (0.45–0.6, against 0.1–0.3) and the blend sharpness (γ 2, against 4) changed
     silently.
   - The revision discipline covers changing a rule, not declining a proposal.
   - Notes whose proposals were written in the rulebook's own format went in whole: rust-water (13 of
     15 actions) and rR (11 of 11).
7. **Fixes stop at the first file. Stale text and stubs look like coverage.**
   - The rR wording fix reached `frame_critique.py`, but not the four skill passages that still teach
     "3–6".
   - Rules replaced numbers without the prose that states them being edited: "70–80 %", the half-clean
     edges, rust runs that fan out, "no crack starts mid-face".
   - Stubs read as coverage:
     - `peeling` and `washed` are in the layer list, with no generator;
     - repaint patches are off in every preset;
     - `cluster_mask.vfl` forces a strength-1 hotspot;
     - the shaders cite a contract file and a "T8" that do not exist.
   - Uncalibrated estimates went binding: there is no advisory state, and the K and N origins say L for
     bands the note tagged as estimates. They did not move when the user's reviews contradicted them
     (edges "too subtle", less webbing, cracks "too faint"): no revision touched K5–K11 or N1–N5.

## Process changes

1. **Every research note ends with an action table, and a round cannot close with open rows.**
   - The columns: id; finding, with its number; carrier (rule, check, pipeline step or skill section);
     target file; status.
   - Status is one of: open; done, with the commit; parked, with the reason and a trigger to revisit.
   - Write proposed rules in the rulebook's JSON form. rust-water §7.2 is the model: it went in whole.
   - A small script lists the open rows across `docs/redesign/research/`. The round's closing commit
     runs it, and it must show 0 open rows.
   - Back-fill: the ranked table above becomes the first action table for the existing 24 notes.
2. **"Applied" means a check that runs, in the pipeline, on what ships.** A finding is done only when
   all of these hold:
   - (a) a rule or check with a number uses it;
   - (b) the pipeline calls that check. Add `weather_gate.py texture`; call `wx_texcheck.py` and
     `wx_export.py` from `pipeline_i.py`; put `test_noise.py` in the pipeline;
   - (c) it measures the shipped carrier: the exported masks, an engine render, or a mirror that has
     passed parity.

   Two new checks make (c) concrete:
   - a carrier check: every layer the gate measures has an export carrier, or the export fails;
   - a release parity check: a Godot 4 headless golden crop against the numpy mirror, mean ΔE00 ≤ 2.

   Advice that cannot meet (a) to (c) is labelled as advice in the skill.
3. **Review the product, and say which renderer made each image.** Each review page shows:
   - at least one Godot render beside the mirror;
   - one lit view with specular, so roughness is visible;
   - `frame_critique` value, saturation and micro numbers on each crop (mask from `cls`).

   Level gates add a 2 s camera move. Every image carries a label: 50 px/m sheet, numpy mirror, Karma
   or Godot. The sheet was presented as the result for several rounds; this label would have flagged it.
4. **Record what is not adopted, and keep the prose in step with the rulebook.**
   - When a proposed number is adopted weaker, or not at all, add a revision that says so and why (for
     example "V4 ×1.3 → L5 ×1.15, because …").
   - Give rules a `status` field (binding or advisory), and use origin C for estimates.
   - Replace the 22 `roundG/research/` citations with repo paths, and make `rules_to_md.py` fail on a
     path that does not exist.
   - Keep the reconciled numbers (micro p90/p10, coverage, normal strength, edge band, rust-run shape)
     in one table with their source rules, plus a grep lint that fails on the old values.
5. **Keep one research index, linked from the skills.**
   - `docs/redesign/research/README.md` lists each note, the skill files and rules that use it, and its
     open or parked rows.
   - procedural-assets SKILL.md's reading table links the index, so no note is left unlinked.
   - Deferrals the user makes in a review (the painterly round D, the damage round, vines) go in the
     index as parked rows with a trigger, not only in session memory.

## Actions

Statuses as `scripts/research_actions.py` reads them, for the ranked findings above (round J). The older
notes have no action tables of their own; this table and the per-note counts above stand in for them.

| Rank | Action | Status |
|---|---|---|
| 1 | Render the golden crop in Godot 4.7, parity mean ΔE00 ≤ 2 | parked (the round-J work was the round-I feedback and the texture checks; revisit at the start of round K, when the golden crop first renders in Godot 4.7: the first item of that round) |
| 1a | The shaders' edge rule from the exported 10 cm local maximum | parked (needs the engine render to verify; revisit at the start of round K, when the golden crop first renders in Godot 4.7) |
| 1b | Re-equalised mips and rotated derivatives in the shaders | parked (revisit at the start of round K, when the golden crop first renders in Godot 4.7) |
| 1c | Hex-tiled normals with a facade tangent basis | parked (revisit at the start of round K, when the golden crop first renders in Godot 4.7) |
| 1d | Unreal units and axes, an import table per texture class | done (large-scale-texturing SKILL.md, Engine hookup: units and axes, import table) |
| 2 | A carrier for every layer the gate measures | parked (revisit at the start of round K, when the golden crop first renders in Godot 4.7) |
| 3 | Trim sheet, decal atlas and per-class sets, with a gate | parked (revisit at the next danchi export, with `asset_check`) |
| 4 | Roughness, normal and height weathered and checked | parked (starting numbers are in paint-rust-concrete.md; the previews are albedo only until the engine renders; revisit at the start of round K, when the golden crop first renders in Godot 4.7) |
| 5 | The structural-damage rules K12-K21 and the K7 revision | parked (revisit in a damage round, or when a review asks for cracks, spalls or broken pieces; the procedural-mesh-damage skill notes the same trigger) |
| 6 | The water-layer rules adopted weaker than the note | done (each recorded as a revision with its reason in `weather_rules.json`, round J) |
| 7 | Growth area per preset on north planes; a wet-map check | parked (the user's round-I review asked only for corner and recess growth, now G7 and F5; revisit when a review asks for more or less growth overall) |
| 8 | Texel density measured from the exported UVs | parked (revisit at the next danchi export, with `asset_check`) |
| 9 | The texture checks in the gate, before any review page | done (`weather_gate.py texture`; `pipeline_j.py` accepts a build only when it passes) |
| 9b | T5-T8: decals, distance, memory, engine delivery | parked (revisit at the start of round K, when the golden crop first renders in Godot 4.7) |
| 10 | Facade breaks handed to the mesh; a derelict stage | parked (revisit in a damage round, or when a review asks for cracks, spalls or broken pieces) |
| 11 | The photo-calibrated picture tests on every review crop | parked (revisit when the round-K review page is built: run value_range, saturation_budget and the micro floor on its crops) |
| 12 | Rail rust with an engine carrier | parked (rust is measured at 50 px/m and drawn at 1 mm/px by the mirror; revisit at the start of round K, when the golden crop first renders in Godot 4.7) |
| 13 | A second, recessed mask layer for oblique views | parked (the player views are straight on; revisit with the grazing views, rank 1) |
| 14 | A use layer: touch at code heights | parked (R7's hand zone covers the rails only; revisit when a review asks for wear from use) |
| 15 | T4 grain stationarity on the fine composite | parked (revisit with 9b) |
| 16 | Skill text reconciled with the later rules, and a lint | done (`scripts/skill_lint.py`, `tests/unit/test_skill_lint.py`) |
| 17 | The peeling layer drawn, with rules | done (`weather_fields.layer_peeling`; P1, P2, P3c) |
| 17b | The washed layer and repaint patches | parked (revisit when a review asks for repaint patches or washed bands) |
| 18 | Windows and dressing counted at the plan gates | parked (revisit at the next danchi plan or dressing pass) |
| 19 | Glass, tops, soffits and inner faces in the gate | parked (not in the elevation planes; revisit with the grazing, up and down views, rank 1) |
| 20 | Moss with relief and sheen | parked (needs the height and roughness carriers, rank 4) |
| 20b | The lichen line in weather-and-use.md | done (fixed in round J; `scripts/skill_lint.py` keeps the old line out) |
| 21 | Cracks and edges at close range | parked (revisit in a damage round, or when a review asks for cracks, spalls or broken pieces) |
| 22 | Facade stories: 3-7 hot regions per front | parked (the user's picks have favoured rule-placed marks; revisit when a review asks for more story) |
| 23 | Shader terms: world macro, per-bay tint, instance data | parked (revisit at the start of round K, when the golden crop first renders in Godot 4.7) |
| 24 | Masks padded; the export fails on a side over 4,096 | done (`wx_export.pot_pad` and `size_lint`, which raises) |
| 24b | A vertex-data encoding check | parked (revisit at the next danchi export, with `asset_check`) |
| 25 | A GPU and motion budget | parked (revisit at the start of round K, when the golden crop first renders in Godot 4.7: measure GPU ms at the first engine run) |
| 26 | Expressive range over 50 seeds; hold-out picks | parked (revisit at the danchi's next phase 8 gate) |
| 27 | Vines | parked (vines on public housing are rare: 2 of 827 sites; revisit if a brief asks for overgrown or abandoned sites) |
| 28 | Rulebook paths fixed | done (`rules_to_md.py` fails on a cited path that does not exist) |
| 28b | An advisory status and C tags for estimates | parked (revisit when a rule is adopted from an estimate without a user pick or a photo) |
| 29a | Industrial wear (racks, docks, forklift floors) | parked (no industrial asset is planned; revisit when one is) |
| 29b | The painterly surface layers | parked (the user deferred them: realism is the default and painterly an option; revisit when a painterly brief arrives) |
| 29c | Research-grade metrics (DISTS, saliency, inverse fitting) | parked (the rule gates and the user's picks carry the reviews; revisit if two rounds' picks disagree with the gate) |
