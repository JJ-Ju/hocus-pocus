# Tiling, height blending and scatter: algorithms for the layered facade material

Research note, 2026-11-01. The danchi facade moves from one unique 50 px/m albedo to tiling
detail sets at about 1024 px/m, rule-driven masks at 25–50 px/m, and decals. This note gives the
algorithms. Pipelines, trim sheets and UDIMs are in the sibling `texturing-at-scale.md`. It
extends `layering.md` (R1, R2) and `weathering-grid-breakup.md` §2–3.

Tags: **[C]** consensus or vendor spec · **[P]** one practitioner's practice · **[M]** measured or
published data · **[I]** my inference.

"Measured here" means scratchpad runs of the §5 code (not in the repo): a tileable 512² map over
2048² px (4 × 4 periods). The test maps are *gauss* (Gaussian, correlation about 10 px), *spots*
(15 % bimodal cover, like lichen dots) and *cells* (Voronoi stones with dark joints).

## 0. Recommendations

| Job | Use | Cost per pixel |
|---|---|---|
| Stochastic detail: coat, dirt film, biofilm, rust bloom | **hex-tiling** (Mikkelsen), one weight set per material taken from its height | 3 `SampleGrad` per map |
| The same, when the histogram must hold (lichen dots, rust pits) | **Burley's histogram-preserving blend**, γ = 4 | 3 fetches + 1 LUT fetch per channel |
| Structured detail: aggregate, stones, formwork | **random offset per precast panel**, cell borders on real joints; corner tiles (≥ 3 colours) elsewhere | 1 fetch |
| Low-res mask to a crisp edge | **coverage-preserving reveal** on an equalised height with **re-equalised mips**; mask upsampled by **B-spline**; **SDF** for geometric edges | 1 height + 4 bilinear fetches |
| Stamps from a mask | Poisson with **λ = −ln(1 − m)/E[A]**, power-law sizes; Thomas clusters with λ × about 1.1 | offline |
| Runs and rust streaks | trace the water path, split it into falling runs, **chain overlapping decals** (head, body, tail) | 1 decal per 1–1.5 m |

Why, as measured here [M]: hex keeps 95–97 % of contrast with no preprocessing. Burley matches the
histogram best. The reveal holds mean cover exactly at every mip. The Boolean λ hits cover within 0.9 %.

## 1. Repetition-free tiling

| Pitfall | Cause | Fix |
|---|---|---|
| Mip seam lines | `ddx(uv)` jumps where a cell's offset jumps, so a 1 px line takes a coarse mip [C GPU Gems] | derivatives of the continuous uv, transformed like the uv (rotate, mirror, scale), into `SampleGrad` [C Mikkelsen] |
| Visible seams | an unblended cell border | blend 2–4 samples, or put the border under a real joint [I] |
| Contrast loss | a linear 3-sample blend scales σ by √Σw² ≥ 0.577 [C HN] | variance-preserving blend [C], exponentiated weights [C Burley], gain [C Mikkelsen] |
| Histogram change, ghosting | bimodal values blend into mid-greys | Gaussianise first (HN), or let one sample dominate (high γ) |
| Mean shift | luminance or height weights favour bright samples | spots +0.011 on a mean of 0.15 with hex [M]; fold it into the equalisation (§2) |
| Maps disagree at transitions | albedo, normal and ORM blended with different weights | one weight set per material, reused for every map [I] |
| Tile choice differs between GPUs | `frac(sin(x)·43758)` loses precision at large ids | integer `pcg2d` [C Jarzynski & Olano], bit-identical in numpy, HLSL and GLSL |

**Hex-tiling** (Mikkelsen 2022, JCGT 11(2):77–94; [C] unless tagged).
- **Grid.** Scale `st` by 2√3 and skew it by rows (1, −1/√3) and (0, 2/√3). With `f = frac`,
  `z = 1 − f.x − f.y`, `s = step(z, 0)` and `s₂ = 2s − 1`:
  - the weights are `(−z·s₂, s − f.y·s₂, s − f.x·s₂)`;
  - the vertices are `b+(s,s)`, `b+(s,1−s)` and `b+(1−s,s)`;
  - the hex centres are `(v.x + v.y/2, v.y·√3/2)/2√3`, 0.289 tile apart.
- **Weights.** Each vertex samples `Rᵢ(st − cᵢ) + cᵢ + oᵢ`, with a hashed offset and rotation.
  Weights are `∝ (0.4 + 0.6·metric)·wᵢ⁷`. The metric is luminance for colour, and
  `√(|d|²/(1+|d|²))` for normals.
- **Gain.** `½(2x)^k` below ½ and `1 − ½(2−2x)^k` above, with `k = log(1−r)/log ½`. Use
  r = 0.65–0.75 for colour and 0.5 (off) for normals.
- **Normals.** Sample them as derivatives `d = −n.xy/n.z`. Rotate back by `Rᵢᵀ`, blend, and output
  `normalize(−d, 1)`. Rotation works because there is no histogram transform.
- **Cost.** 3 `SampleGrad` per map, plus 3 hashes, `sincos` and `pow`. No GPU timing is published.
- **Pitfalls.** At high r the hexagons show [C Unity README]. Never rotate directional content such
  as runs and laps [I]. Take the metric from the layer height: the tiles then height-blend, and
  one weight set serves every map [I].

**Histogram-preserving blending** (HN 2018, DH 2019, Burley 2019; [C] unless tagged).
- **Gaussianise each channel:** `T(v) = ½ + σΦ⁻¹(F(v))`, with F the rank and σ = 1/6. Burley
  truncates the Gaussian to [0, 1]; the infinite one puts about 0.3 % of texels outside
  [M Burley].
- **Blend.** Each lattice vertex reads a randomly offset patch. `G = Σwᵢ(Gᵢ − ½)/√Σwᵢ² + ½`
  restores the variance, but pushes up to 8.2 % of equal-weight pixels out of [0, 1]
  [M Burley]. Burley's soft clip `S*` (linear on the middle half of the output, quadratic ends;
  §5) avoids that.
- **Invert** with the LUT `T⁻¹(g) = F⁻¹(Φ((g − ½)/σ))`. Unity Labs uses 128 entries and one row per
  LOD; each row is blurred by the mean sub-pixel variance of `T` in 2^L windows.
- **Colour.** HN's 3D optimal transport took minutes per 256² [M Burley]. DH use the PCA basis.
  Burley works per channel, or on Y only.
- **Weights** `w^γ/Σw^γ`. Ghosting at γ ≤ 2, structure visible at γ ≥ 8, and γ = 4 for most maps
  [M Burley]. Unity's slider spans γ = 1–16.
- **Cost.** 3 `SampleGrad` + 4 LUT `SampleLevel` per RGBA map (Unity). Preprocessing takes under
  1 ms, and a 4K² image takes 75 ms on 24 CPU cores [M Burley].
- **Limits.** Offsets only, so stochastic maps only, and no rotation of normal maps
  [C Mikkelsen]. A variance-only blend keeps σ but not the histogram (spots W1/σ 0.295) [M].

**Texture bombing** (GPU Gems ch. 20; [C] unless tagged).
- **Method.** Each UV cell holds n candidates, each with a random position, image index and
  priority. A pixel checks its 2 × 2 neighbour cells (3 × 3 if an image can span a cell), and the
  top priority wins. A start priority of 0.5 rejects half. Rotated content must fit a circle of
  diameter 1.
- **Cost.** 4n image fetches, plus a hash or 4n random fetches. The 2D example uses "eight texture
  samples and 44 math instructions" [M].
- **Pitfalls.** With n = 1 the grid shows. A mipmapped random texture jumps LOD at cell borders, so
  use NEAREST or LINEAR on it. Atlas borders bleed at coarse mips: clamp them or pad each level.
- **Use.** Sparse marks inside a layer, not full cover [I].

**Wang and corner tiles.**
- **Wang tiles** match coloured edges [C Cohen 2003].
  - Wei packs a complete set into one atlas whose shared edges all match, so filtering across
    borders is correct.
  - The lookup takes 2 reads, 25–50 % slower than one texture on a GeForce 6800 GT [M].
  - Clean the low mips by averaging same-colour edges [C].
- **Corner tiles** colour the corners, which also constrains diagonal neighbours [C Lagae & Dutré].
  - 2 colours give 16 tiles: `id = c₀₀ + 2c₁₀ + 4c₀₁ + 8c₁₁` from hashed vertex bits, then one
    fetch.
  - The 4 × 4 torus `1110/1101/0100/1000` holds each 2 × 2 pattern once [M]. In that atlas order
    every neighbour matches, so filtering and the first mips are right across borders [I].
  - There is no runtime blend: structure survives, and any map works [I].
- **Measured.** Corner patches recur on the lattice: NCC 0.31–0.36 at 512 px, and a blind ACF peak
  of 0.55–0.60 against a null of 0.09 [M].
- **Fix:** ≥ 3 colours, small corners, and quilted unique interiors [I].

**UE TextureVariation** (4.26 and later).
- **Pins** [C, from the material code in Epic's forum post]. In: Heightmap, UVs, Variation Scale,
  Variation Levels, Heightmap Influence, Mask Channel, Use Dither, Random Rotation and Scale, HQ
  Edge Comparison. Out: Shifted UVs, Raw UVs, DDX, DDY, Random Offset. Set the Texture Sample's
  MipValueMode to Derivative.
- **Internals** are undocumented; a tutorial says it shifts UVs rather than taking many samples
  [P]. My reading: noise-quantised offset regions with height-moved, optionally dithered edges
  (dither needs TAA or TSR). That is Quilez's third technique at about 1 fetch per map [I].
- **The older Texture Bombing** (4.13) blends offset, flipped and rotated samples, with an
  optional height lerp [C].

**Per-cell offset and rotation.**
- **Quilez's first technique** hashes a per-tile offset and orientation, and blends 4 neighbour
  tiles near the borders: 4 fetches. The hash may alias under strong minification [C].
- **His third technique** takes `l = 8·noise` from a low-frequency noise, then blends offsets
  `floor(l)` and `floor(l)+1` by `smoothstep(0.2, 0.8, fract(l) − 0.1·Σ(a − b))`: 2 fetches plus
  1 noise [C, Godot port].
- **Unblended, per precast panel**: 1 fetch, and the joint hides the seam [I]. But it copies whole
  panels, so the period test passes and the blind ACF flags 0.33 [M].
- **Quarter turns and mirrors** are exact on texels. Swap and negate the derivatives the same way
  [C].

**Measured comparison** (2048², 512 px period; fetches per map) [M]

| Method | Fetches | σ/σ₀ gauss | W1/σ₀ spots | spot mid-grey share (source 0.085) | W1/σ₀ cells | NCC at period | blind ACF peak | numpy s |
|---|---|---|---|---|---|---|---|---|
| plain tile | 1 | 1.000 | 0 | 0.085 | 0 | 1.000 | 1.00 | 0.4 |
| offset per cell, no blend | 1 | 0.998 | 0.014 | 0.092 | 0.013 | 0.006 | 0.33 | 0.7 |
| offset + transpose or mirror, 2 × 2 blend | 4 | 0.882 | 0.127 | 0.166 | 0.132 | 0.007 | 0.16 | 2.0–2.7 |
| triangle grid, linear | 3 | 0.709 | 0.263 | 0.258 | 0.271 | 0.018 | 0.16 | 1.3 |
| triangle grid, variance only | 3 | 1.001 | 0.295 | 0.224 | 0.065 | 0.019 | 0.16 | 1.3–2.9 |
| HN/DH histogram, γ = 1 | 3 + 1/ch | 1.003 | 0.030 | 0.081 | 0.023 | 0.020 | 0.15 | 1.8 |
| **Burley, γ = 4, soft clip** | 3 + 1/ch | 0.993 | **0.015** | 0.081 | **0.020** | 0.016 | 0.14 | 1.3–1.7 |
| hex, r = 0.5, no rotation | 3 | 0.940 | 0.069 | 0.129 | 0.073 | 0.013 | 0.13 | 2.3 |
| **hex, r = 0.75, rotation** | 3 | 0.966 | 0.050 | 0.114 | 0.052 | 0.008 | **0.11** | 1.5–2.6 |
| corner tiles, 2 colours (blended atlas: worst case) | 1 | 0.967 | 0.192 | 0.222 | 0.122 | 0.36 | 0.60 | 0.9–2.8 |
| null: a unique field, no tiling | — | — | — | — | — | ≤ 0.015 | ≤ 0.093 | — |

## 2. Height blending and mask refinement

| Operator | Maths | Mean cover at amount a (uniform h) |
|---|---|---|
| UE **HeightLerp** (A, B, Transition Phase, Height, Contrast) | pins documented; "Leaving this at 0.5 performs a standard lerp" [C]. `α = CheapContrast(sat(h + 2T − 1), c)` is my reading [I] | 2a² for a ≤ ½, if that reading holds [I] |
| Substance **Height Blend** | Adobe refused my fetcher. From memory: top and bottom heights, an optional mask, Height Offset, Contrast [P] | not documented |
| HDRP **ApplyHeightBlend** | `hᵢ′ = (hᵢ − min h)·maskᵢ`; `wᵢ = (max(0, hᵢ′ − max h′ + t) + 10⁻⁶)·maskᵢ`, scaled so the tallest is 1; then top layer first, `outᵢ = min(wᵢ, 1 − Σ upper)` [C] | not controlled: the tallest wins |
| `layering.md` R1 | `t = 1 − a(1 + w)`, `smoothstep(t, t + w, h)` | **a + w(a − ½)** [I] |
| Naughty Dog vertex blend | not found. The Uncharted 4 deck (13 MB) was over my fetch limit; its topics list only moss and wetness shading [C] | — |

**The coverage-preserving reveal** [I].
- Equalise the layer's height to its rank, so `h_eq ~ U(0, 1)`. Set `c = 1 − a` and
  `ŵ = min(w/2, a, 1 − a)`.
- Then **`m = smoothstep(c − ŵ, c + ŵ, h_eq)`** has `E[m] = a` exactly. The smoothstep is odd about
  c, and its window stays in [0, 1].
- R1's window `[1 − a(1+w), 1 − aw]` is off-centre, which is its bias.

| a | 0.05 | 0.10 | 0.25 | 0.50 | 0.75 | 0.90 |
|---|---|---|---|---|---|---|
| R1 cover, w = 0.1 / 0.2 [M] | 0.012 / 0.005 | 0.060 / 0.030 | 0.225 / 0.200 | 0.500 / 0.500 | 0.775 / 0.800 | 0.940 / 0.970 |
| new reveal [M] | 0.050 | 0.100 | 0.250 | 0.500 | 0.750 | 0.900 |

- **Against a 64² mask upsampled ×32,** 32 px block means track the mask: bias +0.0004, RMS 0.076,
  p99 0.20. R1's bias is −0.015 [M].
- **The RMS** is the height's own pattern. It shrinks when the height's main wavelength is well
  below a mask texel [I].
- **8-bit or BC4 heights:** equalise from the decoded texture [I].

**Several layers** [I unless tagged].
- **Order.** Stack them as they formed: coat → film → biofilm and lichen → dirt crust → rust run →
  decals. Fill-low layers use `1 − h_surface`; growth uses `h_surface` [C `layering.md`].
- **Independent heights** composited by sequential "over": layer i shows `aᵢ·Π_{j>i}(1 − aⱼ)`.
  Write amounts "as if alone", and report the visible shares.
- **One shared height:** use exclusive quantile bands `[1 − A_k, 1 − A_{k−1})`, with
  `A_k = Σ_{j≤k} a_j`. Each layer then covers exactly `a_k`: crust deepest, then dirt, then film.
- **Max-height blends** (R2, HDRP) take the locally tallest layer, so the shares follow the height
  ranges, not the masks. Iterate a per-layer bias offline, `qᵢ += η(coverᵢ − aᵢ)`.

**Width, distance and mips.**
- A width w in height units spans `w/|∇h|` px. Keep `ŵ ≥ fwidth(h_eq)`: the two-texel rule in
  screen space [I].
- Box mips narrow the histogram, so the fixed quantile loses cover. Widening w with LOD does not
  help: a = 0.3 drops 0.300 → 0.128 by mip 4 [M].

| mip | 0 | 1 | 2 | 3 | 4 |
|---|---|---|---|---|---|
| σ(h) | 0.289 | 0.261 | 0.211 | 0.159 | 0.106 |
| cover, a = 0.1 / 0.3, plain mips [M] | 0.100 / 0.300 | 0.065 / 0.266 | 0.020 / 0.197 | 0.002 / 0.112 | 0.000 / 0.030 |
| cover, a = 0.1 / 0.3, re-equalised mips [M] | 0.100 / 0.300 | 0.100 / 0.300 | 0.100 / 0.300 | 0.100 / 0.300 | 0.100 / 0.300 |

Fixes, best first:
1. **Re-equalise every mip offline**, and ship that chain. It is exact at every level, at no runtime
   cost [M]. Castaño did this for one alpha reference [C].
2. **A per-LOD quantile LUT** `c = Q_L(1 − a)`, 64 × L. Compute L as
   `½·log₂ max(|∂(uv·N)/∂x|², |∂(uv·N)/∂y|²)`, as Unity's code does [C].
3. **Fade m toward a beyond some LOD** [I].

**Upsampling the mask** (64² → 2048², ×32; [M] unless tagged).
- **Bilinear** puts all the curvature on the coarse node lines (lattice index 4.8·10⁵). Iso-lines
  kink there: the "diamonds".
- **A cubic B-spline** is C2 [C], with an index of 1.33. It smooths, though: iso-contour IoU 0.797,
  against bilinear's 0.846.
- **With Unser's prefilter** (pole √3 − 2) it interpolates: IoU 0.896, index 1.45 [C, M].
  - It costs 4 bilinear fetches on a GPU [C Sigg & Hadwiger].
  - Store the coefficients as R16F: they leave [0, 1] [I].
- **No 4-fold orientation bias** was measurable (0.013, against the truth's 0.028).
- **Geometric edges** (repaint patches, the wet-band top, shelter lines): store a signed distance.
  Green 2007 turns a 4096² binary into a 64² SDF, 0.5 = edge [C].
  - Edge error: 0.72 px, against 2.10 px for bilinear coverage and 1.91 px for B-spline coverage.
  - Corners round by up to 10.5 px: use two channels with AND, or MSDF [C Green].
  - Breakup: `m = smoothstep(−ŵ, ŵ, sd + k(h_eq − ½))` [I].

**Detail around a macro value, keeping the mean.**
- `M + k(d − d̄)` keeps it unless something clamps [C].
- `M·d/d̄` keeps it if d is independent of M [C].
- `M·exp(kZ − k²σ²/2)` always keeps it, like the generator's `lognormal` [C].
- So does overlay with d̄ = 0.5, which is linear in d for a fixed M [I].
- Take d̄ in linear space, not sRGB [I]. Mips keep a mean-neutral detail neutral; thresholds
  need the fixes above [I].

## 3. Stamp, decal and scatter distribution

- **Density from a mask.** Poisson stamps of mean area E[A] cover `1 − e^(−λE[A])` [C Boolean
  model], so set **`λ(x) = −ln(1 − m(x))/E[A]`**.
  - Alpha stamps composited "over" cover `1 − exp(−λ∫α)` [I].
  - With 3–40 px discs the cover is 0.2720 for a 0.2744 target. The naive `m/E[A]` gives 0.2340,
    15 % short [M].
- **Sizes.** Use a truncated Pareto, `s = (s_min^−α − u(s_min^−α − s_max^−α))^(−1/α)`.
  - At α = 1.5: median 4.7 px, p95 17.7 px; the top 10 % hold 61 % of the area [M].
  - Big marks belong in clusters [C `r4-noise.md`].
- **Clusters** (Thomas, a Neyman–Scott process). Draw parents at `λ/μ` from the mask, each with
  Poisson(μ) Gaussian children [C spatstat].
  - At the same λ, overlap loses 8.6 % of the cover (σ 30 or 60 px, μ = 8) [M].
  - Scale λ by `ln(1 − m̄)/ln(1 − c̄)`, about ×1.11 here [M]. Average over draws, and pad the region
    by 3σ [I].
- **Blue noise with variable density:** Bridson with a radius map, `r(x) = r₀/√(ρ/ρ_max)`, a grid
  of `r_min/√2`, and the symmetric rule `|p − q| ≥ max(r_p, r_q)` [C/I].
  - **Pitfall:** candidates at 1–2 × the parent's radius never enter a sparser zone; at a
    10 → 20 px step the density came out 215 : 1. Stepping by the candidate's own radius gives
    3.6–4.0, with 4 expected [M].
  - On a smooth map: block counts against 1/r², r = 0.96; packing 0.48 of hexagonal [M].
- **Other blue-noise routes.**
  - Sample elimination (Yuksel 2015) thins a 3–5× larger set, keeps every prefix blue noise, and
    supports adaptive density [C].
  - In a shader, keep a texel where blue noise B < ρ(x), using Peters' CC0 void-and-cluster
    textures (16²–1024²). A tiled 64² still shows up close, so offset it per tile [C].
- **Flow.** Orient each mark along the path tangent, ±3°. Length-to-width is 5–30 on vertical
  walls, lower on slopes. Mirror freely, flipping the normal's x [I].

| Tool | How it places | Our use [I] |
|---|---|---|
| Substance **Tile Sampler** | X × Y grid, one pattern per cell; random position, rotation, scale, luminance; mask, scale and rotation maps read at each instance centre [P: Adobe refused my fetcher] | trims and decal atlases only: it is a grid |
| Substance **Shape Splatter** | splats shapes from a distribution, height-blended, with per-instance data outputs [P] | the same |
| Houdini **Stamp Points** (Copernicus) | SOP points; the `stamp` attribute picks one of up to 10 layers; `pscale`/`orient` or sprite attributes; Depth-Sorted Over, Order-Independent Over, Add, Sub, Mul, Max, Min; outputs the dominant stamp's `id` and `uv`; wrap mode for tileable output [C] | bake stamp layers and decal atlases from our point lists |
| UE **PCG** | Surface Sampler is a jittered grid (looseness, points per m²); Self Pruning removes overlaps by size priority, with random ties; Density Filter, Distance, Attribute Noise, Transform Points, Spline Sampler, Spawn Actor; no Poisson-disk node [C] | spawn decal actors from our exported lists |

**Runs and rust streaks along water paths** [I, after Dorsey et al. 1996]:
1. **Sources.** Keep `sources_along_tops` (Poisson thinned by a 1D cascade, 6 cm spacing). Add sill
   ends, joint ends and fixings.
2. **Trace.** Step down a row at a time with a damped wander. On a ledge, run to the nearest free
   end, then fall.
3. **Split** into falling runs. Each starts at a drip point with a head decal. The ledge part gets
   a sill-end stain stamp.
4. **Chain** 1–1.5 m decals with 20 % overlap (head, random body, tail). Taper the width and
   mirror at random.
   - Measured: a 3 m sill sends its run to the nearer end, and it falls 9 m. That makes 9 decals
     of 1.2 m, within ±7°, tapering 23 → 11 cm [M].
5. **Export.** `stamp_run` already returns x, y, L_m, w_m and peak, so emit those as decal
   instances. The rasterised run stays in the mask as macro tone.

## 4. Tests that catch repetition and grids

| Test | Definition | Measured here [M] | Threshold [I] |
|---|---|---|---|
| NCC one period apart | Pearson r of I(x) and I(x + P), along x and y | tile 1.000; corner tiles 0.31–0.36; blended ≤ 0.020; null ≤ 0.015 | ≤ 0.05 (2048² window, correlation ≤ 10 px) |
| **Period z-test** | z of NCC(P) against NCC at 48 off-period lags (0.6–1.4 P) of the same image | tile 19–64; corner tiles 9–26; blended ≤ 1.8; null ≤ 1.61 | **fail if z > 4**; robust to the texture's own correlation |
| Blind ACF peak | max normalised ACF (Hann window, window ACF divided out) for r₀ ≤ \|lag\| < W/2 | tile 1.0; unblended offsets 0.33; corner tiles 0.55–0.60; blended 0.04–0.16; null 0.08–0.09 | ≤ 0.2, r₀ ≥ 3 correlation lengths; catches offset copies the z-test misses |
| Harmonic ratio | mean over 8 harmonics of 1/P of peak power / local median | tile 4.1–4.8; corner tiles 1.9–2.3; others 1.05–1.25; null ≤ 1.13 | ≤ 1.5; G-1's harmonic sum ≤ 9 stays for the masks |
| Fisher's g | max periodogram ordinate / sum over m frequencies, `P(g > x) ≈ m(1 − x)^(m−1)` [C Fisher 1929] | — | `g* ≈ ln(m/α)/(m − 1)` = 0.0113 at m = 1024, α = 0.01; whitened single profiles only |

- The null σ of a correlation scales as `√(A_corr/A_window)` [C]. Calibrate on untiled draws, as
  G-1 does.
- Test review renders at a scale that fits at least 4 periods [I].
- I found no published threshold for perceived repetition.

## 5. Implementation notes (numpy, float32, one 2048² region per call; tested)

- **UE5:** helpers in a `.ush` named in the Custom node's *Include File Paths*. A Texture Object
  input `Tex` samples as `Tex.SampleGrad(TexSampler, …)`. Custom nodes block constant folding [C].
- **Godot 4:** `textureGrad`, `dFdx`/`dFdy` (fragment only), `fwidth`, `uint` with `^ << >>` and
  const arrays exist; matrices are column-major [C].
- **Hash unit test:** `pcg2d` ids (0, 0) and (1, 0) give x = 1055784853 and 1881446135 [M].

| Method | UE5 (`.ush` or Material Function) | Godot 4 |
|---|---|---|
| hex-tiling | the HLSL below; `Tex.SampleGrad(TexSampler, P[i], mul(R[i], ddx(st)), mul(R[i], ddy(st)))` | the same with `uvec2`, `fract`, `mix`, `textureGrad`; `mul(R, p)` → `vec2(cs*p.x + sn*p.y, -sn*p.x + cs*p.y)`; no green flip (OpenGL normals) [C] |
| histogram-preserving | `T` raw; the LUT as a 128 × L R16; 3 `SampleGrad`, the soft clip, `SampleLevel(LUT, (G, L))` per channel [C Unity] | the same; LOD from `dFdx`/`dFdy` |
| bombing, corner tiles | the loop unrolled 4n times with rotated derivatives; a 16-entry `where` constant and atlas-scaled derivatives | the same; a `const ivec2[16]` |
| per-panel offset | panel id → `pcg2d`; swap and negate the derivatives and the normal's `d` like the uv | the same |
| reveal | `hw = max(min(min(w*.5, a), 1-a), fwidth(h)); m = smoothstep(1-a-hw, 1-a+hw, h);` re-equalised mips as DDS with *LeaveExistingMips* [I] | the same; check the DDS mips on import [I] |
| B-spline mask, SDF edge | 4 bilinear fetches of an R16F coefficient map [C Sigg & Hadwiger]; `smoothstep(.5-w, .5+w, enc + k*(h-.5))` | the same |
| scatter, decal chains | offline lists → DBuffer decal actors (rotated by `angle` about the wall normal) or PCG; spline mesh decals | `Decal` nodes, atlas region from `variant` |

```hlsl
uint2 pcg2d(uint2 v) { v = v * 1664525u + 1013904223u; v.x += v.y * 1664525u; v.y += v.x * 1664525u;
    v ^= v >> 16u; v.x += v.y * 1664525u; v.y += v.x * 1664525u; v ^= v >> 16u; return v; }
float u01(uint h) { return float(h >> 8u) * (1.0 / 16777216.0); }
void HexSetup(float2 st, float rotStrength, out float2 P[3], out float2x2 R[3], out float3 w) {
    float2 sk = float2(st.x - 0.57735027 * st.y, 1.15470054 * st.y) * 3.46410162;
    int2 b = int2(floor(sk)); float2 f = frac(sk);
    float z = 1.0 - f.x - f.y, s = step(z, 0.0), s2 = 2.0 * s - 1.0; int k = int(s);
    w = float3(-z * s2, s - f.y * s2, s - f.x * s2);
    int2 v[3] = { b + int2(k, k), b + int2(k, 1 - k), b + int2(1 - k, k) };
    [unroll] for (int i = 0; i < 3; i++) {
        uint2 h = pcg2d(uint2(v[i] + 32768));
        float2 c = float2(v[i].x + 0.5 * v[i].y, 0.8660254 * v[i].y) / 3.46410162;
        float a = (2.0 * u01(h.x) - 1.0) * 3.14159265 * rotStrength, cs = cos(a), sn = sin(a);
        R[i] = float2x2(cs, sn, -sn, cs);                                   // rows: st frame -> sample frame
        P[i] = mul(R[i], st - c) + c + float2(u01(h.y), u01(h.x ^ h.y)); } }
// per map: c_i = Tex.SampleGrad(TexSampler, P[i], mul(R[i], ddx(st)), mul(R[i], ddy(st)));
// W = lerp(1, metric, 0.6) * pow(w, 7); W /= dot(W, 1); gain via lerp(lo, hi, step(0.5, W)), no vector ?:
// normals: d_i = -n_i.xy / n_i.z (UE green is DirectX: flip d.y); d = sum(W_i * mul(transpose(R[i]), d_i))
```

```python
# -- shared helpers ----------------------------------------------------------------------------------
import numpy as np
from statistics import NormalDist
F, U = np.float32, np.uint32

def pcg2d(i, j):   # Jarzynski & Olano; uint32 wraps like the GPU; ids offset to stay >= 0
    M, A = U(1664525), U(1013904223)
    x = (np.asarray(i, np.int64) + 32768).astype(U) * M + A; y = (np.asarray(j, np.int64) + 32768).astype(U) * M + A
    x = x + y * M; y = y + x * M; x ^= x >> U(16); y ^= y >> U(16)   # not +=: ids may broadcast
    x = x + y * M; y = y + x * M; x ^= x >> U(16); y ^= y >> U(16)
    return x, y

def u01(h): return (h >> U(8)).astype(F) * F(2.0 ** -24)       # shader: float(h >> 8u) / 16777216.0

def bilerp(t, x, y):   # GPU-style bilinear lookup of a tileable map t (h, w[, c]) at texel coords; wraps
    h, w = t.shape[:2]; x, y = x - F(0.5), y - F(0.5); x0, y0 = np.floor(x), np.floor(y)
    fx, fy = (x - x0).astype(F), (y - y0).astype(F)
    if t.ndim == 3: fx, fy = fx[..., None], fy[..., None]
    x0, y0 = x0.astype(np.int64) % w, y0.astype(np.int64) % h; x1, y1 = (x0 + 1) % w, (y0 + 1) % h
    return (t[y0, x0] * (1 - fx) + t[y0, x1] * fx) * (1 - fy) + (t[y1, x0] * (1 - fx) + t[y1, x1] * fx) * fy

def smoothstep(e0, e1, x): t = np.clip((x - e0) / np.maximum(e1 - e0, F(1e-6)), 0, 1); return t * t * (3 - 2 * t)
def grid(shape): y, x = np.mgrid[0:shape[0], 0:shape[1]].astype(F); return x + F(0.5), y + F(0.5)

# -- 1 hex-tiling (Mikkelsen 2022) -------------------------------------------------------------------
def tri_grid(u, v):   # u, v in tile units -> 3 barycentric weights, 3 integer vertex ids
    s = F(2 * np.sqrt(3)); x, y = u * s, v * s; sx, sy = x - F(0.57735027) * y, F(1.15470054) * y
    bx, by = np.floor(sx), np.floor(sy); fx, fy = sx - bx, sy - by
    z = 1 - fx - fy; up = (z <= 0).astype(F); s2 = 2 * up - 1
    bx, by, k = bx.astype(np.int64), by.astype(np.int64), up.astype(np.int64)
    return (-z * s2, up - fy * s2, up - fx * s2), ((bx + k, by + k), (bx + k, by + 1 - k), (bx + 1 - k, by + k))

def hex_tile(t, shape, tile_px, rot=1.0, r=0.75, gamma=7.0, beta=0.6, seed=0):
    th, tw = t.shape[:2]; x, y = grid(shape); u, v = x / F(tile_px), y / F(tile_px)
    w, verts = tri_grid(u, v); S, W = [], []
    for (vx, vy), wk in zip(verts, w):
        hx, hy = pcg2d(vx + 7919 * seed, vy)
        cx, cy = ((vx + 0.5 * vy) / (2 * np.sqrt(3))).astype(F), (vy * 0.25).astype(F)        # hex centre
        a = (2 * u01(hx) - 1) * F(np.pi * rot); c, s = np.cos(a), np.sin(a)
        su = c * (u - cx) + s * (v - cy) + cx + u01(hy); sv = -s * (u - cx) + c * (v - cy) + cy + u01(hx ^ hy)
        S.append(bilerp(t, su * tw, sv * th))
        lum = S[-1] if t.ndim == 2 else S[-1] @ np.array([.299, .587, .114], F)       # or the layer height
        W.append((1 - beta + beta * lum) * wk ** gamma)
    W = np.stack(W); W /= W.sum(0)
    if r != 0.5:                                                       # Perlin-Hoffert gain on the weights
        k = float(np.log(1 - r) / np.log(0.5)); W = np.where(W < 0.5, 0.5 * (2 * W) ** k, 1 - 0.5 * (2 - 2 * W) ** k)
        W /= W.sum(0)
    return sum((Wk[..., None] if t.ndim == 3 else Wk) * Sk for Wk, Sk in zip(W, S))

# -- 1 histogram-preserving blend (Burley variant of HN / DH) ----------------------------------------
def gauss_lut(t, sigma=1 / 6, n=4096):   # one channel -> truncated-Gaussian T + inverse LUT (colour: per PCA or Y)
    nd = NormalDist(); lo = nd.cdf(-0.5 / sigma); q = np.linspace(0.5 / n, 1 - 0.5 / n, n)
    rank = np.empty(t.size, F); rank[np.argsort(t, axis=None)] = (np.arange(t.size) + F(0.5)) / t.size
    T = (0.5 + sigma * np.interp(rank, q, [nd.inv_cdf(lo + p * (1 - 2 * lo)) for p in q])).astype(F).reshape(t.shape)
    p = (np.array([nd.cdf((g - 0.5) / sigma) for g in q]) - lo) / (1 - 2 * lo)
    return T, np.quantile(t, np.clip(p, 0, 1)).astype(F)          # inv[k] = value at Gaussian level (k+.5)/n

def soft_clip(x, W):   # Burley's S*: (x - .5)/W + .5 on the middle half of the output, quadratic ends
    lo = np.minimum(x, 1 - x); t = lo / (2 - W)
    near = 8 * (1 / W - 1) * t * t + (3 - 2 / W) * t                   # W > 2/3: passes (0, 0)
    far = np.where(lo >= 0.5 - 0.75 * W, (lo - 0.5 + 0.75 * W) ** 2 / W ** 2, 0)
    y = np.where(lo >= 0.5 - 0.25 * W, (lo - 0.5) / W + 0.5, np.where(W > 2 / 3, near, far))
    return np.where(x <= 0.5, y, 1 - y)

def hpb_tile(T, inv, shape, tile_px, gamma=4.0, seed=0):
    th, tw = T.shape[:2]; x, y = grid(shape); u, v = x / F(tile_px), y / F(tile_px)
    w, verts = tri_grid(u, v); w = np.stack(w) ** F(gamma); w /= w.sum(0)
    G = sum(wk * bilerp(T, (u + u01(hx)) * tw, (v + u01(hy)) * th)
            for wk, (hx, hy) in zip(w, (pcg2d(vx + 7919 * seed, vy) for vx, vy in verts)))
    G = soft_clip(G, np.sqrt((w * w).sum(0)))                         # S* includes the 1/W expansion
    return np.interp(G * inv.size - 0.5, np.arange(inv.size), inv).astype(F)

# -- 1 texture bombing (GPU Gems ch. 20) -------------------------------------------------------------
def bomb(stamp, shape, cell_px, density=1.0, n=2, seed=0):   # stamp: (s, s) alpha, s <= 0.7 cell_px
    x, y = grid(shape); s = stamp.shape[0]; pad = np.pad(stamp, 1)
    cx, cy = np.floor(x / cell_px - 0.5).astype(np.int64), np.floor(y / cell_px - 0.5).astype(np.int64)
    out, best = np.zeros(shape, F), np.full(shape, -1, F)
    for dy, dx, k in [(a, b, c) for a in (0, 1) for b in (0, 1) for c in range(n)]:
        h1, h2 = pcg2d((cx + dx) * 8 + k, cy + dy + 7919 * seed); h3, h4 = pcg2d(h1.astype(np.int64), h2.astype(np.int64))
        a, sc, pri = u01(h3) * F(2 * np.pi), F(0.6) + F(0.4) * u01(h4), u01(h3 ^ h4)   # angle, scale, priority
        lx, ly = (x - (cx + dx + u01(h1)) * cell_px) / sc, (y - (cy + dy + u01(h2)) * cell_px) / sc
        rx, ry = np.cos(a) * lx + np.sin(a) * ly + s / 2, -np.sin(a) * lx + np.cos(a) * ly + s / 2
        al = np.where((rx > 0) & (rx < s) & (ry > 0) & (ry < s), bilerp(pad, np.clip(rx, 0, s) + 1, np.clip(ry, 0, s) + 1), 0)
        win = (u01(h1 ^ h4) < density) & (al > 0) & (pri > best)
        out, best = np.where(win, al, out), np.where(win, pri, best)
    return out

# -- 1 corner tiles ----------------------------------------------------------------------------------
def debruijn_4x4():   # 4x4 binary torus, all 16 2x2 windows distinct; tile (r,c): TL B[r,c] TR B[r,c+1] BL B[r+1,c]
    for code in range(1 << 16):
        B = (code >> np.arange(16) & 1).reshape(4, 4)
        win = B + 2 * np.roll(B, -1, 1) + 4 * np.roll(B, -1, 0) + 8 * np.roll(B, (-1, -1), (0, 1))
        if len(set(win.ravel())) == 16: return B, win

def corner_tiles(atlas, win, shape, tile_px, seed=0):   # atlas: 4x4 tiles laid out by debruijn_4x4
    T = atlas.shape[0] // 4; where = np.zeros((16, 2), np.int64)
    for r_, c_ in np.ndindex(4, 4): where[win[r_, c_]] = r_, c_
    x, y = grid(shape); ix, iy = np.floor(x / tile_px).astype(np.int64), np.floor(y / tile_px).astype(np.int64)
    bit = lambda a, b: (pcg2d(a + 7919 * seed, b)[0] >> U(31)).astype(np.int64)
    idx = bit(ix, iy) + 2 * bit(ix + 1, iy) + 4 * bit(ix, iy + 1) + 8 * bit(ix + 1, iy + 1)
    return bilerp(atlas, (where[idx, 1] + x / tile_px - ix) * T, (where[idx, 0] + y / tile_px - iy) * T)

# -- 1 per-cell / per-panel offset -------------------------------------------------------------------
def cell_offset(t, shape, cell_px, tile_px, blend=True, seed=0):   # blend: 4 fetches; else 1 (borders on joints)
    th, tw = t.shape[:2]; x, y = grid(shape); o = F(0.5 if blend else 0)
    gx, gy = x / cell_px - o, y / cell_px - o; ix, iy = np.floor(gx).astype(np.int64), np.floor(gy).astype(np.int64)
    bx, by = smoothstep(0.25, 0.75, gx - np.floor(gx)), smoothstep(0.25, 0.75, gy - np.floor(gy)); acc = 0
    for dy, dx in ((0, 0), (0, 1), (1, 0), (1, 1)) if blend else ((0, 0),):
        hx, hy = pcg2d(ix + dx + 7919 * seed, iy + dy); q = (hx >> U(30)).astype(np.int64)
        u, v = x / tile_px + u01(hx), y / tile_px + u01(hy)
        u, v = np.where(q & 1, v, u), np.where(q & 1, u, v); u = np.where(q & 2, -u, u)   # transpose/mirror
        acc = acc + ((bx if dx else 1 - bx) * (by if dy else 1 - by) if blend else 1) * bilerp(t, u * tw, v * th)
    return acc

# -- 2 height reveal ---------------------------------------------------------------------------------
def equalize(h):   # rank transform to U(0, 1)
    r = np.empty(h.size, F); r[np.argsort(h, axis=None)] = (np.arange(h.size) + F(0.5)) / h.size; return r.reshape(h.shape)

def reveal(a, h_eq, w=0.1):   # coverage-preserving: E[m] = a for h_eq ~ U(0,1); a may be a per-pixel mask
    hw = np.minimum(np.minimum(F(w / 2), a), 1 - a); return smoothstep(1 - a - hw, 1 - a + hw, h_eq)

def bands(amounts, h_eq):   # exclusive layers on one equalised height; layer k covers exactly amounts[k]
    A = np.cumsum(np.stack(amounts), 0); A0 = np.concatenate([np.zeros_like(A[:1]), A[:-1]])
    return [((h_eq >= 1 - A[k]) & (h_eq < 1 - A0[k])).astype(F) for k in range(len(A))]

def eq_mips(h, levels):   # custom mip chain, every level re-equalised
    out = [equalize(h)]
    for _ in range(levels): m = out[-1]; out.append(equalize(m.reshape(m.shape[0] // 2, 2, m.shape[1] // 2, 2).mean((1, 3))))
    return out

# -- 2 mask upsampling and SDF edges -----------------------------------------------------------------
def bspline_coeffs(m):   # Unser prefilter per axis (pole sqrt(3)-2, mirror ends): the B-spline then interpolates m
    z = np.sqrt(3) - 2
    for ax in (0, 1):
        c = np.moveaxis(m.astype(np.float64) * 6, ax, 0).copy(); n = c.shape[0]
        c[0] = np.tensordot(z ** np.arange(min(n, 30)), c[:min(n, 30)], 1)
        for i in range(1, n): c[i] += z * c[i - 1]
        c[-1] = z / (z * z - 1) * (c[-1] + z * c[-2])
        for i in range(n - 2, -1, -1): c[i] = z * (c[i + 1] - c[i])
        m = np.moveaxis(c, 0, ax)
    return m

def bspline_up(c, f):   # cubic B-spline (C2) at f x resolution, separable 4 + 4 gathers
    for ax in (0, 1):
        n = c.shape[ax]; p = (np.arange(n * f) + 0.5) / f - 0.5; i0 = np.floor(p).astype(np.int64); t = p - i0
        ws = ((1 - t) ** 3 / 6, (3 * t ** 3 - 6 * t ** 2 + 4) / 6, (-3 * t ** 3 + 3 * t ** 2 + 3 * t + 1) / 6, t ** 3 / 6)
        sh = [1, 1]; sh[ax] = -1
        c = sum(np.take(c, np.clip(i0 + k - 1, 0, n - 1), ax) * wk.reshape(sh) for k, wk in enumerate(ws))
    return c.astype(F)

def sdf_encode(sd_lo, spread_px):   # signed distance (px, < 0 inside) at mask res -> 8-bit friendly, 0.5 = edge
    return np.clip(0.5 - sd_lo / (2 * spread_px), 0, 1).astype(F)

# -- 3 scatter from a mask (offline) -----------------------------------------------------------------
def lam_for_cover(m, mean_area): return -np.log(np.clip(1 - m, 1e-6, 1)) / mean_area   # Boolean model

def poisson_points(lam, rng):   # inhomogeneous Poisson, lam in points per px
    n = rng.poisson(lam); yy, xx = np.nonzero(n); k = n[yy, xx]
    return np.repeat(xx, k) + rng.random(k.sum()), np.repeat(yy, k) + rng.random(k.sum())

def thomas(lam, mu, sigma, rng):   # parents lam/mu; Poisson(mu) children at N(0, sigma) offsets
    px, py = poisson_points(lam / mu, rng); k = rng.poisson(mu, px.size)
    return np.repeat(px, k) + rng.normal(0, sigma, k.sum()), np.repeat(py, k) + rng.normal(0, sigma, k.sum())

def pareto(n, smin, smax, alpha, rng):   # truncated power law, N(>s) ~ s^-alpha
    u = rng.random(n); return (smin ** -alpha - u * (smin ** -alpha - smax ** -alpha)) ** (-1 / alpha)

def poisson_disk(rad, rng, k=30):   # Bridson 2007 with a radius map (px): points keep max(r_p, r_q) apart
    H, W = rad.shape; cs = float(rad.min()) / np.sqrt(2); n = int(np.ceil(rad.max() / cs))
    g = -np.ones((int(H / cs) + 1, int(W / cs) + 1), np.int64); P, R = [], []
    def add(x, y):
        g[int(y / cs), int(x / cs)] = len(P); P.append((x, y)); R.append(rad[int(y), int(x)]); return len(P) - 1
    def free(x, y):
        gx, gy, r = int(x / cs), int(y / cs), rad[int(y), int(x)]; nb = g[max(0, gy - n):gy + n + 1, max(0, gx - n):gx + n + 1]
        return all((P[j][0] - x) ** 2 + (P[j][1] - y) ** 2 >= max(r, R[j]) ** 2 for j in nb[nb >= 0])
    active = [add(rng.random() * W, rng.random() * H)]
    while active:
        i = active[rng.integers(len(active))]
        for a, u in zip(rng.random(k) * 2 * np.pi, 1 + rng.random(k)):
            x, y = P[i][0] + R[i] * u * np.cos(a), P[i][1] + R[i] * u * np.sin(a)
            if 0 <= x < W and 0 <= y < H and rad[int(y), int(x)] > R[i]:     # into a sparser zone: step by its radius
                r = rad[int(y), int(x)]; x, y = P[i][0] + r * u * np.cos(a), P[i][1] + r * u * np.sin(a)
            if 0 <= x < W and 0 <= y < H and free(x, y): active.append(add(x, y)); break
        else: active.remove(i)
    return np.array(P)

# -- 3 water paths and decal chains ------------------------------------------------------------------
def trace_path(blocked, x0, y0, rng, wander=0.08):   # elevation image, row 0 on top; blocked = ledges
    H, W = blocked.shape; x, y, drift, pts = float(x0), int(y0), 0.0, [(float(x0), int(y0))]
    while y < H - 1:
        if blocked[y + 1, int(x)]:                                    # run along the ledge to the nearest free column
            free = np.flatnonzero(~blocked[y + 1])
            if free.size == 0: break
            xn = float(free[np.argmin(np.abs(free - int(x)))]); pts += [(q, y) for q in np.linspace(x, xn, int(abs(xn - x)) + 2)[1:]]; x = xn
        drift = 0.9 * drift + wander * rng.standard_normal(); x = min(max(x + drift, 0.0), W - 1.0); y += 1; pts.append((x, y))
    return np.array(pts)

def falling_runs(path, min_len=8):   # streak decals go on the falling parts only
    e = np.flatnonzero(np.diff(np.r_[0, (np.diff(path[:, 1]) > 0).astype(int), 0]))
    return [path[s:t + 1] for s, t in zip(e[::2], e[1::2]) if t - s >= min_len]

def decal_chain(run, seg_len, overlap=0.2, w0=24.0, taper=0.6, n_body=3, rng=None):   # variant: 0 head, n_body+1 tail
    rng = rng or np.random.default_rng(0); d = np.r_[0.0, np.cumsum(np.hypot(*np.diff(run, axis=0).T))]
    a = np.arange(0.0, max(d[-1] - seg_len, 0.0) + 1e-6, seg_len * (1 - overlap)); b = np.minimum(a + seg_len, d[-1])
    ax, ay, bx, by = (np.interp(s, d, run[:, i]) for s, i in ((a, 0), (a, 1), (b, 0), (b, 1)))
    var = rng.integers(1, n_body + 1, a.size); var[0] = 0
    if a.size > 1: var[-1] = n_body + 1
    return dict(x=(ax + bx) / 2, y=(ay + by) / 2, angle=np.arctan2(bx - ax, by - ay), length=b - a,
                width=w0 * (1 - taper * (a + b) / (2 * max(d[-1], 1e-6))), variant=var, mirror=rng.random(a.size) < 0.5)

# -- 4 repetition tests ------------------------------------------------------------------------------
def ncc_shift(img, p, axis):
    n = img.shape[axis]; return float(np.corrcoef(np.take(img, np.arange(n - p), axis).ravel(), np.take(img, np.arange(p, n), axis).ravel())[0, 1])

def repeat_z(img, p, n_ctrl=24, seed=0):   # fail if z > 4
    q = np.random.default_rng(seed).uniform(0.6, 1.4, 4 * n_ctrl) * p; q = q[np.abs(q / p - 1) > 0.08][:n_ctrl].astype(int)
    ctrl = [ncc_shift(img, k, ax) for k in q for ax in (0, 1)]
    return (0.5 * (ncc_shift(img, p, 0) + ncc_shift(img, p, 1)) - np.mean(ctrl)) / np.std(ctrl)

def acf_max(img, r0=64):   # blind: max normalised ACF at r0 <= |lag| < half the window
    H, W = img.shape; win = np.outer(np.hanning(H), np.hanning(W))
    ac = lambda a: np.fft.irfft2(np.abs(np.fft.rfft2(a, (2 * H, 2 * W))) ** 2, (2 * H, 2 * W))
    r = ac((img - img.mean()) * win) / np.maximum(ac(win), 1e-9 * H * W); r = np.fft.fftshift(r / r[0, 0])
    yy, xx = np.ogrid[-H:H, -W:W]; return float(r[(np.hypot(yy, xx) >= r0) & (abs(yy) < H // 2) & (abs(xx) < W // 2)].max())
```

## 6. What I could not find or verify

- **Naughty Dog's vertex-blend maths.** The Uncharted 4 and The Last of Us Part II decks are 13 MB
  and 152 MB, over my fetch limit, and a download needs the user's permission.
- **HeightLerp internals.** Epic documents only the pins, so my formula is [I]. Render a gradient
  through the node to check it.
- **Unreadable to my fetcher:** Adobe (403); Quilez (404), so I used a search summary and a credited
  Godot port; Heitz & Neyret's PDF (blocked), so its maths came via Burley and Unity's code;
  Yuksel's PDF (too large).
- **Not published, as far as I found:** GPU timings for hex or histogram blending, and a
  threshold for perceived repetition. The web-search budget ran out late in the session.
- **From memory or earlier notes, not re-fetched:** pcg2d, normal-map handedness, Sigg & Hadwiger,
  Dorsey et al., Cohen et al., msdfgen.
- **My own bugs, caught by these tests and fixed:** Burley's 1/W applied twice (+13–38 % σ), the
  Bridson stall, and two float64 promotions.

## 7. Sources

- Mikkelsen, *Practical Real-Time Hex-Tiling*, JCGT 11(2), 2022: https://jcgt.org/published/0011/03/05/ · https://github.com/mmikk/hextile-demo
- Heitz & Neyret, HPG 2018: https://eheitzresearch.wordpress.com/722-2/ · Deliot & Heitz, GPU Zen 2: https://eheitzresearch.wordpress.com/738-2/
- Unity Labs: https://github.com/UnityLabs/procedural-stochastic-texturing · https://unity.com/blog/technology/procedural-stochastic-texturing-in-unity
- Burley, JCGT 8(4), 2019: https://jcgt.org/published/0008/04/02/ · Jarzynski & Olano, JCGT 9(3), 2020: https://jcgt.org/published/0009/03/02/
- GPU Gems ch. 20, bombing: https://developer.nvidia.com/gpugems/gpugems/part-iii-materials/chapter-20-texture-bombing
- GPU Gems 2 ch. 12, Wei: https://developer.nvidia.com/gpugems/gpugems2/part-ii-shading-lighting-and-shadows/chapter-12-tile-based-texture-mapping
- GPU Gems 2 ch. 20, Sigg & Hadwiger: https://developer.nvidia.com/gpugems/gpugems2/part-iii-high-quality-rendering/chapter-20-fast-third-order-texture-filtering
- Cohen et al. 2003: https://doi.org/10.1145/882262.882265 · Lagae & Dutré 2006: https://doi.org/10.1145/1183287.1183296 · Dorsey et al. 1996: https://doi.org/10.1145/237170.237278
- Quilez: https://iquilezles.org/articles/texturerepetition/ · Godot port (MIT): https://godotshaders.com/shader/seamless-texture-sampler-without-repeating-patterns-tiling/
- Epic forums: https://forums.unrealengine.com/t/new-texturevariation-node-in-4-26-simple-non-tiling-materials/152671 · https://forums.unrealengine.com/t/texture-bombing/65652
- Epic docs (HeightLerp; CheapContrast): https://dev.epicgames.com/documentation/en-us/unreal-engine/texturing-material-functions-in-unreal-engine · https://dev.epicgames.com/documentation/en-us/unreal-engine/image-adjustment-material-functions-in-unreal-engine
- Epic docs (Custom node; PCG): https://dev.epicgames.com/documentation/en-us/unreal-engine/custom-material-expressions-in-unreal-engine · https://dev.epicgames.com/documentation/en-us/unreal-engine/procedural-content-generation-framework-node-reference-in-unreal-engine
- HDRP: https://github.com/Unity-Technologies/Graphics/blob/master/Packages/com.unity.render-pipelines.high-definition/Runtime/Material/LayeredLit/LayeredLitData.hlsl · Uncharted 4 tech art: https://advances.realtimerendering.com/other/2016/naughty_dog/index.html
- Adobe (403): https://helpx.adobe.com/substance-3d-designer/substance-compositing-graphs/nodes-reference-for-substance-compositing-graphs/node-library/filters/blending/height-blend.html · https://helpx.adobe.com/substance-3d-designer/substance-compositing-graphs/nodes-reference-for-substance-compositing-graphs/node-library/noises-and-patterns/patterns/tile-sampler.html
- Castaño: http://the-witness.net/news/2010/09/computing-alpha-mipmaps/ · Green 2007: https://steamcdn-a.akamaihd.net/apps/valve/2007/SIGGRAPH2007_AlphaTestedMagnification.pdf · https://github.com/Chlumsky/msdfgen
- Thévenaz, Blu & Unser 2000: https://bigwww.epfl.ch/thevenaz/interpolation/ · Bridson 2007: https://www.cs.ubc.ca/~rbridson/docs/bridson-siggraph07-poissondisk.pdf
- Yuksel 2015: http://www.cemyuksel.com/research/sampleelimination/ · Peters: https://momentsingraphics.de/BlueNoise.html · Boolean model: https://en.wikipedia.org/wiki/Boolean_model_(probability_theory)
- spatstat: https://www.rdocumentation.org/packages/spatstat/versions/1.63-3/topics/rThomas · Stamp Points: https://www.sidefx.com/docs/houdini/nodes/cop/stamppoint.html · Fisher's g: https://rdrr.io/cran/GeneCycle/man/fisher.g.test.html
- Godot: https://docs.godotengine.org/en/stable/tutorials/shaders/shader_reference/shading_language.html · https://docs.godotengine.org/en/stable/tutorials/shaders/shader_reference/shader_functions.html
- Project: `layering.md`, `weathering-grid-breakup.md`, `r3-clustering.md`, `r4-noise.md`
