# Anime-background stylisation: an optional profile

The baseline is realistic. A 1980s–90s anime-background look (painted concrete, coloured
shadows, a painted sky) is an **option** layered on a realistic generator, never a lowering of
realism in its core. It comes in three independent layers, and each one can be switched off:

1. **Lookdev switches** on the generator HDA: material flattening and a palette swap.
2. **A lighting key preset** per time of day.
3. **A Copernicus post** on the render (`../scripts/build_anime_post.py`),
   with a `strength` mix back to the realistic render.

Research and sources: `docs/redesign/research/rC-anime-background.md`. Evidence:
`docs/redesign/evidence/styleC/`. Node and parm names were read in Houdini 22.0.466. Tags:
[S] sourced, [I] inference, [C] measured in round C on danchi v3 and v5 renders. † marks a
recipe step that was not run in round C.

## 1. What goes where

| Layer | Changes | Lives in | HDA parm (proposed) | Default |
|---|---|---|---|---|
| Lookdev: flattening | micro-grain amplitude ×0.3; streak count ×0.3, width ×2, harder edges; no grain inside stains | the material graphs and the streak generator | `style` menu (realistic, painterly), `style_micro`, `style_streaks` | realistic |
| Lookdev: palette swap | base colours per style; accent chroma allowed up to the painterly budget | material parms through `mtlxswitch` | `style_palette` | realistic |
| Lookdev: geometry | painted-mass tree canopies instead of facets; window detail by distance | Switch SOP in the generator | `style_veg` | realistic |
| Lighting key | sun angle, colour and strength; sky-dome tint; night emissives | the LOP light rig | `style_key` (summer_day, winter_overcast, dusk, night†) | the realistic rig |
| Post | bands, colour key, sky, lines, texture, haze, grade | Copernicus, after the render | `style_post` toggle, `style_strength` | off |

The post is a presentation layer for offline renders. A game export takes only the lookdev
switches; an engine needs its own post or toon shading for the rest [I].

**Strength.** 0 is the realistic render, 0.4 is "mostly realistic" (painted sky and coloured
shadows show through), and 1 is the full profile (`styleC/07_strength_0_04_1.jpg`). The user
picked **0.4**, now the default (review 34): 1.0 read as a filter, and its edge lines were so
distracting that nothing else in the frame registered. 0.4 is "still not quite the painterly
anime background style". The missing part is a mild brush-stroke impression and very slight
hue shifts in surface space (materials and textures), not more post. That is round D.

**Edge lines are off by default** (`--lines` turns them on). The user read them as CG
outlines. The light edges in background paintings and environment concept art are mostly
worn and chipped arrises showing light substrate under grime. That belongs in the realistic
material (`weather-and-use.md`, "Urban grime and the light substrate"). A highlight from the
light belongs in the shader.

## 2. Lookdev switches

- **Flattening.** Painted backgrounds are flat fields in opaque, thin poster colour [S/P Oga],
  with stains as a few designed strokes [I].
  - Multiply the micro-grain amplitude by about 0.3. Painted surfaces measured a mean local std
    of 5.5–6.4 L\* at pixel scale, against 8.6–9.7 on the realistic v3 renders [C].
  - Keep the generator's cause-placed streak sources (`weather-and-use.md`), and draw fewer,
    wider, harder-edged marks from them. Do not delete the story.
- **Palette swap.** `mtlxswitch` (verified type) between the realistic and the painterly
  base-colour set, driven by the `style` parm. The painterly set may run warmer and more
  saturated on walls, within the `--profile painterly` saturation budget in §5.
- **Night.** It needs emissive windows (20–40 % lit †) and lamp halos (Ogura's fogged-lens halos
  [S/2]). The post cannot invent them from a day render.
- **Karma toon shading.** Houdini 22 has a `karmatoonshading` LOP (CVEX `toonshading`, with the
  ramps `difframp`, `glossramp` and `coatramp` and `outline_enable`), and outline parms on
  `karmarendersettings` (`outline_enable`, `outline_radius`, `outline_depththreshold`). Neither
  was rendered in round C †. The post below does the banding from AOVs instead, which keeps the
  beauty render realistic.

## 3. Lighting key presets

Start from the realistic rig that the user preferred (`believability.md` 6): sun 28° up and 40°
off the facade normal on the camera's side, sun 0.85 and sky dome 0.35. The keys change colour
and balance, not where the light comes from:

| Key | Sun | Sky dome | Why |
|---|---|---|---|
| `summer_day` | same angle; colour (1.0, 0.96, 0.88) | tint toward (0.55, 0.70, 1.0) | blue sky fill gives blue shadows in the render itself; less post work [I] |
| `winter_overcast` | 0.15 or off | 1.0, neutral grey | flat, low contrast (Patlabor 2) [I from stills] |
| `dusk` | 8–12° up, colour (1.0, 0.55, 0.30) | (0.35, 0.35, 0.60) | the post grade alone cannot move the sun (`06_presets…`: dusk on a noon render reads as a filter) [C] |
| `night` † | off | (0.02, 0.03, 0.08) | emissive windows and lamps; no pure black, dark reds and blues (Akira) [S/2] |

None of these rigs was rendered in round C; the `summer_day` and `dusk` grades were applied to
the v3 noon render.

## 4. The Copernicus post

Run it with hython from a directory that holds no `.py` files:

```
hython render_aov.py <scene.hip> cam_hero,cam_facade <out_dir> 32      # Karma AOVs, multi-part EXR
hython build_anime_post.py --aov-exr <cam>_aov.exr --out after.jpg --horizon 0.12 \
       [--preset summer_day|winter_overcast|dusk] [--strength 0.4] [--lines] [--save-hip post.hiplc]
hython build_anime_post.py --beauty render.jpg --out after.jpg --horizon 0.26   # image mode
```

**AOV mode is the one to use.** Turn on `albedo`, `hitPz` and `hitN` on
`karmarendersettings`. Image mode is a fallback for old JPGs: without albedo it cannot tell a
stain from a shadow, so it posterises stains into blotches (`05_…`, `04_…`), and its sky mask is a
colour heuristic.

The graph (about 85 nodes; cooks in under a second at 1280 × 720 after the first OpenCL compile):

| Step | Nodes and parms (verified) | Numbers |
|---|---|---|
| Inputs | `file` (`filename`, then press `addaovs`; set `raw#` on N and depth); `channelsplit` → `channeljoin` (`signature` f3) for RGB | Karma parts: C, albedo, depth, N |
| Sky mask | `remap` (`op` threshold, `side` less, `threshold` 1e-3) on depth | depth 0 = sky [C] |
| Flat albedo | `kuwaharafilter` (`radius` 1.5, then 2.5), then a local mean at `radius` 8 | radius 4 or more turns windows into blobs [C] |
| Stains as levels | `mono`, `blend` (`mode` divide), `remap` (`useramp`, constant `hou.Ramp`), then a gain via divide and `clamp` 0.6–1.6 | levels 0.78 / 0.90 / 1.0 / 1.06 of the local mean; keeps the hue of small items [C] |
| Irradiance | `mono` (C) ÷ `clamp` (`lowerlimit` 0.03) of `mono` (albedo) | v3: lit 1.15–1.24, sky-lit shadow ~0.25, occluded 0.07–0.12 [C] |
| Painted shadow shapes | `kuwaharafilter` `radius` 3 on irradiance; `blur` (`units` pixels, `size_pixel` 1) | merges 32-spp speckle [C] |
| Hand-cut edges | two `fractalnoise` (`elementsize` 0.03, `amp` 1, `center` 0, second `off` (17.3, 4.1)) → `channeljoin` (`signature` f2) → `distort` `dir` input, `scale` 0.0025 | about 1 px [C] |
| Colour key | `function` (`func` math, `func_math` abs, `scale` 1/key) → `monotorgb` (`inputmax` 2, constant ramp: occlusion, shadow, lit colours) → `blend` multiply with the flat albedo | thresholds 0.12 and 0.55 of the lit level; key = 80th percentile of irradiance [C] |
| Paint texture | `fractalnoise` strokes (`elementsize` 0.01, `elementscale` (3, 0.6), `amp` 0.035, `center` 1) × wash (`elementsize` 0.25, `amp` 0.045) → `blend` multiply | [I] |
| Distance | `remap` depth 40 → 650 m (linear) → `kuwaharafilter` `radius` 4 blended in; `constant` (`signature` f3) haze colour blended at up to 0.40 | a square-root ramp over-hazed the 200–300 m blocks [C] |
| Edge highlights | `edgedetectnormal` (`normtolerance` 0.12, `thickscale` 1) → `remap` 0.05–0.30 (`useramp` 0) × lit mask (`remap` threshold, minus sky, `dilateerode` `radius` 1.5) → `blend` screen with a warm white at 0.55 | 1 px at 1280 [C] |
| Silhouette steps | `edgedetectdepth` (`depthtolerance` 0.25) → `remap` → `hsv` (`valscale` 0.55) blended at 0.25 | default 0.08 flags 32 % of the frame [C] |
| Painted sky | vertical `ramp` (`rampType` vertical, `signature` f1) → `monotorgb` 3-colour gradient from the horizon; clouds = `fractalnoise` (`elementsize` 0.16, `elementscale` (2.4, 1)) → `remap` threshold (`width` 0.003) × height band → `dilateerode` −4 then +4 px; underside = mask − `xform2d` (`t` (0, 0.022)) | [S] gradient and drawn clouds; [C] values |
| Grade | `colorcorrect` (`master_add` lift); `hsv` (`satscale`); diffusion = `blur` (`units` image, `size` 0.02) → `blend` screen, `mask` 0.07 | no pure black [S/2] |
| Strength | `blend` (`mode` blend, `mask` = strength) between the original RGB and the stylised result | 0, 0.4, 1 |
| Output | `rop_image` (`copoutput`, `vm_image_jpeg_quality`); default OCIO conversion | linear in, sRGB JPG out |

Presets, as linear RGB multipliers on the flattened albedo [I, tuned in round C]:

| Preset | Lit | Shadow | Occlusion | Sky zenith / horizon | Saturation | Haze |
|---|---|---|---|---|---|---|
| `summer_day` | (1.02, 0.98, 0.90) | (0.36, 0.40, 0.52) | (0.16, 0.18, 0.27) | (0.24, 0.44, 0.80) / (0.74, 0.80, 0.86) | 1.10 | 0.40 |
| `winter_overcast` | (0.80, 0.81, 0.78) | (0.44, 0.47, 0.50) | (0.24, 0.26, 0.29) | (0.48, 0.52, 0.55) / (0.70, 0.71, 0.70) | 0.78 | 0.65 |
| `dusk` | (1.10, 0.72, 0.46) | (0.26, 0.24, 0.44) | (0.12, 0.11, 0.24) | (0.08, 0.09, 0.30) / (1.00, 0.58, 0.32) | 1.05 | 0.50 |

Override any value with `--set key=r,g,b`.

**Keep the sky in the light value group.** A deep zenith (0.10, 0.25, 0.62) put the sky in the
mid group and dropped notan dominance from 2.57 to 1.07 on the v3 hero street. The pale
cerulean above gives 1.67 (`08_sky_value_deep_vs_pale.jpg`) [C].

## 5. Judging it

Run `frame_critique.py --profile painterly` on every stylised look, and `--pair` against the
realistic render of the same camera. On top of the realistic tests, the profile:

- **changes thresholds** (`PAINTERLY_OVERRIDES`): accent chroma warn and fail at 0.15 and 0.25,
  the facade base-colour standard off, `notan_dom_pass` 2.0, slope −1.9 to −0.7,
  `detail_a80_pass` 0.40, and camera tilt warn and fail at 4° and 12°;
- **keeps value grouping binding.** A designed image needs one dominant value. In round C
  this check caught a deep painted sky, which dropped dominance from 2.57 to 1.07;
- **reports these as info,** as the realistic profile does: saliency, repetition, palette,
  depth, squint, spectral slope (−1.03 → −1.13 only), camera apart from the bare-plane
  check, and the stationarity half of `micro_uniformity`;
- **adds `painted_key`,** which warns when any of three rules fails. Ranges are [C], re-measured
  with `frame_critique.py` on round-C outputs without captions:

  | Rule | Threshold | Realistic | Stylised |
  |---|---|---|---|
  | Shadow colour: mean b\* of the darkest non-sky quartile | ≤ −2 | +3.8 | −2.2 to −12.5 |
  | Black floor: L\* 1st percentile | ≥ 12 | 6.9–9.0 | 14.9–35.2 |
  | Value peaks: share within ±4 L\* of the 3 strongest peaks | ≥ 0.58 | 0.48–0.50 | 0.61–0.76 |

  The overcast winter key keeps neutral shadows (b\* +2.5) and warns on the first rule; that is
  expected for overcast. Strength 0.4 gives 0.42 on the third rule, which suits a look that is
  meant to stay mostly realistic.
- **adds a grain ceiling** to `micro_uniformity`: a warn above 7.0 L\* mean local std, meaning
  photographic grain was left in. Realistic 8.6–9.7; stylised 4.7–6.9; the v5 original passes
  at 5.9, so this is a warn only.

All of these numbers come from our own renders, tuned by eye on two cameras of one scene.
Nobody has judged them yet. Re-fit them on the user's answers to the questions below, as
round B did for the realistic profile. `docs/redesign/evidence/styleC/painterly_metrics.py` is
the first standalone version of the same measurements.

**A/B questions for the user** (show both orders; record the answers like round B):
1. Strength 0.4 or 1.0? **Answered: 0.4** (review 34).
2. Pale or deep sky? (`08`)
3. Edge lines painted or CG? **Answered: CG; now off by default** (review 34).
4. Blue-violet shadows (summer) or neutral (winter)? (`06`)
5. Is the haze on the far blocks right, too much, or Kobayashi-clear? (`01`)
6. Hard-edged stain levels (aov mode) or soft stains (image mode)? (`02` against `05`)
7. Which preset fits the brief: summer, overcast or dusk? (`06`)
8. What breaks the illusion first? Expected answers: faceted trees, flat ground, image-mode
   blotches.

## 6. Traps (Houdini 22.0.466, all hit in round C)

| Trap | Fix |
|---|---|
| Setting a File COP's `filename` from Python adds no outputs (`outputNames()` is empty). Downstream, `kuwaharafilter` then reports "Invalid source …/blur3 (source is missing)" from inside its HDA | press `addaovs` after setting `filename` |
| `hou.Node.setInput(i, node, output)` needs an output **index**; a name raises `TypeError` | `node.outputNames().index(name)` |
| Karma writes AOVs as a **multi-part** EXR (parts C, albedo, depth, N, primid). OpenImageIO's `ImageInput.spec()` shows part 0 only | iterate `ImageBuf(path, i, 0)` over `nsubimages`; the File COP's `addaovs` finds all parts |
| `hitPz` arrives as `depth`, `hitN` as `N` | pick AOVs by part name |
| With the dome light visible to camera, C alpha is 1 everywhere | sky mask = depth == 0 |
| `karmarendersettings` `resolutiony` is locked while `res_mode` is autoheight (`hou.PermissionError`) | leave it; the height follows the camera |
| `sceneimport::2.0` created from Python has an empty `objects` parm and imports nothing | set `objects` to `*` |
| `primid` is per primitive (per triangle here), so it is no material mask; husk logs "Mode idcover requires PrimId channel" | use `karmacryptomatte` (material) or a primvar AOV † |
| `remap` has `useramp` on by default | set `useramp` 0 for a plain linear stretch |
| `dilateerode` defaults to `radius` 25 px; a negative radius erodes | set the radius explicitly |
| `edgedetectnormal` output peaks at 0.2–0.36 | stretch it with a `remap` before use |
| `edgedetectdepth` at the default `depthtolerance` 0.08 marks noise on the ground and the trees at 32 spp | 0.25 |
| `fractalnoise` has no `seed` parm | decorrelate with `off` |
| Signatures are strings (`f1`, `f2`, `f3`, `f4`, `default`) on `fractalnoise`, `constant`, `channeljoin`, `ramp` | set them as strings |
| `distort` with a wired `dir` input ignores `dirtype` (the parm only matters without the input) | — |
| `edgedetect` `method` tokens are `0`–`4` (Sobel, Prewitt, Laplacian, Simple, Thresholded Sobel) | set the index |
| Constant-basis ramps still give about 30 transition colours at band edges | fine: free antialiasing |
| The vertical `ramp` runs 1 at the top to 0 at the bottom | — |
| A script named `types.py` (any stdlib name) in the working directory crashes hython at startup in `enum` | run hython from a directory with no `.py` files |
| Houdini's bundled `python313/python.exe` cannot import PIL (`_imaging` DLL) outside hython | run numpy/PIL checks in hython |
| Noise in image space swims under camera moves | stills only; for animation, put strokes and wash in world space in lookdev † |

## 7. Limits

- Geometry shows through: faceted trees stay faceted and get a highlight on every facet (`01`,
  `06`). Fix it in lookdev (painted canopy masses), or mask vegetation out of the lines with a
  cryptomatte †.
- Image mode blotches stains on dim, stained walls (v5 end wall) and posterises asphalt grain.
- The grades move colour, not light: dusk on a noon render reads as a filter.
- No night key, no reflections in wet ground, no window lights.
- Clouds come from the same noise in every shot; studios vary them per shot [S]. Change `off`
  per camera.
- The thresholds were tuned by eye on two cameras of one scene; no user pick has judged them yet.

## Sources

The research note has the full list. The key ones:
- Animation Obsessive on Oga and Yasuda: https://animationobsessive.substack.com/p/what-kazuo-oga-thinks-about-when · https://animationobsessive.substack.com/p/the-artist-who-colored-ghibli
- Kobayashi interview: https://animeanime.jp/article/2020/02/08/51470_2.html
- Blue Protocol, CEDEC: https://www.famitsu.com/news/202009/08205405.html · https://www.gamebusiness.jp/article/2021/09/13/19051.html
- Clip Studio photo-to-background tips: https://tips.clip-studio.com/ja-jp/articles/8939 · https://tips.clip-studio.com/en-us/articles/8952
- SideFX, Kuwahara, Edge Detect by Depth and by Normal COPs: https://www.sidefx.com/docs/houdini/nodes/cop/kuwaharafilter.html · https://www.sidefx.com/docs/houdini/nodes/cop/edgedetectdepth.html · https://www.sidefx.com/docs/houdini/nodes/cop/edgedetectnormal.html
