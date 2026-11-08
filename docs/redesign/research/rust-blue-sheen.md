# Rust's blue sheen: dense dark scale reflecting the sky

Date: 2026-11-08. Scope: the user's request after round J, "subtle touches of blue rusting on the rust ... a rough
blue sheen on the darker rust surfaces", which "may be better off as a material shader". It builds on
`weathering-rust-water.md` (rust layers, colours, where water stays) and `coatings-concrete-corrosion.md` §3 (colours
on one rail: mill scale bluish-black, black rust L* about 25.5). Research only: no code, skill or rule was changed.

## Conventions

- Tags: **[S n]** a source's statement; **[M n]** a measurement published in source n; **[P]** my pixel reading of a
  photo this session (camera JPEG read as sRGB D65, white balance and exposure unknown, about ±5 L*); **[I]** my
  inference or arithmetic; **[C]** a craft estimate to calibrate on the user's picks. "(snippet)" means seen only in a
  search summary. **[repo]** is my reading at 40a9963 of `rust_flow.py` (`LAB_DARK`, `dark`), `wx_hires.py` (`lit`),
  `wx_export.py` (`M_hi`), the skill's `paint-rust-concrete.md` and `examples/danchi/README.md`.
- Arithmetic [I]: F0 colours integrate each mineral's reflectance spectrum with the CIE 1931 functions (Wyman et al.
  fit [35]) under a 6,504 K Planck illuminant, white = 1. Porosity uses Looyenga mixing with voids. Apparent colours
  use Karis's split-sum fit [32] and a uniform sky. Each is a few lines of numpy.

## 0. Summary

1. **Cause: the dark scale's own reflection, lit by the sky.** It is not a pigment, and it is not a film. Compact
   goethite, magnetite, maghemite and hematite reflect 13–31 % at normal incidence [M 1–5], 3–8× the 4 % of paint or
   concrete; porous scale keeps about 9–15 % [I]. The body is near black (L* 25, Y 0.044), so the reflection is
   1–2.5× the diffuse light [I]. Outdoors it mostly reflects sky: a broad blue-grey gloss, bluest on scale that is in
   shade and faces open sky [I; P 34a–b]. The minerals add a slight cool tint: all but magnetite are bluish grey in
   reflected light, reflecting 15–25 % less red than blue [S, M 1–4], but the sky does most of the blue [I].
2. **It is steady, not iridescent.** Its colour follows whatever it reflects and whitens toward grazing angles.
   Rainbow colours on rust need thin films: tarnish on compact hematite [S 15], bacterial or oil films on still
   water [S 16], heat temper colours [S 13]. None of them fits a rough blue sheen on rails [I].
3. **Where:** on the oldest, densest dark scale. That is the inner layer bared where the flaky outer layer spalled
   (feet, joints, bottom rail, rail tops), and scale compacted by hands in the top rail's hand zone [S 7, 8; P 34a; I].
   Photos of heavy rust show it on about 5–30 % of the rusted surface [P 34a, 34c]. For the danchi: 4–15 % of the
   rusted steel at rust 1.0, none below rust 0.5 [C].
4. **What to do:** bake a **sheen mask** (the amount of dense scale) into `M_hi.A` on steel pixels. Under it the
   material raises F0 from 0.04 to **0.08** and lowers roughness from 0.85–0.95 to **0.55**. The albedo stays
   brown-black (never b* < 0). That is Specular 1.0 in UE Default Lit and `SPECULAR` 0.71 in Godot. Both engines do it,
   Substrate's default GBuffer included [S 17–19, 24; I]. A thin film is not worth its cost here (§3.4).
5. **Preview:** with no specular term, the compositor shows every dark surface 5–7 L* darker and warmer than an engine
   will [I]. Add a split-sum sky reflection behind a button, and a material-ball strip for judging strength (§5).

## 1. What makes the sheen

### 1.1 Candidates

| Candidate | Evidence | Verdict |
|---|---|---|
| High reflectance of dense iron oxides | compact phases reflect 13–31 % [M 1–5]; Querry's n, k give F0 0.16–0.17 for magnetite and 0.26–0.31 for hematite (o-ray) [M 6; I] | **the cause**, lit by the sky |
| Mineral tint ("specular hematite") | hematite "gray-white, with a bluish tint"; goethite "gray with bluish tint"; maghemite "white to bluish gray", body "brown, bluish black" [S 1, 3, 4] | **adds a slight cool tint** |
| Sky reflection on any dark surface | dark body + any F0: the reflection rivals the diffuse light (§1.3) | **supplies the blue**; under overcast it is grey [I] |
| Thin oxide film (temper colours) | interference in the oxide film [S 14]; needs heating to 205–337 °C [S 13]; blue at about 45–75 nm [I; 36 snippet] | **rejected** for atmospheric rust |
| Water or oil film | water films are microns thick (no colours) [I]; iridescent films form only on still iron-rich water: bacterial films shatter into plates when disturbed, oil swirls and reforms [S 16] | **rejected** for rails; puddles at most |
| Mill scale ("blue scale") | bluish-black, under 1 mm [S 9] | **minor**: already a colour in the R7 paint-loss rims |
| Blued steel | blue-black magnetite layers ≤ 2.5 µm; rust bluing boils red rust into black Fe3O4 [S 12] | **supports** magnetite-rich black scale reading blue-black |

### 1.2 Dense scale reflects 3–8× more than paint

| Phase (where it sits in rust) | R at 460 / 540 / 640 nm, compact [M] | F0, linear sRGB [I] | B/R | Body colour |
|---|---|---|---|---|
| hematite (minor in atmospheric rust; old, dry scale) | 30.9 / 28.8 / 25.8 % [1] | (0.264, 0.287, 0.316) | 1.20 | steel-grey to red [1] |
| maghemite (patches in inner layers) | 27.6 / 24.8 / 21.6 % [4] | (0.213, 0.246, 0.276) | 1.30 | brown, bluish black [4] |
| magnetite (inner layer, wet, low oxygen) | 20.8 / 20.4 / 20.8 % [2] | (0.209, 0.203, 0.211) | 1.01 | black; pigment Lab (25.5, +0.8, +0.4) [8] |
| goethite (dense, stable inner layer) | 16.0 / 14.0 / 12.8 % [3] | (0.127, 0.138, 0.166) | 1.30 | blackish brown [3] |
| lepidocrocite (porous orange outer layer) | 15.3 / 14.0 / 12.8 % [5] | (0.127, 0.139, 0.158) | 1.24 | red to orange-brown [5] |
| paint, concrete, other dielectrics | — | 0.04 | 1.00 | — |

- **Layers.** Next to the steel lies goethite with magnetite, darker and denser than the outer lepidocrocite
  [S 8 (rust note S38); 11 snippet]. Magnetite forms where thick rust starves the steel of oxygen and where wet periods
  reduce FeOOH. It was 35 % of the crystalline rust under salt spray and 51 % under a sealing coat [M 7]. Thick marine
  rust exfoliates in laminar sheets, which bares the inner layers [10 snippet].
- **Porosity lowers F0** [I]: dense n 2.3–2.4 gives 0.155–0.17; 10 % voids 0.13–0.15, 20 % 0.11–0.12, 30 % 0.09–0.10.
  Compact lepidocrocite would match goethite, but the orange layer is porous and rough, so its gloss stays low.

### 1.3 Why it reads blue [I]

Dark scale with the generator's albedo, Lab (25, +10, +11) (`LAB_DARK`). Camera balanced to daylight; clear sky at
12,000 K; ground albedo 0.2. The reflection sees either open sky or a grey wall (albedo 0.25).

| Material on the dark scale | Shade, sky in the mirror | Shade, wall in the mirror | Sun (4× the sky), sky in the mirror |
|---|---|---|---|
| F0 0.04, roughness 0.75 (rust today) | (32.5, +6.0, −2.6) | (26.7, +7.3, +2.7) | (27.4, +9.3, +6.6) |
| F0 0.08, roughness 0.55 (proposed) | (40.9, +4.8, −7.0) | (29.7, +6.6, +1.4) | (30.6, +8.3, +3.1) |
| F0 0.12 tinted, roughness 0.55 (strong tier) | (46.3, +4.5, −12.1) | (31.9, +6.0, −0.6) | (32.9, +7.8, −0.5) |

- **Reflection against diffuse**, L* 25 scale under a uniform sky: 0.5× at F0 0.04 (roughness 0.75); at roughness 0.55,
  1.2× at F0 0.08, 1.9× at 0.12 and 2.4× at 0.16. Old rust at L* 31 gets 0.3× at F0 0.04: lighter rust hides it.
- **So the sheen is strongest on dark scale in shade that faces open sky.** It is mild in sun and absent where the
  reflection sees walls, ground or the balcony ceiling. In photo 34b one rusted sheet-pile wall reads (34, +14, +15.5)
  in sun and (15, +0.5, −0.3) in a shadow, where 57 % of its pixels are cool grey [P]. Fresnel adds little until
  grazing (F0 + 0.002 at 45°, + 0.03 at 60°, + 0.22 at 75°): rail tops seen from the balcony brighten and whiten.

### 1.4 Where it appears, and how much

| Place | Sheen | Why |
|---|---|---|
| dense dark scale where the flaky outer layer spalled (feet, joints, bottom rail, rail tops) | yes, the main site | oldest and wettest steel, densest inner layer [S 7, 8]; the generator's dark class sits there (R9) |
| top rail's upper face in the hand zone (0.8–1.2 m) | yes, the most | hands compact and smooth the scale, like the foot-worn studs in 34a [P; I] |
| horizontal upper faces | strongest, view-dependent | they mirror the sky from any view above them; grazing views add Fresnel [I] |
| vertical faces | partly | from below they mirror the sky at the viewing elevation; straight on, the horizon or the facing building [I] |
| sheltered undersides | no blue | the scale may be dense there, but it mirrors the ground and the balcony [I] |
| wet zones | glossier, not bluer | water fills the micro-roughness (roughness down, existing damp mask) but tops F0 at 0.02 [I] |
| porous orange and brown rust, fresh fronts | no | rough (0.85–0.95), and its lighter body masks the reflection |

Photo readings [P] (classes are mine: "cool" means C* < 14 and b* < 1):

| Photo | Subject | Reading |
|---|---|---|
| 34a, Nyhavn tread plate (evening sun) | foot-worn stud tops of dense dark scale in a field of porous rust | the stud tops are cool: 26.5 % of the frame, median (28, +7, −5), L* p10–p90 12–51, b* p10–p90 −10 to −0.5; the field (52.5, +15.5, +24.6) |
| 34b, Carolinensiel sheet piling (morning) | one rusted wall, part of it in a shadow | sun: (34, +14, +15.5), 0.1 % cool; shadow: (15, +0.5, −0.3), 57 % cool |
| 34c, Midway close-up (marine) | flaky orange outer rust over dark scale | dark class 36 % of the frame, median (12, +3, +1); light cool-grey flecks on it 5 % (49, +1, −4), which may be salt as much as sheen |

### 1.5 Steady or iridescent?

Steady. The reflection's hue is the environment's (blue sky, grey overcast, warm ground or walls), and Fresnel only
whitens it toward grazing (F90 = 1). A film would swing hue with angle: 170 nm at IOR 1.3 over dense scale is a faint
blue (C* 8–14) at normal incidence, but at 60° it acts like 127 nm and turns saturated blue-violet (C* about 19) [I].
That is the soap-bubble look, not the photos.

## 2. Values for the material

| Item | Linear RGB | L*a*b* | F0 | Roughness | Tag |
|---|---|---|---|---|---|
| dense dark scale (`LAB_DARK`, keep) | (0.078, 0.036, 0.024) | (25, +10, +11) | 0.08 under the mask (0.10–0.12 strong tier; cap 0.16) | 0.55 (0.50–0.65) | I; C |
| old wet scale (`LAB_WET`) | (0.070, 0.034, 0.021) | (24, +8.5, +11.5) | 0.04; wetness lowers roughness only | 0.85 dry, 0.55–0.7 wet | repo; C |
| optional neutral drift on sheen pixels | (0.061, 0.040, 0.034) at most | (25, +5, +5) | as above | as above | M 8 (magnetite black); I |
| black rust (magnetite pigment), the limit | (0.048, 0.045, 0.045) | (25.5, +0.8, +0.4) | — | — | M 8 |
| never in albedo | any b* < 0 on rust | — | — | — | I |
| F0 tint where the target keeps coloured F0 | — | — | 0.08–0.12 × (0.92, 1.00, 1.10) | — | M 1–4; I |
| porous rust (old, mid, fresh) | rust note §6 | rust note §6 | 0.04 | 0.85–0.95 | skill table; C |

If a film is ever tried (not recommended, §1.5): for a faint blue at normal incidence over scale of F0 0.15, use 165–175
nm at film IOR 1.3 (the glTF default) or 85–100 nm at IOR 2.0 [I]. Set minimum and maximum thickness equal: the glTF
default range of 100–400 nm sweeps a rainbow [S 26; I]. Temper colours, oxide n 2.6 on iron: straw about 20 nm, brown
30, purple 40, blue 45–55, light blue 60–75 [I].

## 3. Engine recipes

### 3.1 Unreal Engine 5

| Version | Substrate status | Source |
|---|---|---|
| 5.2–5.4 | Experimental | [S 21a] |
| 5.5 | Beta; "all features of legacy materials" and all platforms supported | [S 21a] (snippet) |
| 5.6 | Beta: the project setting reads "Substrate materials (beta)" | [S 21b] |
| 5.7 | Production-ready; on by default in new projects, while projects upgraded to 5.7+ stay legacy unless they opt in | [S 21c; 19] |
| 5.8 docs | still "Platform support and testing is currently incomplete" | [S 19] |

- **Legacy Default Lit.** Specular 0–1 maps to F0 0–0.08: 0.5 is "approximately 4 %" [S 17], and F0 =
  lerp(0.08 × Specular, BaseColor, Metallic) [S 18 snippet]. Without metallic, 0.08 is the ceiling, and it is enough.
- **`MF_RustSheen`** (inputs Sheen, Roughness, Cavity = 1): `Specular = Cavity × Lerp(0.5, 1.0, Sheen)`,
  `Roughness = Lerp(Roughness, 0.55, Sheen)`; Base Color and Metallic (0) untouched. This also covers Epic's cavity
  practice (`Cavity × 0.5` in Specular [S 17]).
- **Substrate.** A Slab takes F0 and F90; F90 is unsupported in the default Blendable GBuffer. Thin film is a helper
  (Substrate Thin-Film: F0, F90, IOR, Normal, Thickness) that computes a slab's F0 and F90; its thickness unit is not
  documented [S 19, 20]. Use `F0 = Lerp(0.04, 0.08, Sheen) × Cavity`, grey, the same as Specular 1.0. A forum report
  says Blendable drops dark F0's chroma (UE 5.8, no Epic reply) [S 22], so a tinted F0 is portable only on the Adaptive
  GBuffer (SM6 platforms; +15 % cook time; slower than Blendable) [S 19].
- **Rejected.** Partial metallic gives F0 the base colour's hue (a warm reflection on brown scale, the wrong way) and
  darkens the diffuse [I]. Per-pixel Clear Coat adds a 0.04 lobe (about 0.11–0.12 in all) but needs the From Material
  Expression shading model [S 23]: keep it for the strong tier. Thin film: §3.4.

### 3.2 Godot 4

Godot's dielectric F0 is `0.16 × specular × specular`, mixed toward albedo by metallic; F90 reaches 1 from F0 about
0.02 [S 24]. So `SPECULAR` 0.5 = 0.04, 0.707 = 0.08, 0.866 = 0.12, 1.0 = 0.16, always grey. `light()` runs per light [S 25] and
cannot touch the sky reflection, where this effect lives. StandardMaterial3D's Specular is one value per material (I
found no texture slot for it), so the steel slot needs a spatial shader [I]:

```glsl
// steel slot: the sheen is F0 and roughness, nothing else
uniform sampler2D m_hi : hint_default_black, filter_linear_mipmap; // RGBA8 linear; A on steel = dense-scale sheen
uniform float rough_rust = 0.88;             // porous rust
uniform float rough_sheen = 0.55;
uniform float spec_sheen = 0.7071;            // F0 = 0.16 * S * S = 0.08; 0.866 = 0.12 (strong tier)
void fragment() {
    float sheen = texture(m_hi, UV2).a;       // facade UV1 from the export, or a per-vertex value on the rails
    ALBEDO = rust_albedo(UV2);                // the existing paint/rust compositing: brown-black, never blue
    METALLIC = 0.0;
    SPECULAR = mix(0.5, spec_sheen, sheen);
    ROUGHNESS = mix(rough_rust, rough_sheen, sheen);
}
```

### 3.3 Portable formats and a Karma check

- **glTF.** KHR_materials_specular gives dielectric F0 = min(0.04 × specularColor, 1) × specular, and
  specularColorFactor may exceed 1 [S 26]: a factor of 2 with a mask-driven texture going 0.5 → 1 gives 0.04 → 0.08
  [I]. With KHR_materials_ior, F0 = ((ior − 1)/(ior + 1))², so ior 1.79 gives 0.08 [S 26; I]. KHR_materials_iridescence
  (ratified; IOR 1.3; 100–400 nm; Belcour–Barla [28]) is not needed [S 26].
- **OpenPBR 1.1.2** [S 29]: `specular_ior` sets F0 (1.79 for 0.08, 2.06 for 0.12); `specular_roughness` 0.55 under the
  mask. `specular_color` could carry the tint, though the spec calls non-white values "technically unphysical". Keep
  `thin_film_weight` 0. The film (`thin_film_thickness` in µm, default 0.5; `thin_film_ior` 1.4) modulates the base's
  Fresnel. Standard Surface takes `thin_film_thickness` in nm [S 30]. Houdini 22 lists MtlX OpenPBR Surface [S 31].

### 3.4 Cost

- **Sheen through F0 and roughness:** no extra lighting work; two lerps on a mask channel already sampled [I].
- **Coloured F0 on Substrate:** needs the Adaptive GBuffer (§3.1).
- **Thin film:** the Khronos reference sums two orders, about 15 sqrt, 8 exp and 8 cos plus vector work per call
  [S 27; I], for every light and for the environment. On a screen-filling facade that is close to a second BSDF, which
  Epic puts at twice the lighting cost [S 19]. In Godot it would tint direct light only (§3.2). Not affordable for an
  effect the sky already makes [I].

## 4. What the generator should bake

- **Layer `rust_sheen`, alpha only, never composited into the albedo** [I; repo]. In `rust_flow.py`, after `dark` (the
  `C_DARK` weight): `sheen = clip((dark − 0.5) / 0.5, 0, 1) × smoothstep(0.55, 0.8, u) × place`, with u the rust age.
  `place` is 1.0 at feet, joints, the bottom rail and the rails' upper rows; 1.3 on the top rail's upper row in the
  0.8–1.2 m hand zone; 0.4 elsewhere; 0 on the bright class or within 2 cm of a front. Cut by quantile to R10's share
  (nominal 10 % of the rusted steel at rust 1.0), 0 below rust 0.5. Reuse the 3–5 cm `nd`/`nv` fields, so the sheen sits
  in the darkest part of each dark patch.
- **Export.** `M_hi.A` on steel pixels, as R and G are already overloaded on steel. Efflorescence is a concrete layer:
  assert its alpha is 0 on steel. Note it in the `wx_export` docstring and the shader contract. If the rails keep the
  1.1 vertex-colour path, store each segment's mean sheen as a per-vertex float [I].
- **Resolution.** 50 px/m carries the amount. The 1–5 cm patches (`DARK_WET_SCALE_M` 0.03 m; the studs in 34a are
  2–3 cm) come from the rust detail by the coverage-preserving reveal, restricted to fine dark-scale pixels. No new
  texture is needed, and 8 bits suffice (one level is 0.4 %) [I].
- **Base colour.** Keep `LAB_DARK`. At most, let sheen pixels drift toward magnetite black, to Lab (25, +5, +5) at equal
  Y [M 8; I]. Never bake view-dependent blue: b* ≥ 0 on all rusted steel.

## 5. Previewing it

- **Today** `lit()` is albedo × ((0.45 + 0.15·up)(1 − 0.4·cav) + 0.75·sun·face), with no reflection [repo]. In the same
  units its ambient implies a sky of mean radiance 0.60 and a ground of 0.30 [I].
- **Add** `spec = (F0·A + B) × L_env(mirror)`, with A and B from Karis's EnvBRDFApprox at the pixel's roughness and N·V
  (free to reuse without attribution [S 32]):
  - F0 0.04 everywhere and 0.08 under the sheen; roughness by class: coat 0.86, rust 0.88, sheen 0.55, painted steel 0.45.
  - Stated clear sky [C]: horizon 0.80 × (0.869, 1.009, 1.296) (9,000 K), zenith 0.50 × (0.721, 1.004, 1.781)
    (20,000 K), linear in sin(elevation), cosine-weighted mean 0.60; ground 0.30, neutral. Stated overcast [C]: the
    CIE overcast sky (zenith 3× the horizon) at 6,500 K, mean 0.60. Skylight spans 3,800 K to infinity [S 33].
- **The elevation view is the palest case.** Straight on, every front face mirrors the horizon behind the camera, and
  rail tops are edge-on. Dark scale, sunlit: (25, +10, +11) today, (30, +8, +7) with F0 0.04, (36, +7, +2) with the
  sheen. Shaded: (15, +8, +9), then (22, +5, +2), then (31, +4, −1.5). A player pass from 30° below mirrors sky at 30°:
  sunlit sheen (34.5, +7, +1), shaded (29, +4, −3.4) [I].
- **Show it twice.** On the review page as a button: the same shot, "diffuse only" against "with sky reflection". And
  as a material-ball strip, where strength is judged: a 40 × 40 mm rail section and a 16 mm flat bar at 0°, 45°, 70° and
  80°, clear and overcast, sheen off and on. Gates keep measuring albedo; the reflection is for review only [I].
- **In engine, expect** [I] a sheen that moves with camera and sun: strongest on scale in shade under a clear sky and on
  rail tops seen from the balcony, faint on sunlit faces (b* about −3.5), grey under overcast. It reflects whatever feeds
  the reflections (UE sky light, Lumen, captures; Godot sky, ReflectionProbe, SDFGI); a probe captured inside the
  balcony mirrors the ceiling. The preview's one fixed reflection checks placement and strength, not the look.

## 6. Proposed rules

In the rulebook's form, for rulebook 1.8. The numbers tagged C need calibration on the user's picks.

```json
[
 {"id": "R10", "family": "metal", "title": "Dense dark scale carries a rough sheen",
  "measure": "railing steel: the sheen layer (alpha >= 0.5; M_hi.A on steel in the export) against the rust amount: its share of the rusted steel (R1's rust pixels); the share of sheen pixels in the dark class (albedo L* <= 32), in the bright class and within 2 cm of a rust front; the share at feet, joints, the bottom rail and rail tops (the top rail's 0.8-1.2 m hand zone counted with the tops); sheen on paint or bare metal",
  "pass": "none below rust 0.5; <= 2 % at 0.5, 2-8 % at 0.75, 4-15 % at 1.0; >= 90 % in the dark class; none in the bright class or within 2 cm of a front; >= 60 % at feet, joints, the bottom rail and rail tops; none on paint or bare metal",
  "origin": "U (after round J: 'subtle touches of blue rusting on the rust ... a rough blue sheen on the darker rust surfaces'); L (research rust-blue-sheen.md §1: compact goethite, magnetite, maghemite and hematite reflect 13-31 %, bluish in reflected light; magnetite forms under thick, wet rust); P (Nyhavn tread plate, Midway close-up); C (shares)", "binding": true},
 {"id": "R11", "family": "material", "title": "The sheen is F0 and roughness, never albedo",
  "measure": "rusted-steel albedo: the median Lab of sheen pixels against dark-class pixels without sheen, and the share of rusted-steel pixels with b* < 0; the material contract: F0 (or Specular) and roughness under the sheen mask and on other rust; the material ball (§5), sunlit at normal view under the stated clear sky: dL* and db* of dark scale with the sheen against F0 0.04 at roughness 0.85",
  "pass": "sheen pixels within +-3 L* and +-3 b* of the dark class, with a* >= +1; no rusted-steel pixel with b* < 0; F0 0.06-0.12 (UE Specular 0.75-1.0 or a Substrate F0; Godot SPECULAR 0.61-0.87), grey unless the target keeps coloured F0 (then B/R <= 1.2); roughness 0.45-0.65 under the mask and >= 0.8 on other old rust; F0 0.04 elsewhere; ball dL* +4 to +12 and db* -2 to -8",
  "origin": "U ('better off as a material shader'); L (UE: Specular 0.5 = 4 %, F0 = 0.08 x Specular; Godot: F0 = 0.16 x SPECULAR^2; the game-engine target: looks in portable materials, no post); I (split-sum sky arithmetic, research rust-blue-sheen.md §1.3 and §5); C", "binding": true}
]
```

R9 is unaffected, because the sheen never changes the albedo; R6's medians hold if the optional drift stays on at most
15 % of the rust [I]. The ball reads dL* +6.4 and db* −4.4 at F0 0.08, +10.4 and −6.3 at 0.12; 0.16 fails the cap [I].

## 7. Unchecked

- **Not found or not read:** any published gloss or BRDF of rust scale (porous F0 is my estimate; roughness 0.55 is
  craft); Mindat, PMC and the CSIC exfoliation papers (Morcillo et al. 2017) refused the fetcher; the NBS
  temper-colour table (McAdam and Geil) was too large. The photos are three, uncalibrated, none of a Japanese rail.
- **Engines and formats:** the Thin-Film node's unit; whether Blendable stores grey F0 0.08 exactly as Specular 1.0
  (expected); Clear Coat's cost; a Godot specular texture slot; KHR_materials_specular import; Karma XPU thin film.

## 8. Sources

1–5. Anthony et al., Handbook of Mineralogy (Mineral Data Publishing): 1 hematite, 2 magnetite, 3 goethite,
   4 maghemite, 5 lepidocrocite — https://www.handbookofmineralogy.org/pdfs/hematite.pdf (and `magnetite.pdf`, `goethite.pdf`, `maghemite.pdf`, `lepidocrocite.pdf`)
6. Querry 1985 (CRDC-CR-85034) via refractiveindex.info — https://refractiveindex.info/?shelf=main&book=Fe3O4&page=Querry ;
   data: https://github.com/polyanskiy/refractiveindex.info-database (`data/main/Fe3O4/nk/Querry.yml`, `Fe2O3/nk/Querry-o.yml`, `Querry-e.yml`)
7. Yamashita et al. 2017, Zairyo-to-Kankyo 66:93 — https://ir.library.osaka-u.ac.jp/repo/ouka/all/82362/ztk_66_3_93.pdf
8. `weathering-rust-water.md` §6 (S35 magnetite pigment; S38 Alcántara et al. 2017, inner layer dark grey goethite and magnetite)
9. `coatings-concrete-corrosion.md` §3 (source 30, mill scale)
10. Revista de Metalurgia, rust exfoliation in marine atmospheres (snippet; fetch refused) — https://revistademetalurgia.revistas.csic.es/index.php/revistademetalurgia/article/download/1480/1829?inline=1
11. Yamashita et al. 1998, ISIJ International 38:285 (snippet) — https://www.jstage.jst.go.jp/article/isijinternational1989/38/3/38_3_285/_article/-char/ja
12. Wikipedia, Bluing (steel) — https://en.wikipedia.org/wiki/Bluing_(steel)
13. Wikipedia, Tempering (metallurgy) — https://en.wikipedia.org/wiki/Tempering_(metallurgy)
14. Peet and Bhadeshia, Oxide on steel and tempering colours — https://www.phase-trans.msm.cam.ac.uk/2008/Oxide/Oxide.html
15. Rossman and Ma 2025, Iridescent Iron Oxides, Minerals 15:108 — https://authors.library.caltech.edu/records/ykxsp-shv79
16. Wisconsin DNR, Bio Sheen Fact Sheet — https://dnr.wisconsin.gov/sites/default/files/topic/Stormwater/MS4/CHEMbiosheen.pdf
17. Epic, Physically Based Materials (5.8) — https://dev.epicgames.com/documentation/en-us/unreal-engine/physically-based-materials-in-unreal-engine
18. ikrima.dev, UE4 base shader code flow (snippet; 403) — https://ikrima.dev/ue4guide/graphics-development/render-architecture/base-usf-shaders-code-flow/
19. Epic, Overview of Substrate Materials (5.8) — https://dev.epicgames.com/documentation/en-us/unreal-engine/overview-of-substrate-materials-in-unreal-engine
20. Epic API, UMaterialExpressionSubstrateThinFilm (5.8) — https://dev.epicgames.com/documentation/unreal-engine/API/Runtime/Engine/UMaterialExpressionSubstrateThin-
21. Substrate status: a. UE 5.5 announcement (snippet) — https://www.unrealengine.com/blog/unreal-engine-5-5-is-now-available ;
    b. forum, 5.6 Preview — https://forums.unrealengine.com/t/metahuman-character-textures-appear-black-after-assembling-in-unreal-engine-5-6-preview/2513248/12 ;
    c. 5.7 — https://gamefromscratch.com/unreal-engine-5-7-released/ , https://cgpress.org/archives/unreal-engine-5-7-released.html
22. Unreal forums, Blendable GBuffer discards F0 chromaticity (5.8) — https://forums.unrealengine.com/t/substrate-blendable-gbuffer-silently-discards-f0-chromaticity-for-dark-metals-same-f0-different-results-between-legacy-converted-and-hand-built-slab-materials/2741166
23. Epic, Shading Models (5.8) — https://dev.epicgames.com/documentation/en-us/unreal-engine/shading-models-in-unreal-engine
24. Godot source, `scene_forward_lights_inc.glsl` (F0, F90, clearcoat) — https://github.com/godotengine/godot/blob/master/servers/rendering/renderer_rd/shaders/scene_forward_lights_inc.glsl
25. Godot 4.7, Spatial shaders — https://docs.godotengine.org/en/stable/tutorials/shaders/shader_reference/spatial_shader.html
26. Khronos glTF: KHR_materials_iridescence, KHR_materials_specular, KHR_materials_ior — https://github.com/KhronosGroup/glTF/tree/main/extensions/2.0/Khronos
27. Khronos glTF Sample Renderer, `iridescence.glsl` — https://github.com/KhronosGroup/glTF-Sample-Renderer/blob/main/source/Renderer/shaders/iridescence.glsl
28. Belcour and Barla 2017, A Practical Extension to Microfacet Theory for the Modeling of Varying Iridescence — https://hal.archives-ouvertes.fr/hal-01518344v2
29. OpenPBR Surface specification v1.1.2 — https://academysoftwarefoundation.github.io/OpenPBR
30. Autodesk Standard Surface — https://autodesk.github.io/standard-surface/
31. SideFX, Houdini 22 MaterialX — https://www.sidefx.com/docs/houdini/solaris/materialx.html
32. Karis 2014, Physically Based Shading on Mobile — https://www.unrealengine.com/blog/physically-based-shading-on-mobile
33. Hernández-Andrés and Romero 2001, JOSA A 18(2), clear-sky CCT 3,800 K to infinity (snippet) — https://colorimaginglab.ugr.es/pages/pdfs/josaa_2001_412/!
34. Photos, Wikimedia Commons, read this session: a. Dietmar Rabich, sheet metal at Nyhavn, 2017, CC BY-SA 4.0 —
    https://commons.wikimedia.org/wiki/File:Kopenhagen_(DK),_Nyhavn_--_2017_--_1711.jpg ; b. Tuxyso, rusty sheet piling at Carolinensiel, 2026, CC BY-SA 4.0 —
    https://commons.wikimedia.org/wiki/File:Rostige-Stahlspundwand-Schatten-Carolinensiel-Morgens-2026.jpg ; c. Kris Krüg, rusty texture, Midway Island, 2011, CC BY-SA 2.0 —
    https://commons.wikimedia.org/wiki/File:Journey_to_Midway_Island_(5559099910).jpg
35. Wyman, Sloan and Shirley 2013, analytic CIE colour-matching functions, JCGT 2(2) — https://jcgt.org/published/0002/02/01/
36. Odesa University study of iron oxidation: the oxide's colours from yellow to blue span 46–72 nm (snippet) — https://dspace.onu.edu.ua/items/1d6575ee-e548-4085-8876-c61cb7306c6e

## 9. Actions

| # | Action | Status |
|---|---|---|
| 1 | R10 and R11 into `weather_rules.json` (rulebook 1.8) with a gate check | done (rulebook 1.8 R11, the sheen's share, place and no blue albedo; `scripts/weathering/gate_rk.py`) |
| 2 | `rust_sheen` layer in `rust_flow.py`: dark weight × age × place, cut by quantile to R10's share, 0 below rust 0.5 | done (`scripts/weathering/rust_flow.py` `_sheen`: the darkest old scale, wet parts and the hand zone weighted, cut by quantile to the share, none below rust 0.5) |
| 3 | Export the sheen in `M_hi.A` on steel pixels; assert no efflorescence on steel; document it in the shader contract | done (`scripts/weathering/wx_export.py`: `M_hi.A` on steel pixels is the sheen, written in place of efflorescence, whose layer the paint mask keeps off the steel; the channel table in `.claude/skills/large-scale-texturing/references/texturing-at-scale.md`) |
| 4 | Optional neutral drift of sheen pixels' albedo toward Lab (25, +5, +5); never b* < 0 | parked (not adopted: R11 keeps the albedo unchanged; revisit after the in-engine look of row 10) |
| 5 | UE: `MF_RustSheen` on the steel material (Specular 0.5 → 1.0, roughness → 0.55; Substrate F0 0.04 → 0.08, grey) | parked (UE `MF_RustSheen` on the steel material: Specular 0.5 -> 1.0 and roughness -> 0.55 under the mask; revisit at the first engine round trip) |
| 6 | Godot: steel spatial shader (`SPECULAR` 0.5 → 0.707, `ROUGHNESS` → 0.55 under the mask) | parked (Godot steel shader: `SPECULAR` 0.5 -> 0.71 and `ROUGHNESS` -> 0.55 under the mask; revisit at the first engine round trip) |
| 7 | `wx_hires.lit`: split-sum sky reflection (F0 0.04 everywhere, 0.08 under the sheen; stated clear and overcast skies), behind a review-page button | done (`scripts/weathering/wx_hires.py` `spec_term` and `lit(spec=True)`: split-sum sky reflection, F0 0.04 and 0.08 under the sheen, a stated clear sky; the round-K review's sheen toggle via `roundF/render_player_k.py --spec`) |
| 8 | Material-ball strip (rail section and flat bar; 0°, 45°, 70°, 80°; clear and overcast; sheen off and on) for judging strength | parked (the round-K review shows the sheen on the rails at 1:1 with the sky reflection on and off; a ball strip waits for the engine look of row 10) |
| 9 | Skill text: a "dense scale (sheen)" row in the rust zone table of `paint-rust-concrete.md`, and a trap: "dark rust's look is its reflection; never blue albedo; previews without a reflection term read dark surfaces 5–7 L* too dark" | done (`.claude/skills/procedural-materials/references/paint-rust-concrete.md`: a dense-scale row in the rust zone table and the paragraph 'The blue sheen is a reflection, never a colour') |
| 10 | Strong tier (F0 0.10–0.12, tint (0.92, 1.00, 1.10)) only on Substrate Adaptive or Godot `SPECULAR` 0.87, after an in-engine look | parked (the strong tier needs Substrate Adaptive or Godot `SPECULAR` 0.87; revisit after an in-engine look) |
| 11 | No thin film or iridescence on rails; revisit only if the ground kit gets standing water at post feet (bio-sheen) | parked (no thin film or iridescence on the rails; revisit only if the ground kit gets standing water at post feet) |
| 12 | Optional Karma check: OpenPBR `specular_ior` 1.79 and `specular_roughness` 0.55 under the mask | parked (optional Karma check of OpenPBR `specular_ior` 1.79 and `specular_roughness` 0.55; revisit if a Karma render of the rails is wanted before the engine round trip) |
