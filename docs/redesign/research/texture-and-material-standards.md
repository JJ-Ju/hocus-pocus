# Texture and material standards for UE5 and Godot 4: the non-negotiables we have not enforced

Date: 2026-11-07. Scope: the standards, value ranges and technical conventions that a material and texture
author for Unreal Engine 5 and Godot 4 is expected to follow, and how each is checked, read against what we
already have: `procedural-materials` (SKILL Values, `layering.md`, `concrete.md`), `large-scale-texturing`
(SKILL and references), `procedural-assets/references/surfacing.md`, the research notes `rE-concrete.md`,
`texturing-at-scale.md` and `tiling-and-distribution-algorithms.md`, and the round-I deliverables
(`scripts/weathering/wx_export.py`, `layered_facade.gdshader`, `layered_facade_ue.hlsl`,
`examples/danchi/README.md`). It answers the user's verdict that the texturing "was a big miss": texel density
was in our notes, but nothing enforced it. The same is true of most delivery standards below. Research only:
no code or skill was changed and no Houdini tool was used.

## Conventions

- Tags: **[C]** consensus or a vendor document, **[P]** one practitioner's practice, **[M]** measured data,
  **[I]** my inference or arithmetic. **[n]** is a source in §10. "(snippet)" means I saw the claim only in a
  search summary. "repo" means read in this repository.
- "sRGB" values are 8-bit sRGB-encoded; "linear" is reflectance 0–1. Conversions use the sRGB transfer function
  (sRGB 30 = 0.013, 50 = 0.032, 240 = 0.871 linear), not a 2.2 gamma, which some charts use (30 → 0.009) [I][11].
- The web-search budget shared by all agents ran out about two-thirds of the way through. Later facts come from
  direct reads of known pages; §9 lists what stayed unchecked.

## 0. Summary

1. **The value ranges are mostly covered; delivery is not.** Engine import settings live only in a research
   note (`rE-concrete.md` §2.6), `concrete.md` and a README. Nothing writes or checks them, and the round-I masks
   have none. The engines' defaults are wrong for our data: UE treats a new texture as sRGB "Default" (BC1/BC3);
   Godot re-imports any texture used in 3D as VRAM-compressed DXT1/DXT5 unless High Quality is on [C][13][21].
   Our RGBA masks would land in BC3, where three independent masks share one 5:6:5 colour line per 4×4 block [I][32].
2. **Our masks break block and streaming rules** [M, repo]. `M_hi` is 4,095 × 1,815 px and `M_lo` 2,047 × 907:
   not multiples of 4, which block compression requires, and not powers of two, which UE needs to stream [C][32]
   [P][23]. A 4×4 block is 8 cm of wall at 50 px/m and spans 80 px at the review density [I].
3. **Two live convention bugs** [M, repo]. (a) Godot converts `source_color` colour uniforms, values and
   defaults alike, from sRGB to linear [C][17]. `layered_facade.gdshader` puts the linear `COL` constants under
   that hint, so the film, stain and run colours render about 10× too dark (0.094 → 0.009). (b) The danchi 1.1
   README's Unreal wall recipe never says to flip green on `spray_normal.png` and `concrete_normal.png`. Both are
   OpenGL (Y+) from Copernicus, and UE expects DirectX (Y−) [C][28].
4. **World-position sampling defeats UE's texture streaming.** When the build cannot tie a lookup to a UV
   channel, it assumes UV0 at scale 1 [C][25]. With UV0 in metres, a texture that repeats every T m is
   under-streamed by log2 T mips: about 2 mips for the 3.6 m coat and 6 for an 82 m facade mask [I]. The skill
   tells us to stream the masks.
5. **Value anchors.** The usual "50–243 sRGB" non-metal range (Unity's charts) is exactly the ColorChecker's
   black and white patches (Y 3.1 % and 90 %) [C][5][9][I]. Manufactured blacks go lower: velvet sRGB 35–38
   (snippet) [7], Musou Black 0.006 linear [3]. So 30 sRGB is the floor for paint, rubber and soot, and 50 for
   natural materials. Epic's base-colour list is broadband solar albedo minus 0.04 [I][1][2]. It is fine for
   concrete (0.51), and it should not anchor vegetation.
6. **Mips need settings, not defaults.** Engines box-filter mips on import. A reveal detail needs its own
   re-standardised mips: Godot loads DDS mip chains as they are, and UE has Leave Existing Mips [C][13][22].
   Specular aliasing has engine switches: UE's Composite Texture (NormalRoughnessTo*), and Godot's import-time
   roughness from a normal plus its screen-space roughness limiter [C][13][16][27]. Alpha-tested foliage needs
   coverage-preserving mips [C][33]; Godot 4.8 adds them [C][20].
7. **Validation tools differ.** UE has buffer views (Base Color, Roughness, Metallic, Specular, World Normal),
   Detail Lighting and streaming-accuracy views [C][24][26]. Godot 4.7 has Unshaded, Lighting (which ignores
   custom shaders) and Normal Buffer, with no albedo or roughness check [C][19]. We need our own debug shader and
   an offline texture lint. Substrate: author weathering as one slab with parameter blending (an Epic example
   drops 108 → 28 B/px; the default budget is 80) [C][30].

## 1. PBR values

**Base-colour anchors** (dielectric unless marked):

| Material | Linear | sRGB | Source |
|---|---|---|---|
| Manufactured blacks (velvet, black dye) | 0.017–0.020 | 35–39 | Unity dark-dielectric study (snippet) [7] |
| Super-black paint (Musou Black) | 0.006 | 18 | [3] |
| Charcoal | 0.02 (Filament coal 0.032) | 39 (50) | [1][3][4]; visible albedo "about 0.04" [2] |
| Tyre rubber | 0.023 (Filament rubber 0.036) | 42 (53) | [3][4] |
| Worn asphalt | 0.08 | 80 | [1] |
| Bare soil; mud | 0.13; (0.091, 0.047, 0.031) | 101; (85, 61, 49) | [1]; [4] |
| Brick | (0.262, 0.095, 0.061) | (140, 87, 70) | [3] |
| Vegetation | (0.198, 0.223, 0.076); Epic "green grass" 0.21 | (123, 130, 78) | [4]; [1], broadband (below) |
| Sand | (0.44, 0.386, 0.231) | (177, 167, 132) | [3], the same as Filament's sample [4] |
| Fresh concrete | 0.51 | 189 | [1][3]; covered (procedural-materials SKILL) |
| Fresh snow | 0.81–0.85 | 232–237 | [1][3] |
| Iron, steel (metal) | 0.49–0.58 per channel | 187–200 | [1][3]; Filament iron (192, 189, 186) [4] |
| Zinc, galvanised (metal) | (0.808, 0.844, 0.865) | (232, 237, 239) | [3] |
| Aluminium (metal) | about 0.92 | about 245 | [1][3] |
| Rust | no calibrated value found; metallic 0 ("rust is not a conductor") | — | [4]; §9 |

**Ranges:**

| Rule | Value | Source |
|---|---|---|
| Non-metal, strict | 50–243 sRGB (0.032–0.90): ColorChecker black N2 (sRGB 52, Y 3.1 %) to white N9.5 (243, Y 90 %) | Unity charts [5]; chart [9]; the match is [I] |
| Non-metal, tolerant | 30–240 sRGB (0.013–0.87) | Adobe [12]; covered |
| Non-metal, permissive | 10–240 sRGB | Filament [4] |
| Painted non-metal | below 0.2 too dark, above 0.8 too bright (scale not stated) | Unity [6] |
| Metal | 180–255 (Adobe), 186–255 (Unity), 170–255 (Filament) sRGB | [4][5][12] |
| Dielectric specular | F0 0.04 = Specular 0.5 in UE and Godot; Unity flags non-metal specular outside 40–75 sRGB (F0 0.021–0.070) | [1][4][5] |
| Metallic | 0 or 1; grey only for transitions and hybrids | [1][4][6] |

- **Epic's list is broadband albedo minus 0.04.** Wikipedia's table (worn asphalt 0.12, soil 0.17, grass 0.25,
  sand 0.40, concrete 0.55, sea ice 0.50–0.70) minus 0.04 gives Epic's 0.08, 0.13, 0.21, 0.36, 0.51 and, at
  mid-range, 0.56; the two darkest (0.04) are halved to 0.02 [I][1][2]. Wikipedia's albedo means the whole solar spectrum unless stated [C][2].
  That is harmless for grey materials. For plants, solar albedo includes the bright near infrared, so 0.21 should
  not anchor moss, algae or vine leaves [I]. Filament's vegetation sample has the same luminance, 0.21 [I][4].
  I found no calibrated visible-light leaf albedo (§9).
- **The specular curves differ.** UE uses F0 = 0.08 × Specular [C][38] (not re-read); Godot uses F0 = 0.16 ×
  specular², per a community reproduction of the engine's F0 [P][18]. Both give 0.04 at 0.5. The danchi README
  sets Specular 0.4 in both engines, which gives F0 0.032 in UE and 0.026 in Godot [I, repo]. Epic puts cavity
  into Specular (Cavity × 0.5) [C][1], so a cavity map ports to Godot with a different curve [I].
- **Roughness** is perceptual in both engines, with GGX α = r² [C][16][38]. Unity's smoothness is 1 − r [C][6].
  No measured roughness standard exists; our ranges are artist practice (covered: procedural-materials SKILL
  Values; `rE-concrete.md` §1.6).
- **Calibration of scans.** Epic measured its base colours "using a polarizing filter" [C][1]. Unity's
  photogrammetry workflow shoots a colour checker at every capture for white balance, uses a polariser for
  diffuse albedo, and removes residual light with a de-lighting tool that needs AO, normal and bent-normal maps
  (snippet) [8]. The dark-dielectric study used a spectrophotometer and polarised photos calibrated on an X-Rite
  ColorChecker (snippet) [7]. A practitioner warns that the chart is not fully dielectric under
  cross-polarisation, so luminance needed a second correction (snippet) [P][10].
- **For procedural work** [I]: our reference photos carry no chart, so they give relative values only. Absolute
  albedo comes from anchors (concrete 0.51; paint from its Munsell value, as `rE-concrete.md` does).

**Numbers and checks.** Gate the composite by percentile, not the palette [I]. Per surface class: base colour
p0.5 ≥ 30 sRGB (paint, rubber, soot) or ≥ 50 (stone, concrete, soil, growth); p99.5 ≤ 240 (243 only for fresh
snow or new white paint). Metal-class pixels sit at metallic 0 or 1 except a transition band of at most 2 %, with
base colour ≥ 180 sRGB. Leave Specular at 0.5 in both engines. Our `COL` table passes the 30 floor; `bio`,
`rust_bar` and `stains_crust` sit at 47–48 in blue, under 50 [M, repo].

## 2. Texture encoding

| Map | On disk (ours) | Unreal 5 | Godot 4 | Note |
|---|---|---|---|---|
| Base colour, tint, ramps | 8-bit sRGB PNG | Default → BC7 (BC1 lean), sRGB on | `source_color`; VRAM + High Quality (BC7) | ramps: uncompressed, no mips, clamp [I] |
| Normal | 16-bit raw, OpenGL Y+ | Normalmap (BC5), sRGB off, **Flip Green Channel** | `hint_normal` → RGTC (RG only); no invert | Z is rebuilt in both [C][13][16] |
| ORM (R AO, G rough, B metal) | 8-bit raw | Masks (BC1/BC3) or BC7, sRGB off | no hint; Roughness Mode G + Src Normal | covered: `layering.md` |
| Height | 16-bit raw mono, range in meta | Grayscale (uncompressed G8/G16), or Alpha (BC4) for Nanite displacement | Lossless | [C][21] |
| Masks `M_hi`, `M_lo`, stage | 8-bit raw RGBA, R | BC7, sRGB off; Grayscale or Alpha for one channel | no hint; VRAM + High Quality, or RG pairs (RGTC) | never BC1/BC3 [I] |
| Reveal details (Gaussian, `0.5 + g/8`) | 8-bit raw mono | Grayscale (G8), Leave Existing Mips | DDS with its own mips, or Lossless | about 1.3 MB each [I] |

- **Block compression.** "A block-compressed texture must be created as a multiple of size 4 in all
  dimensions" [C][32]. BC1 stores two 5:6:5 endpoints and two interpolated colours, so a block's four colours
  lie on one line through RGB [C][32]. Three independent masks in R, G and B therefore bleed into each other and
  get about four levels per block [I]. BC3 is BC1's colour plus an 8-level alpha block. BC4 and BC5 have 8-bit
  endpoints and 8 levels per channel. BC7 has 4–7 bits per channel, optional alpha and 8 modes, at the same
  1 B/px as BC3 [C][21][32].
- **UE defaults** [C][21]. Default and Masks are BC1/BC3 ("Masks ... same compression as Default"; Masks only
  drops sRGB). Grayscale is uncompressed G8 ("if SRGB is set, becomes uncompressed RGBA8; prefer BC4"). Alpha is
  BC4 and is the format "for Nanite displacement". BC7 is "high quality ... same size as BC3". UE also
  auto-detects normal maps and resets their sRGB, compression and LOD group [C][28].
- **Godot defaults** [C][13]. A texture used in 3D is re-imported as VRAM Compressed with mipmaps (Detect 3D).
  Without High Quality, desktop gets DXT1 for opaque and DXT5 for transparent textures; with it, BC7/BC6H (ASTC on
  mobile). High Quality is always off in the Compatibility renderer. Normal maps get RGTC with red and green
  only, and the built-in path "always ignore[s] Z" [C][16]. The "Optimized" channel pack allows RG formats.
  "Fix Alpha Border" is recommended on and "blends edge pixels to reduce darkened outlines" [C][13]. On an RGBA
  data mask whose A is mostly zero (our `M_hi.A`, light layers) I expect it to alter R, G and B near the
  non-zero A, so turn it off for data [I].
- **Colour or data is decided by the hint in Godot.** `source_color` decodes sRGB and is required in Forward+
  and Mobile; no hint means raw [C][14]. For colour *uniforms*, Godot also converts the value and the shader
  default from sRGB to linear [C][17] (§5).
- **Normal-map Y.** UE is DirectX (Y−) [C][28]. Godot requires "X+, Y+ and Z+ ... OpenGL style" [C][15].
  Copernicus is OpenGL (covered: `concrete.md`, `surfacing.md`). The fixes are UE's Flip Green Channel (Interchange
  `flip_normal_map_green_channel`) [C][28] and Godot's Normal Map Invert Y for DirectX maps [C][13]. A wrong Y
  flips only the slope along V. On a wall lit from above, every lip, groove and chip edge reads lit from below
  (bumps read as dents), while vertical features look right, so it survives a casual look [I].
- **Normal frames.** Godot applies `NORMAL_MAP` in the mesh's MikkTSpace frame [C][16]. A normal sampled in
  another space (planar, triplanar, facade) needs a frame built from that projection, or Mikkelsen's
  surface-gradient framework [C][35].
- **Bit depth.** Author heights and normals at 16 bits (covered); BC5's 8-bit endpoints set the shipped
  precision [C][32]. For masks, 8 bits are enough [I]. One level moves edge-rule coverage by 0.4 %. In the faint
  tail, where `pk` is floored at 0.05, one level moves spot coverage by 8 % at 5 % opacity, about 0.4 % in the
  mean. So the "16-bit texture" in `tiling-and-blending.md` is stricter than needed; block compression is the
  real risk.

**Numbers and checks.** Every texture: width and height multiples of 4, and powers of two wherever UE may stream
it. sRGB only on base colour, tint and ramps. The format per class follows the table. After a real BC7 round
trip, the decoded masks pass T3 (mean within 1 ± 0.03, 5th–95th percentile 0.85–1.15). The 95th percentile of
the per-block mean error should be ≤ 1 level (0.4 %) [I]. A ridge test tile lit from +V shows its upper face lit
in both engines [I].

## 3. Mipmapping and filtering

- **Generation.** Mips add about 33 % memory [C][13]. UE's group default is a 2×2 average; Sharpen0–10 use an
  8×8 filter with sharpening; No Mipmaps and Leave Existing Mips also exist [C][22]. Godot generates mips on
  import; "Mipmaps > Limit is currently not implemented"; DDS mipmaps "will be loaded directly" [C][13].
  Sharpening changes means and histograms, so never use it on masks, reveal details or normals [I].
- **Reveal details** need re-standardised mips (covered: `tiling-and-blending.md`; a 10 % layer otherwise shows
  2 % by mip 2). The engines' box filters undo this. Ship a DDS with our own chain (Godot loads it as is; UE has
  Leave Existing Mips, but its DDS import of a mip chain is unchecked). Or re-standardise in the shader from
  per-mip mean and std uniforms indexed by `textureQueryLod` or `CalculateLevelOfDetail` [I].
- **Specular aliasing.** A mip's averaged normal is shorter than 1, and that lost variance must become roughness
  (Toksvig; LEAN and CLEAN carry it further) [C][34]. Engine switches:
  - UE: the roughness texture's Composite Texture, mode NormalRoughnessToRed/Green/Blue/Alpha. The compositing
    texture "needs to be a normal map with the same or larger size" [C][27]. It adds the detail the normal loses
    in each mip to that mip's roughness (snippet) [27]. A material flag, Normal Curvature To Roughness, also
    exists; its behaviour is unchecked [C][27].
  - Godot: import-time Roughness Mode plus Src Normal, "to help decrease specular aliasing slightly" [C][13];
    in custom shaders, `hint_roughness_r/g/b/a/normal/gray` [C][14]. A screen-space roughness limiter adds
    `amount × (|dn/du|² + |dn/dv|²)` to roughness², capped by `limit`, after Tokuyoshi and Kaplanyan [C][16].
  - Risk for us [I]: the coat at 0.75–0.9 roughness barely aliases. Painted steel (0.3–0.55) and damp films
    (−0.25) are where it shows.
- **Mip bias.** In Godot, TAA adds −0.5, FXAA −0.25 and both −0.75; a 3D scale below 1 adds log2(scale); the
  Compatibility renderer always uses 0 [C][19]. A negative bias raises the density a surface needs [I]. UE's
  TSR bias is unchecked.
- **Alpha-tested mips** (vines, leaves, grilles). Plain mips change the share of texels that pass the test, so
  foliage thins with distance. Castaño rescales alpha per mip to keep the coverage [C][33]. Unity exposes
  `mipMapsPreserveCoverage`, off by default [C][33]. UE has alpha-coverage thresholds; a bug in them was fixed in
  2022 (UE-102673), and a forum gives 0.333 as the default threshold (snippet) [33]. Godot 4.8 dev 5 keeps alpha
  data in scaled-down mips (GH-104289) [C][20]. Godot's alpha antialiasing (alpha to coverage) needs MSAA ≥ 2×
  and an edge value "strictly below the alpha scissor threshold" [C][15].
- **Streaming pools.** When UE's pool is short, it drops one mip at a time, keeping on-screen textures first
  [C][24]. Non-power-of-two textures never stream (forum, snippet) [P][23]. Godot 4.7 has no texture streaming.
  Godot 4.8 (beta 1 on 15 October 2026) adds experimental mip-level streaming through a "Texture2D Streamed"
  import type with per-texture minimum and maximum resolution [C][20].

**Numbers and checks.** A 10 % threshold on each reveal detail covers 10 ± 1 % at mips 0–4 in the engine [I].
Alpha-test coverage per mip stays within ± 5 % of mip 0 [I]. A lit 30 m view's specular energy (high-passed lit
luminance) stays within 10 % of a supersampled reference [I]. Godot reviews state the TAA and FXAA mip bias in
use.

## 4. Tiling detail and texel density

Already covered: the densities (1,024 px/m first person, 512 third person, 256 background), detail maps tiling
4–10× and mean-neutral, macro variation at incommensurate scales, hex tiling at 3 fetches per map, and no hex
tiling for structured content (`large-scale-texturing`, `layering.md`, `tiling-and-blending.md`). What is new:

- **Authored density is not delivered density** [I]. The engine shows `authored × 2^−offset`, where the mip
  offset comes from streaming, mip bias and isotropic filtering at grazing angles. Our T1 checks only the
  authored side.
- **UE's streamer and projected lookups.** The streaming build relates each texture lookup to a UV channel and a
  scale. If it cannot, because "the sampling could be based on world position", "the engine will assume a
  dependency on UV Channel 0 and a Scale of 1" [C][25]. Danchi 1.1's UV0 is in metres [M, repo]. A texture that
  repeats every T m is then under-streamed by log2 T mips: 1.85 for today's 3.6 m coat, 1 for the planned 2.0 m
  coat, 6.4 for an 82 m facade mask. The 0.6 m micro tile is over-streamed by 0.74 [I]. Today's masks are NPOT,
  so they never stream and stay resident [P][23]. Padding them to powers of two without fixing this would make
  them stream, at the wrong mip [I].
- **Grazing angles.** Looking along a 60 m facade, the footprint is anisotropic. `layered_facade.gdshader` filters
  the coat albedo and normal anisotropically, but the detail fields and masks with plain
  `filter_linear_mipmap`. So the reveal details reach coarse mips first, and edges soften and drift [I, repo].
- **Cost.** Hex tiling triples the fetches per map: the coat's albedo, normal, ORM and height make 12. Samplers,
  not fetches, are the hard limit (§7) [I].

**Numbers and checks.** In UE, the Material Texture Scale Accuracy and Required Texture Resolution views (red: 2
or more mips missing; yellow: 1) read white on walls at the review cameras [C][24][25]. In Godot, a mip-colour
test texture (each mip a flat, distinct colour) on the wall at 2, 10 and 30 m shows the expected mip,
log2(texels per pixel) [I]. T1 stays the authored check.

## 5. Colour management

- **Working space.** UE renders in linear sRGB/Rec.709 by default; since 5.1 a Working Color Space setting can
  change that, and textures then carry Source Color Settings (snippet) [C][29]. Godot "renders in linear color space", and
  sRGB data needs `source_color` [C][14].
- **Storage.** Base colour is 8-bit sRGB-encoded linear reflectance. Everything else is raw (covered:
  procedural-materials SKILL Write and Traps).
- **Display transforms are not part of the asset.** The tonemapper, exposure and grading apply after lighting.
  A texture tuned to look right through one engine's tonemapper is off in the other [I]. Judge albedo unlit: UE's
  Base Color buffer view [C][26]; in Godot, Unshaded with the Environment tonemap set to Linear and exposure 1,
  or the Internal Buffer view ("linear color, before tonemapping") [C][19][I]. Our `lit_preview.py` images are
  display-referred and must never be used to tune the `COL` constants [I].
- **No baked light.** AO stays in ORM.R (covered). Scans are de-lit and cross-polarised (§1).
- **The Godot constant bug** [M, repo]. `layered_facade.gdshader` declares `k_film`, `k_stain`, `k_run` and
  `k_light` as `source_color` and fills them with values from `weather_fields.COL`, which its own comment calls
  "layer colours, linear RGB". Godot converts them [C][17]. `k_film` 0.094 becomes 0.0091 linear (sRGB 24, under
  the 30 floor), and the film's colour falls from tint × (1.04, 0.84, 0.58) to tint × (0.10, 0.07, 0.05) [I].
  `wall_colour` (0.85, 0.84, 0.80) becomes 0.69 linear, close to `old_paint` 0.70, so that one looks
  intentionally sRGB [I]. UE material vector parameters are linear, so the two shaders disagree [I]. T8 parity
  would catch it, but neither shader has run in an engine.

**Numbers and checks.** Every colour constant in the shader contract carries its encoding. Generated shaders
declare sRGB values with `source_color` and linear values without it [I]. The unlit base-colour views pass the §1
percentiles.

## 6. Validation

- **UE** [C][26]. Buffer Visualization shows Base Color, Roughness, Metallic, Specular, World Normal, Material
  AO, and Diffuse Color (base colour × AO). Detail Lighting applies a neutral material with the normal maps, to
  show whether base colour is too dark or noisy. Lighting Only, Reflections and Shader Complexity also exist.
  The streaming-accuracy views are in §4. I found no built-in albedo range check.
- **Godot 4.7** [C][19]. Unshaded, Lighting ("custom shaders are ignored"), Normal Buffer (Forward+ only),
  Internal Buffer, cluster and atlas views. There is no albedo, roughness or metal check, so our layered shader
  needs a debug variant.
- **Unity, for reference** [C][5]. The Material Validator flags albedo outside 50–243 (non-metal) or 186–255
  (metal), in red below and blue above. It flags specular outside 40–75 (non-metal) or 155–255 (metal).
- **Substance** [C][11]. PBR Validate has an albedo dark-range threshold and a metal reflectance range, shown on a
  red-to-green overlay. Adobe's page gives no defaults. A third-party filter uses 30 or 50 to 240, and 155–255
  for metal (snippet).
- **Pipelines validate too.** UEFN rejects textures without mips in some texture groups (snippet) [36]. I found
  no published studio checklist before the search budget ran out.

**Numbers and checks:** a texture lint for our exports [I]:
1. Size: multiple of 4; power of two if it may stream; ≤ 4,096 px for Godot Mobile and web [C][13].
2. Encoding by class (§2), compared against the engine's import files (UE: CompressionSettings, SRGB,
   MipGenSettings, NeverStream; Godot `.import`: compress mode, high_quality, mipmaps, roughness, fix alpha
   border, normal_map_invert_y).
3. Albedo percentiles and metallic binarity per class (§1).
4. Normals: decoded |xy| ≤ 1 and z ≥ 0.2; mean xy of a tiling detail within ± 0.01; a Y-convention tag present.
5. Roughness: p1 ≥ 0.05, and a within-material std ≥ 0.02 (our "flat roughness reads fake" rule).
6. Detail maps: overlay albedo mean 0.5 ± 0.01; each reveal detail's mean and std per mip as declared.
7. Compression round trip per class (§2), with T3 after decoding.

## 7. UE5 Substrate and Godot 4 limits

- **Substrate** [C][30]. It is on by default for new projects; projects upgraded to 5.7 or later stay on the
  legacy path unless they opt in. "Platform support and testing is currently incomplete", and Material Layers
  under Substrate are experimental. The budget is `r.Substrate.BytesPerPixel` = 80. The Blendable GBuffer allows
  one closure per pixel; the Adaptive GBuffer allows more, at a runtime cost and about 15 % longer cooks. Each
  extra BSDF roughly adds a lighting evaluation. "Use Parameter Blending" merges slabs into one (an example drops
  108 → 28 B/px), and the compiler merges slabs itself when over budget. DBuffer decals work in both modes; the
  Adaptive GBuffer supports only DBuffer.
- **For our facade** [I]: weathering is horizontal mixing on one surface. Compute it into one slab, as our HLSL
  contract does (one base colour, roughness and normal). Keep Vertical Layer for wet films and clear coats.
- **UE samplers.** D3D11-class materials get 16 sampler slots; "Shared: Wrap" samplers do not consume one
  [C][31], which a forum puts at up to 128 textures (snippet) [31]. Our Custom-node functions take a SamplerState
  per texture, so pass a shared one [I].
- **Godot** [C][13][14][15]. There is no material layering system. StandardMaterial3D has one masked detail
  layer; everything else is one spatial shader. The uniform buffer is 64 KB on desktop and 16 KB on mobile, with
  at most 16 instance uniforms. Compatibility cannot index a texture array with an instance uniform, and it has
  no BPTC. Decal nodes take albedo, normal, ORM and emission, with no height and no custom shader (covered:
  `texturing-at-scale.md`). The shading page gives no sampler limit. OpenGL ES 3 guarantees only 16 fragment
  units, and the engine uses some; `layered_facade.gdshader` declares 13 samplers [I, repo].

**Numbers and checks.** UE's Substrate panel shows each material's byte count and any merges: pass ≤ 80 B/px with
no merge reported [C][30][I]. Samplers ≤ 16, or shared. Godot: ≤ 13 samplers if Compatibility is a target, and
uniforms ≤ 16 KB if Mobile is [I].

## 8. Recommendations for our skills

Ranked by effect on what ships, then ease. "Covered" names the file that already has it.

| # | Finding | Why it matters for us | Concrete change | Skill file | Sources |
|---|---|---|---|---|---|
| 1 | **Violation:** Godot converts `source_color` uniforms; linear `COL` constants sit under it | film, stain and run colours about 10× too dark in Godot; parity with the mirror broken | linear constants without `source_color`, sRGB ones with it; generate constants from `weather_fields.COL` with an `encoding` field; add a Trap | `large-scale-texturing/scripts/layered_facade.gdshader`; `large-scale-texturing/SKILL.md` (Traps) | [14][17] |
| 2 | **Violation:** masks 4,095 × 1,815 and 2,047 × 907 (gable 745 wide) | no BC compression without padding; UE never streams NPOT | pad by edge extension to 4096 × 2048 and 2048 × 1024; frames stay in `export.json`; lint: W % 4 = H % 4 = 0, power of two unless declared resident | `scripts/weathering/wx_export.py`; `texturing-at-scale.md` (mask table) | [23][32] |
| 3 | Import settings not written or checked (formats covered: `texturing-at-scale.md` Engines, `concrete.md` Engine path) | defaults: UE sRGB BC1/BC3; Godot DXT5 for RGBA masks, probably DXT1 for grey details, Fix Alpha Border on | `wx_export.py` writes an import manifest, Godot `.import` presets and a UE Python import script. Masks BC7 sRGB off (Godot High Quality, or RG pairs on Compatibility); reveal details uncompressed R8; ramps uncompressed, no mips, clamp; Fix Alpha Border off. Check: T3 after a real BC7 round trip; per-block mean error ≤ 1 level | `procedural-materials/SKILL.md` (Write); `large-scale-texturing/SKILL.md` (Engine hookup); `wx_texcheck.py` | [13][21][32] |
| 4 | **Risk:** UE assumes UV0 × 1 for world-projected lookups; the skill says "masks as streamed textures" | under-stream by log2 T: 1.85 mips (3.6 m coat), 6.4 (82 m mask) | write facade coordinates to UV1 at export and sample masks from TexCoord[1]; tiling sets from TexCoord[0] (m) / T; or Never Stream the masks (≤ 40 MB per building). Check: Material Texture Scale Accuracy and Required Texture Resolution white on walls | `large-scale-texturing/SKILL.md` (Engine hookup, Checks); `procedural-assets` (export UV1) | [24][25] |
| 5 | Normal Y flip covered (`concrete.md`, `surfacing.md`, `rE-concrete.md` §2.6). **Violation:** danchi README's UE wall omits Flip Green. **Risk:** Godot facade shader applies a facade-space normal in the mesh frame, not hex-tiled | lit inside-out lips and grooves in UE; 3.6 m period in the lighting; wrong light on mirrored or rotated pieces | README: Flip Green Channel on `spray_normal.png` and `concrete_normal.png`; shader: T = `facade_u`, B = −`facade_v`, write `NORMAL`; hex-tile the normal, rotating XY back per sample; T2 on a lit view. Check: ridge tile lit from +V in both engines | `examples/danchi/README.md`; `layered_facade.gdshader`; `large-scale-texturing/SKILL.md` (Traps) | [13][15][16][28][35] |
| 6 | Re-standardised mips covered as a rule (`tiling-and-blending.md`), with no delivery path | engines box-filter on import, so coverage drifts with distance in engine | DDS with our own mip chain (Godot loads as is; UE Leave Existing Mips), or per-mip mean and std uniforms with `textureQueryLod` / `CalculateLevelOfDetail`. Check: 10 ± 1 % at mips 0–4 | `tiling-and-blending.md` (Mips); `wx_detail.py` | [13][22] |
| 7 | Ranges covered (`procedural-materials/SKILL.md` Values: 30–240, 50 strict, metal 180–255, F0 0.04) | the gate checks colours, not the composite; Epic's grass is broadband; Specular differs between engines | percentile gate per class (§1); 50 = ColorChecker black, 30 floor for manufactured; no Epic value for plants; Specular 0.5 in both engines (README's 0.4 gives 0.032 vs 0.026); no painted Specular or cavity between engines | `procedural-materials/SKILL.md` (Values); `scripts/weathering/weather_gate.py` | [1][2][4][5][9][18] |
| 8 | Specular AA covered in principle (`layering.md`: Toksvig or the engine composite) | painted steel and damp films sparkle at distance | UE: ORM Composite Texture = its normal, mode NormalRoughnessToGreen. Godot: Roughness Mode Green + Src Normal; `hint_roughness_g`; roughness limiter on. Check: 30 m specular energy within 10 % of a supersampled reference | `procedural-materials/references/layering.md` (Scale and distance) | [13][14][16][27][34] |
| 9 | Godot has no PBR validation view; nothing lints our textures | out-of-range values and wrong flags reach the engine unseen | `pbr_validate.gdshader` (red below 30/50 sRGB, blue above 240, yellow grey metal) and a numpy lint (§6) | `large-scale-texturing/scripts/`; `large-scale-texturing/SKILL.md` (Checks) | [5][11][19][26] |
| 10 | Substrate and sampler budgets not stated | layered weathering can exceed 80 B/px or 16 samplers; Godot Compatibility loses BC7 | one slab with parameter blending; Vertical Layer only for wet films; shared samplers in UE; ≤ 13 samplers on Godot Compatibility | `large-scale-texturing/SKILL.md` (Engine hookup); `layering.md` (Engine systems) | [14][30][31] |
| 11 | T1 checks authored density only (covered: `large-scale-texturing/SKILL.md` Checks) | mip offsets from streaming, bias and grazing angles undo it | engine-side density check (UE views; Godot mip-colour texture); state TAA and FXAA bias; anisotropic filtering on reveal details | `large-scale-texturing/SKILL.md` (Checks); `layered_facade.gdshader` | [19][24][25] |
| 12 | Alpha-tested foliage mips not covered | vines and leaves thin out with distance | coverage-preserving mips (Castaño; Godot 4.8 option; UE thresholds); Godot alpha to coverage with MSAA ≥ 2× | `procedural-assets` (the vine class, when built) | [15][20][33] |
| 13 | Colour management mostly covered (AO out of base colour; linear working) | lit, tonemapped previews tempt us to tune albedo | judge base colour unlit (UE Base Color view; Godot Linear tonemap at exposure 1, or Internal Buffer); keep UE's default working space | `procedural-materials/SKILL.md` (Check) | [19][26][29] |
| 14 | Godot 4.8 adds experimental texture streaming | our Godot budget assumes everything resident | when the danchi moves to 4.8, test "Texture2D Streamed" with projected lookups before relying on it | `texturing-at-scale.md` (Engines) | [20] |

## 9. Unchecked

- The Frostbite course notes (2014) [37]: located, too large to read. Karis's UE4 notes (2013) [38]: located,
  text not extractable, so UE's F0 = 0.08 × Specular and α = r² are from memory. Godot's F0 function body: only a
  community reproduction [18].
- Godot: how it compresses textures that are not multiples of 4; which format a single-channel PNG gets under
  "sRGB Friendly" and "Optimized"; how far Fix Alpha Border reaches; the per-material sampler limit; the height
  map convention (white high or low).
- UE: DDS import of an existing mip chain in 5.x; whether NPOT textures get mips (since 5.1, snippet) and stream
  in 5.8; TSR and TAA mip bias; the behaviour of Normal Curvature To Roughness; any minimum roughness clamp.
- Calibrated visible albedo for rust, soil, moss, algae and leaves. A search did not confirm the commonly
  quoted 10–20 % green peak for leaves. Quixel's calibration method was not found.
- Whether UE stores landscape weightmaps uncompressed, a possible precedent for leaving masks uncompressed.
- Substance Painter's PBR Validate defaults; Ben Golus's triplanar-normal article (HTTP 403); any published
  studio texture-validation checklist; the Godot 4.8 stable date (beta 2 as of this note).

## 10. Sources

1. Epic, Physically Based Materials (UE 5.8): https://dev.epicgames.com/documentation/en-us/unreal-engine/physically-based-materials-in-unreal-engine
2. Wikipedia, Albedo: https://en.wikipedia.org/wiki/Albedo
3. Physically Based database, API: https://api.physicallybased.info/materials (site: https://physicallybased.info/)
4. Filament, Crafting physically-based materials: https://google.github.io/filament/notes/material_properties.html · Filament Materials: https://google.github.io/filament/Materials.html
5. Unity, Material Validator (2019.3): https://docs.unity.cn/es/2019.3/Manual/MaterialValidator.html · (6000.4): https://docs.unity3d.com/6000.4/Documentation/Manual/MaterialValidator.html
6. Unity, Believable visuals: materials and shaders: https://docs.unity3d.com/2020.2/Documentation/Manual/BestPracticeMakingBelievableVisuals5.html
7. Unity, Dark Dielectric Materials (snippet; the fetch failed): https://docs-alpha.unity3d.com/cn/2018.1/uploads/ExpertGuides/Dark_Dielectric_Materials.pdf
8. Unity Photogrammetry Workflow, 2017 (snippet): https://images.response.unity3d.com/Web/Unity/%7Be238a943-f1d8-4689-b4ae-ca0df03641fd%7D_Unity-Photogrammetry-Workflow_2017-07_v2.pdf · 80.lv, Unity De-Lighting tool (snippet): https://80.lv/articles/photogrammetry-de-lighting-tool-for-unity
9. Wikipedia, ColorChecker: https://en.wikipedia.org/wiki/ColorChecker
10. Polycount, calibrating cross-polarised captures (snippet): https://polycount.com/discussion/comment/2530520 · https://polycount.com/discussion/comment/2534876/
11. Adobe, PBR Validate (Substance 3D Sampler): https://experienceleague.adobe.com/en/docs/substance-3d-sampler/using/filters/tools/pbr-validate · Polycount, Painter conversion table (snippet): https://polycount.com/discussion/comment/2636369
12. Adobe, The PBR Guide part 2 (cited in the repo): https://www.adobe.com/learn/substance-3d-designer/web/the-pbr-guide-part-2
13. Godot, Importing images: https://docs.godotengine.org/en/stable/tutorials/assets_pipeline/importing_images.html
14. Godot, Shading language: https://docs.godotengine.org/en/stable/tutorials/shaders/shader_reference/shading_language.html
15. Godot, Standard Material 3D: https://docs.godotengine.org/en/stable/tutorials/3d/standard_material_3d.html
16. Godot source, `scene_forward_clustered.glsl` (normal decode, MikkTSpace, roughness limiter): https://github.com/godotengine/godot/blob/master/servers/rendering/renderer_rd/shaders/forward_clustered/scene_forward_clustered.glsl
17. Godot source, `material_storage.cpp` (`source_color` values and defaults converted with `srgb_to_linear`): https://github.com/godotengine/godot/blob/master/servers/rendering/renderer_rd/storage_rd/material_storage.cpp
18. Community gist reproducing Godot's default BRDF, F0 = 0.16 × specular² (snippet): https://gist.github.com/lyuma/8268047e10ebca9436a2cdcd960e0c6f
19. Godot, Viewport class (debug draw, mipmap bias): https://docs.godotengine.org/en/stable/classes/class_viewport.html
20. Godot, Dev snapshot 4.8 dev 5 (10 September 2026): https://godotengine.org/article/dev-snapshot-godot-4-8-dev-5/ · beta timeline (secondary): https://www.warp2search.net/story/godot-48-beta-2-ships-featurefreeze-bugfix-release-now-available/
21. Epic, TextureCompressionSettings (Python API, 5.8): https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/TextureCompressionSettings · UE 4.27, Texture Compression Settings: https://docs.unrealengine.com/4.27/RenderingAndGraphics/Textures/TextureCompressionSettings
22. Epic, TextureMipGenSettings (Python API, 5.8): https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/TextureMipGenSettings
23. Unreal forums, NPOT textures never stream; Power of Two Mode (snippet): https://forums.unrealengine.com/t/cant-untick-never-stream/381980 · NPOT mips from 5.1 (snippet): https://unreal-garden.com/tutorials/ui-texture-size/ · https://forums.unrealengine.com/t/about-non-power-of-two-texture2d/1667354
24. Epic, Texture Streaming Overview: https://dev.epicgames.com/documentation/en-us/unreal-engine/texture-streaming-overview-for-unreal-engine
25. Epic, Building Texture Streaming Data: https://dev.epicgames.com/documentation/en-us/unreal-engine/building-texture-streaming-data-in-unreal-engine
26. Epic, Viewport Modes: https://dev.epicgames.com/documentation/en-us/unreal-engine/viewport-modes-in-unreal-engine
27. Epic, ECompositeTextureMode: https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Runtime/Engine/ECompositeTextureMode · UseNormalCurvatureToRoughness: https://dev.epicgames.com/documentation/unreal-engine/API/Runtime/Engine/FMaterialResource/UseNormalCurvatureToRoughness?application_version=5.5 · forum explanation (snippet): https://forums.unrealengine.com/t/composite-texture-mode-normal-roughness-explained/149549
28. Epic, InterchangeGenericTexturePipeline (`flip_normal_map_green_channel`, `detect_normal_map_texture`): https://dev.epicgames.com/documentation/en-us/unreal-engine/python-api/class/InterchangeGenericTexturePipeline?application_version=5.2 · forum, DirectX and OpenGL tools (snippet): https://forums.unrealengine.com/t/opengl-or-directx-for-normal-maps/1931367
29. Epic, Working Color Space: https://dev.epicgames.com/documentation/unreal-engine/working-color-space-in-unreal-engine
30. Epic, Overview of Substrate Materials (5.8): https://dev.epicgames.com/documentation/en-us/unreal-engine/overview-of-substrate-materials-in-unreal-engine
31. Epic, SamplerSourceMode (snippet): https://api.unrealengine.com/INT/PythonAPI/class/SamplerSourceMode.html · forum, the 16-sampler limit (snippet): https://forums.unrealengine.com/t/texture-samplers-limitation-is-still-present-in-4-9/42958
32. Microsoft, Block Compression (Direct3D 10): https://learn.microsoft.com/en-us/windows/win32/direct3d10/d3d10-graphics-programming-guide-resources-block-compression · Texture Block Compression in Direct3D 11: https://learn.microsoft.com/en-us/windows/win32/direct3d11/texture-block-compression-in-direct3d-11
33. I. Castaño, Computing Alpha Mipmaps: https://ludicon.com/castano/blog/articles/computing-alpha-mipmaps/ · Unity, mipMapsPreserveCoverage: https://docs.unity3d.com/ScriptReference/TextureImporter-mipMapsPreserveCoverage.html · UE-102673: https://issues.unrealengine.com/issue/UE-102673
34. S. Hill, Rock-Solid Shading (Toksvig, LEAN; cited in the repo): https://www.selfshadow.com/talks/rock_solid_shading_v1.pdf
35. M. Mikkelsen, Surface Gradient Based Bump Mapping, JCGT 2020 (cited in the repo): https://jcgt.org/published/0009/03/04/paper.pdf
36. Unreal forums, UEFN texture validation (snippet): https://forums.unrealengine.com/t/textures-with-no-mipmaps-no-longer-validate-as-of-37-10-if-texture-group-is-set-to-normal/2651022
37. S. Lagarde and C. de Rousiers, Moving Frostbite to PBR (2014), not read: https://www.ea.com/frostbite/news/moving-frostbite-to-pb
38. B. Karis, Real Shading in Unreal Engine 4 (2013), not extractable: https://cdn2.unrealengine.com/Resources/files/2013SiggraphPresentationsNotes-26915738.pdf

**Repo:** `scripts/weathering/wx_export.py` (mask sizes, encodings), `weather_fields.py` (`COL`, "linear RGB"),
`.claude/skills/large-scale-texturing/scripts/layered_facade.gdshader` and `layered_facade_ue.hlsl`,
`examples/danchi/README.md` (engine recipes, Specular 0.4), `examples/danchi/src/py/tex_build.py` (Copernicus
normals), and the skills and research notes named in the scope.

## 11. Actions

Statuses as `scripts/research_actions.py` reads them (round J). Numbers are §8's.

| # | Action | Status |
|---|---|---|
| 1 | `source_color` only on sRGB constants in the Godot shader | done (`layered_facade.gdshader`; large-scale-texturing Traps) |
| 1b | Shader constants generated from `weather_fields.COL` with their encoding | parked (revisit at the start of round K, when the golden crop first renders in Godot 4.7 (audit rank 1)) |
| 2 | Masks padded to powers of two; the export fails on bad sides | done (`wx_export.pot_pad`; `size_lint` raises on sides not multiples of 4, not powers of two or over 4,096) |
| 3 | Import settings written per texture class | done (large-scale-texturing SKILL.md import table) |
| 3b | An import manifest, Godot `.import` presets and a UE import script from the export | parked (revisit at the start of round K, when the golden crop first renders in Godot 4.7 (audit rank 1)) |
| 4 | Masks never streamed, or sampled from a facade UV1 | done (large-scale-texturing SKILL.md streaming; the export's UV1 waits for rank 8) |
| 5 | Flip Green in the danchi README | done (`examples/danchi/README.md`) |
| 5b | The Godot shader's tangent basis and hex-tiled normal | parked (audit rank 1c; revisit at the start of round K, when the golden crop first renders in Godot 4.7 (audit rank 1)) |
| 6 | Re-standardised mips delivered to the engines | parked (revisit at the start of round K, when the golden crop first renders in Godot 4.7 (audit rank 1)) |
| 7 | Specular 0.5 in both engines | done (`examples/danchi/README.md`) |
| 7b | Albedo percentiles per class on the composite | parked (the texture lint row in large-scale-texturing Checks; revisit at the next danchi export, with `asset_check` (audit rank 8)) |
| 8 | Specular anti-aliasing | parked (revisit at the start of round K, when the golden crop first renders in Godot 4.7 (audit rank 1)) |
| 9 | `pbr_validate.gdshader` | parked (revisit at the start of round K, when the golden crop first renders in Godot 4.7 (audit rank 1)) |
| 10 | Substrate and sampler budgets | parked (revisit when a UE 5.7+ build exists, audit rank 25) |
| 11 | An engine-side density check | parked (revisit at the start of round K, when the golden crop first renders in Godot 4.7 (audit rank 1)) |
| 12 | Coverage-preserving mips for alpha-tested foliage | parked (no foliage carrier; revisit when vines or trees are built, audit rank 27) |
| 13 | Judge base colour unlit in the engine | parked (revisit at the start of round K, when the golden crop first renders in Godot 4.7 (audit rank 1)) |
| 14 | Godot 4.8 texture streaming | parked (revisit when the danchi moves to Godot 4.8) |
