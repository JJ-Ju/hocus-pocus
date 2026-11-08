# Paint, rust and concrete up close

What coated concrete and painted steel do as they age, at the scale a player sees at arm's length,
with the numbers the danchi gate checks (rules P1-P3, R7-R9, J1b, J3, F5, G7 in
`weathering-rules.md`). Sources: `docs/redesign/research/coatings-concrete-corrosion.md` and
`surface-detail-techniques.md` (round J), which cite the standards and studies.

## Paint on concrete fails as a stack

A Japanese housing block's wall is a multilayer spray-tile finish (吹付タイル: sealer, a 1-3 mm
textured main coat, one or more top coats), repainted every 12-15 years. It fails in order:
the top coat chalks, then cracks and flakes off the coat below (**type a**, ISO 4628-5), then wears
through while the main coat cracks and lifts, and at last the whole system comes off the concrete
(**type b**). So most flakes show an older coat; concrete shows last, where water got behind the
coat.

| | Kept | Typical | Worn | Derelict |
|---|---|---|---|---|
| Years since the last repaint (danchi clock) | 4.7 | 5.8 | 10.3 | 14.6 |
| Flaked share of the wall (ISO 4628-5: 0.1 / 0.3 / 1 / 3 / 15 %) | 0 | ≤ 0.1 % | 0.3-1 % | 3-15 % |
| Type b (to the concrete) share of the flaked area | — | ≤ 25 % | ≤ 25 % | 30-60 % |
| Typical flake size (ISO size classes: ≤ 3 / 10 / 30 mm, > 30 mm) | — | ≤ 10 mm | 3-30 mm | 10 mm and up; sheets of 0.1-0.5 m on tops |

**Where:** where water stays or gets behind the coat: 0-0.3 m below tops (sills, upstands,
parapets), drip lines and slab noses, within 0.15 m of cracks and joints, 0-0.5 m below rails, the
splash zone at the foot (rising damp), soffits, and wherever efflorescence pushes the coat off. At
Worn, at least 65 % of the flaking sits in those zones (P2).

**How it looks:**
- Flakes come out of a crack network in the film: cells of 1-3 mm in a top coat, 4-10 mm in a
  texture coat, with T-junctions. Draw the checked film around the flakes, not everywhere.
- Edges are crisp (a 0.9-0.1 ramp of 1.5 px at most at 1 mm/px) and jagged, never soft blobs.
- The lip: the paint's broken edge shows its clean body (+3-6 L*), the flake's upper edge casts a
  shadow line 1-2 mm wide on the exposed side, and dirt collects under it (gravity). A recipe, with
  `P` the paint coverage at the fine grid and `b_r` a blur of radius r:
  ```
  h_paint = t·P + c·max(P - b_r(P), 0)      # t film thickness; r = 1-3 mm; c = 0.5-1.5 t where it lifts
  dirt   += d0·max(b_r(P) - P, 0)·below      # the dark line under the edge
  edge    = P·(P - b_1mm(P)) > 0             # the broken edge: lighter, the paint's unweathered body
  ```
- What shows: an older coat 2-10 L* lighter, or a hue step away (type a); concrete at L* 55-68 and
  C* 4 or less (type b), carrying the wall's dirt (it has been exposed for years).
- **Lighter than the dirty paint, never than the clean paint.** An older coat carries less of the
  wall's dirt than the concrete (about the 0.3 power of the dirt ratio, against 0.7), and is capped at
  the clean coat's luminance. A flake lighter than clean paint also breaks local-contrast measures:
  their reference (the cleanest patch nearby) moves onto the flakes and the whole wall reads dirtier.
- **Paint is there or gone.** Reveal flakes at full opacity, their coverage the mask's alpha; a
  coverage-preserving reveal that uses the mask's local peak as the opacity draws see-through paint.
  At low amounts cap the share of any mask texel that is flaked (about 0.55 of a 2 cm texel at Worn,
  1.0 from Derelict) and give the flake tile a cell-border term, so partly flaked areas keep paint
  bridges and the flakes stay separate (3-30 mm at Worn) instead of fusing into one hole.

## Concrete under the coat

| Feature | Size | Cover or count | Contrast | Where |
|---|---|---|---|---|
| Voids (bugholes) on a cast face | 1-25 mm, median 2-3 mm, depth 0.3-0.6 × diameter | 0.3-2 % of the face (JCI test panels 1.25-1.82 %); 30-150 per m² from 5 mm, 5-40 from 10 mm | about -40 % inside, rougher | the top 0.3-0.5 m of each pour lift 2× or more |
| Through a spray-tile coat | dimples from 5 mm | 2-20 % of the bare count | shallow, a little dirt | the coat fills voids under 3 mm |
| Aggregate shadows ("aggregate transparency") | 5-25 mm | 2-8 % | ΔL* -1 to -4, the dark ones Δb* -0.5 to -1.5 | glossy formwork (konpane) favours them |
| Sand flecks, dark and cool | 0.3-3 mm | 0.5-2 % on fresh skin, 3-10 % where the skin is washed or worn | ΔL* -10 to -25 | tops, windward corners, the splash zone, lost paint |
| Pebbles (coarse aggregate) | 5-20 mm (Gmax 20-25 mm) | 35-45 % of a broken face | each its own hue, ±10 % value | spall floors, chips, worn arrises |
| Clean concrete colour | — | C* median 4 or less, p10-p90 spread 1.5 or more | cool and warm drift of 1-3° | — |

Grains over about 0.5 mm show only where the cement skin is gone, so a flecked texture belongs to
breaks, worn arrises and lost paint, not to fresh formed faces. Concrete before about 1970 in
Japan used rounded river gravel; crushed sandstone and andesite (angular, dark grey) after.

## Rust on painted steel

It does not come through intact enamel: it starts at a defect (an edge or weld where the film pulled
thin, a chip, a scratch, a joint that holds water) and creeps under the film (0.1-3.5 mm a year),
lifting it. Read from the inside out, a patch of 4 cm or more has:

| Zone | Width | Colour | Roughness, metallic |
|---|---|---|---|
| Core: old, dense rust | the patch | L* 28-36, hue 40-55°, C* 12-20; black magnetite about 25 underneath | 0.85-0.95, 0 |
| Margin: fresh rust | 1-4 mm on the advancing side and along wet paths | L* 48-56, hue 55-70°, C* 28-40 | 0.75-0.85; 0.5-0.7 wet |
| Exposed metal, primer or scale | 0.5-3 mm (the coatings note allows up to 3 cm of paint loss) on 30-70 % of the perimeter | tarnished steel, oxide over metal: L* 38-48, a* 0 to +4, b* +2 to +8 (R7c); flash rust (L* 55-65, b* +20 to +28) only within 1-3 mm of chips under a year old; red-oxide primer L* 36-44; mill scale near-black | metallic 0.3-0.5 (60-80 % oxide), roughness 0.55-0.75 |
| Blister halo | 2-8 mm | the paint, a little yellower | the paint's + 0.05 |
| Dense scale (the sheen) | the oldest, darkest scale: 4-15 % of the rusted steel at the heaviest rust, none below rust 0.5 | unchanged: brown-black, never b* < 0 | F0 0.04 → 0.08 (UE Specular 1.0, Godot `SPECULAR` 0.71), roughness → 0.55, under a mask (R11) |

Bare bright metal lasts only where something keeps rubbing it: the handrail's top in the hand zone
(0.8-1.2 m), arris chips. Shares of the steel: 0.05-0.5 % at Typical, 0.3-2 % at Worn and
Derelict (R7).

**The Ts first.** A railing's rust starts at the underside corners of each T, where a bar meets the
rail above it: drops hang under the rail, the corner holds them (white enamel's contact angle,
70-78°, is over the 45° limit at which a 90° corner drains), and the film at a weld toe is only
50-70 % as thick as on the flat. Then it spreads sideways along the rail's drip line, then up its face; the rail's top
comes last and only advances with heavy wear. Railing "TTTT" rusts as "TrTrTr" (R3's T clause, R10).
The bottom rail collects every bar's water: it rusts from each bar's foot and spreads along the rail
(wetness about 1.8 against the top rail's face at 1), so between steps its rusted stretches lengthen
rather than new spots appearing (R4).

**Runs down the bars.** The T's water runs down each bar and leaves rust stain below every rusted
T: member-wide for 2-5 cm under the joint, then a stripe over 30-80 % of the bar's face with darker
tide lines, ending in a drip or a collar where it pools on the bottom rail. Measure a run as a share
of its bar: median 2-30 % at rust 0.25, 30-75 % at 0.5, 75-100 % at Derelict (rust 0.6: all or almost
all the way down), 85-100 % at 1.0 (R8). Draw runs as their own layer (stain on intact paint), so
the corrosion rules count corrosion only. A 16 mm bar is under one pixel of a 50 px/m facade mask,
so draw the run in the bar's own space (across 0-1, along in metres) at the fine stage or in the
engine, and judge it at the player's 1 m view: it must read at dE 15 or more over 2 mm of the
bar's width (R8c). A mask-space run that passes at 50 px/m can be an invisible tint at 1:1.

**Dark beside bright.** Thick old rust has an ochre outer and a dark inner layer; where the outer
layer flakes, dark rust shows, and fresh breaks show orange. So 15-40 % of the rust is dark
(L* 32 or less, where water stays: feet, joints, the bottom rail, rail tops, the rails' drip line,
the Ts' underside corners and the first 0.1 m of each bar below a T) and 8-25 % bright (L* 46 or
more and C* 30 or more, at fronts and new sites) (R9). Dark scale must be opaque: at 0.92 opacity
over a cream coat, even L* 25 rust composites to about L* 35, and a clip of the alpha anywhere
downstream undoes the opacity set upstream, so check the composited L* after the last step. Hold the
dark share by quantile over the rusted steel, not by noise thresholds, so it stays in band at every
amount. And keep the dark scale off the fresh
fronts, or it covers the bright rust that marks them. Wet rust darkens only 3-5 L*, but gains
gloss: "bright wet rust" is fresh orange in the albedo plus lower roughness.

**The blue sheen is a reflection, never a colour.** Compact goethite, magnetite and hematite reflect
13-31 % at normal incidence against 4 % for paint, so the near-black scale mirrors the sky: a rough,
steady blue-grey gloss on the oldest dense scale, whitening toward grazing angles; not a rainbow
film. Bake it as a mask on the steel (the danchi export: `M_hi.A` on steel pixels) and raise F0 and
lower roughness under it in the material. A preview without a reflection term shows dark surfaces
5-7 L* darker and warmer than an engine will, so judge the sheen with a sky reflection on.

## The clean coat varies in colour, not only in value

A coat's thickness, its laps and its chalking vary its value; its pigment load and the substrate's
damp also shift its chroma and hue. Drive a chroma field and a warm/cool field at the clouds'
scales (10 cm-2 m): about 0.3-1.2 C* of band-passed std, ±2-4° of hue, luminance kept (J1b). It is
the cheap answer to "more variety in saturation".

## Masks from the geometry: corners, recesses, top edges

Pro weathering generators (Substance Painter's Dirt, Metal Edge Wear and Dripping Rust; Houdini's
Bake Geometry Textures, Mask by Feature, Labs Physical AO) build every dirt and wear mask from mesh
maps: AO, cavity and convexity at two scales (crevices 2-10 mm, recesses 0.1-1 m), world normal and
position, times a grunge breakup:
```
dirt = levels(a·(1-AO_r) + c·concave_s + u·up(N) + g·grad_y, contrast) × (1 - e·convex_s) × grunge
wear = levels(k·convex_s × (1 - m·(1-AO_r)) × grunge)
```
Dirt comes off bright arrises (`e`), and wear stays out of occluded corners (`m`). Measure
curvature and AO on the assembled facade, not per kit piece (it fails at module borders).
**A recess's bottom is its floor line, not a depth edge.** In an elevation capture, a nearer surface
below a wall is usually a parapet hiding it; the junction where water stands is lower, out of view.
Take the bottom 0.3 m of each recess face above its floor line. Found from depth alone, the danchi's
growth ran in a band along every walkway parapet. Soften a recess weight over about 0.25 m too, or
its edge 1.5-2.5 m from a nearer wall shows as a step in the dirt. On a
facade: inside corners collect 1.15-1.6× the dirt in 0.1-0.4 m strips (1.25-2.0× derelict), fading
out by 0.6 m so corners are not outlined; recess faces 1.1-1.5×; corner and recess bottoms carry
twice the growth (G7). The top corners of a facade take up to 20-30× the rain of its centre (PCI):
neglected, the band under the top (≥ 1.4×) and the top corners (1.6-3×) go dark and green-black
(F5).

## What reads at each distance

At 1080p with a 90° horizontal FOV one pixel spans d/960 m at distance d.

| Feature | Size | Spans 2 px at (1080p / 4K) | Under 1 px beyond (1080p / 4K) | Carrier |
|---|---|---|---|---|
| fleck, paint lip, hairline | 1 mm | 0.5 / 1.0 m | 1.0 / 1.9 m | tiling detail; then tone and roughness |
| grain, small pore | 3 mm | 1.4 / 2.9 m | 2.9 / 5.8 m | tiling detail |
| bughole, rust pit cluster | 1 cm | 4.8 / 9.6 m | 9.6 / 19 m | detail and masks |
| chip, flake, rust margin | 3 cm | 14 / 29 m | 29 / 58 m | masks at 50 px/m plus detail |
| rust patch, corner dirt band | 10 cm | 48 / 96 m | 96 / 192 m | masks, mesh-map terms |
| stain, peel patch | 30 cm | 144 / 288 m | — | masks, decals |

A feature below a pixel must leave its mean effect (darkening, roughness) in the mips.

## Not yet checked (advice until a rule uses it)

- **Roughness, normal and height are not weathered by any rule:** every danchi rule measures albedo.
  Starting numbers: wet paths and damp films 0.05-0.3 smoother; dust 0.05-0.1 rougher; repaint
  patches 0.05-0.1 smoother; growth by subtype (roughness 0.6-1.0, height 0.3-20 mm). The open
  action is in `docs/redesign/research/README.md`.
- **A height cascade:** each layer adds height (peel lip, rust scale, deposit, growth cushion) and
  later layers read the composite height, so dirt fills peel steps, chip floors and rust pits.
