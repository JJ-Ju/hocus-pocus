# Rust on thin members, and wear that respects depth and grooves

Date: 2026-11-08. For `scripts/weathering/rust_flow.py`, `wx_hires.py`, `weather_fields.py` (`layer_peeling`,
`layer_wear`), `wx_export.py` and the kit, at rulebook 1.7 (40a9963). Two asks the generator has not met: rust that
runs down the uprights and grows along the rails, and paint failure that stops at depth steps and treats a groove as
a groove.

## Conventions

- Tags (README): **S** a published source; **M** measured, or **M, repo** my reading of the repo at 40a9963 [35];
  **P** read from photos in the repo's notes; **I** inference or arithmetic; **C** a craft estimate to calibrate;
  **U** the user's words. **[n]** is a source in §6; "(snippet)" means seen only in a search summary. No photos were
  measured this round (no downloads).
- Screen density, UE 90° horizontal FOV: 1,920/d px/m at 4K, 960/d at 1080p. Colour differences are dE (CIE76), as
  the gates compute them (`gate_r.py`). Clean rail paint is L\* 86.9 (linear 0.70/0.70/0.68, `assign.vfl`) [M, repo].

## 0. Summary

1. **Runs are drawn where they cannot exist** [M, repo]. A 16 mm upright is 0.8 px at 50 px/m; the run decays over
   5–7 cm at Derelict (`RUNUP_LEXP` 0.05 m at rust 0.5, times a per-bar factor) from a source opacity of 0.25–0.65,
   so 10 cm below a joint it is at α 0.03–0.16: dE 1–5 and C\* under 5, the "faint pink tint". R8 passes because it
   counts any α ≥ 0.06. The onsets start rust on the top rail's upper face (`C_TOP` 0.036 < `C_JOINT` 0.078).
2. **Pros give thin members their own UV space** [S]: trim strips, per-part masks on a second UV set [12],
   vertex-colour lerps [14], per-instance data [5]–[8], or a unique bake with axis drips [1]; decals suit walls [9][10].
3. **Recommendation: member space** (§1.6 a) [I]: UV0 across and along each member in metres, 8 floats per upright,
   a 1 cm strip per rail face and a shared run atlas at 2,048 px/m. About 4 MB per building, against about 50 MB for
   unique front faces at 512 px/m and about 65 MB for four bay variants.
4. **A run on a bar** [P, S, I, C]: member-wide for 2–5 cm under the joint, then a stripe over 30–80 % of the face
   (not the arrises) with darker tide lines [23], ending in a teardrop or a collar. At Derelict it reaches ≥ 75 % of
   the 0.93 m upright below ≥ 75 % of joints [U].
5. **T-joints rust first, at the underside corners** [U, S, I]: edges and welds hold 50–90 % of corrosion starts
   [16], weld toes get 50–70 % of the flat film [17], and paint's contact angle (70–78° [22]) exceeds the 45°
   Concus–Finn limit for a 90° corner [20], so drops sit in the corner. The top face fails later.
6. **Exposed metal should be dark** [S, C]: oxide is not metal [26]; L\* 38–48, a\* 0 to +4, b\* +2 to +8, roughness
   0.55–0.75, against today's L\* 55 (`LAB_BARE`) and 52.5 (`C_FLASH`) [M, repo].
7. **Patterns must be keyed to surfaces** [S; M, repo]. Pros take noise from 3D position or object identity
   [3][4][11]; ours are 2D elevation fields that run across the 1.2–1.4 m step from a balcony front to the wall behind.
   Fix: a surface-ID AOV, five fields assigned by colouring the surface graph, per-ID upsampling and reveal salts; in
   the engine a depth shear and a mask layer for walls hidden in elevation.
8. **A groove has zones** [S, C]: lips 3–8× the open face's chips [17][18]; a floor with fewer impact chips but a
   crack along the joint and bleed dirt [28][29]; more flaking under the lower lip, where water spills.
9. **Rules** (§4): R10–R13, P4 and N6; R8's 50 px/m bands are superseded.

## 1. Rust on thin members

### 1.1 What the player sees

| View | px/m | 16 mm upright | 45 mm top-rail face | 6 mm stripe |
|---|---|---|---|---|
| facade mask (the generator) | 50 | 0.8 px | 2.3 px | 0.3 px |
| 4K at 0.5 m (walkway, own balcony) | 3,840 | 61 px | 173 px | 23 px |
| 4K at 1 m | 1,920 | 31 px | 86 px | 12 px |
| 1080p at 1 m | 960 | 15 px | 43 px | 6 px |
| 4K at 6 m | 320 | 5 px | 14 px | 2 px |
| 4K at 15 m (street to a third-floor balcony) | 128 | 2 px | 6 px | 0.8 px |

T0 (p/t ≤ 2) needs about 1,920 px/m of detail on a rail seen from 0.5 m. A stripe drops under 2 px beyond about 6 m
at 4K; past that only the bar's mean colour counts, and it must equal the 50 px/m layer [I].

### 1.2 How pros carry rust on thin members

| Carrier | Practice | Follows the member | Across a 16 mm bar | Cost on the south front [I] | Our use |
|---|---|---|---|---|---|
| Unique bake of a kit piece | Painter's Dripping Rust reads curvature, AO and position and drips along a chosen position axis, Drips Intensity setting the length [1]; a rusty-gate diorama used anchor points and projected decals [13] | yes, along the axis | as baked | a bay of rail is 2.5 m² of steel: one 2048² set at 1,024 px/m, about 16 MB with normal, ORM and mips | variants only (§1.6 c) |
| Trim or tube strips, V along the member | the metal trim already planned for rail tubes, posts and extrusions (`texturing-at-scale.md` §10.4) [34] | yes | a shared tile at any density | no unique texels | the detail |
| Per-part masks on a second UV set | UV0 unique normal and AO, UV1 shared trims, UV2 RGBA masks per part; 512 px/m minimum [12] | yes | the mask's density | about 2 MB of strips | rail amounts |
| Vertex colour lerps | paint, bare metal and rust lerped by vertex channels on pipes, with Height Lerp [14] | at the vertex spacing | none (a gradient) | 16 rings per bar adds 0.35–0.7 M vertices | coarse only |
| Per-instance data | UE Custom Primitive Data, 32 floats, instancing kept [5]; ISM per-instance custom data, from Houdini as `unreal_num_custom_floats` and `unreal_per_instance_custom_data0…` [6][7]; Godot MultiMesh `INSTANCE_CUSTOM`, 4 floats (16-bit on Compatibility), plus an instance colour [8] | yes, with member-space UVs | an analytic shape over shared tiles | 8 floats × 2,760 members = 88 KB | per-upright runs |
| Decals | UE DBuffer decals hit every receiver in their box with Receives Decals [10]; Godot decals take a cull mask and normal fade, 512 clustered elements in view, 8 per mesh on Mobile [9] | no | the atlas's density | about 2,400 runs at Derelict | concrete stains only |
| Flow simulation | Dorsey's drops, Painter's particle brushes; Houdini's Grunge Drips COP is image noise with no sources (`r5-wear-simulation.md`) [34] | yes | as baked | — | the generator, in 1D |

Only member-space UVs read at 1 m: 33 texels of shared detail across the bar at no unique cost, and every 2D drip tool
(Painter's axis drips, Designer's slope blur, our carry loop) works once V runs along the member [I].

### 1.3 Anatomy of a run on a painted bar

- **Water path** [M, repo `pieces.py`; I]. The 64 mm top rail overhangs the upright by 24 mm each side, so its front
  drips fall clear. The bar gets driven rain, the film under the rail drawn into the joint corners (§1.4), water from
  inside a hollow rail through weld pinholes (as rust bleeds from stitch welds [19]) and condensation, and drains to
  the bottom rail, whose top face stands 7 mm proud each side.
- **Width** [P, r4 §3; I]. Japanese rails show runs 1–4 cm wide at the source and 0.3–1.5 m long with teardrop ends,
  so the head is member-wide; below it a low flow meanders as a rivulet [24] a few capillary lengths (2.7 mm) wide.
- **Face, not arris** [S; I]. Liquid pulls back from convex edges as wet paint does [17] and stays pinned at an edge
  up to the Gibbs limit [21], so the stain runs on the face; arrises show only the bar's own corrosion (1–2 mm lines).
- **Tide lines** [S; I]. Each wetting dries from its edge, carrying iron outward (the coffee-ring flow [23]): darker
  margins 0.5–1.5 mm wide, banded after many cycles.
- **Colour by density** [M, photo: rust note §6; I]. Heads darker and redder (hue 52–56°), tails lighter and yellower
  (68–75°); the head colour at low opacity over white falls to C\* under 7 at hue 55–60° and reads pink.

**Runs on a 16 mm upright, 0.93 m clear, by preset.** S is the years since the steel was painted, by the rust note's
steel clock (rule 11, not yet in the generator): Kept 4.6, Typical 8.5, Worn 14.3, Derelict 20.7 [I]. Colours are as
seen over the white paint at 1:1.

| Measure | Typical (S 8.5) | Worn (S 14) | Derelict (S 21) | Extreme (rust 1.0) | Tag |
|---|---|---|---|---|---|
| T-joints with a run of 5 cm or more | 20–40 % | 50–70 % | ≥ 75 % | ≥ 90 % | U, C |
| median reach, share of 0.93 m | 5–16 % | 20–50 % | ≥ 75 % | ≥ 95 % | U; P (rust note §5: 15–40 cm at 12–20 y, most of the length after 20) |
| runs that reach the bottom rail | ≤ 2 % | 5–15 % | ≥ 40 % | ≥ 80 % | U, C |
| head, member-wide, below the joint | 2–3 cm | 3–4 cm | 3–5 cm | corroded | P (sources 1–4 cm) |
| body width, share of the face | 30–60 % | 40–70 % | 50–80 % | 60–100 % | I |
| tail, last 15 % of the run | 15–30 % of the face, fading | 20–40 % | a collar instead | — | C |
| head L\*, a\*, b\* (dE) | 44–52, +10–16, +14–22 (≥ 30) | 40–50, +11–17, +14–24 (≥ 35) | 38–48, +11–18, +14–26 (≥ 40) | old rust (R9) | M rust note §6; C |
| body / tail L\*, a\*, b\* (dE) | 58–70, +6–12, +16–28 (≥ 15) / 70–80, +3–8, +12–22 (≥ 8) | the same; body dE ≥ 18 | the same; body dE ≥ 20 | — | M photo hues; C |
| collar above the bottom rail | — | 1–3 cm | 3–8 cm | merged | C |
| drip bulbs | 30–50 % of tails, 1.2–1.8× the tail width, 4–8 mm long | the same | — | — | P (teardrop ends); C |
| rust lines along the bar's arrises | none | none | 0–20 % of the length | 30–60 % | I (coatings note §3) |

### 1.4 T-joints and the rails

- **Why the underside corners go first** [S; I]. The weld toe gets 50–70 % of the flat film, thinner at spatter and
  undercut [17]; the crevice is out of the spray's reach and holds water [17][19]; drops under the rail (about every
  24 mm, rust note §3) that form within a few mm of an upright land in the corner. A 90° corner wicks water away only
  below a 45° contact angle [20]; white enamels measured 70–78° after a month outdoors [22], so the water sits as a
  corner-bound drop and the corner dries last, longer once salts and porous rust are there [36].
- **Why the top face is later on a painted rail** [U; I]. It has the thickest film (paint levels there) and is
  rain-washed; bare coupons facing up do corrode faster (BRANZ, rust note S8; Hunan [25]), so once hands, laundry and
  sun break its film it advances fast: "the top would probably advance more with advanced wearing".
- **How a rail grows sideways** [I]. Creep under paint is 0.1–3.5 mm a year (rust note §2), so growth is new failures
  along the wet lines beside each joint: underside, lower arris, then up the front face. The 94 mm gap between bars
  closes when each patch has grown 47 mm each way. The bottom rail pools each upright's water at a re-entrant corner
  on its top face: collars and top-face patches first, then the front face and drips onto the upstand.

**Rust at the T-joints and along the rails, by the rust control's step** [C, from U]:

| Measure | 0.25 | 0.5 | 0.75 | 1.0 |
|---|---|---|---|---|
| T-joints rusted at the underside corners | 30–50 % | 70–85 % | ≥ 90 % | ≥ 95 % |
| patch along the underside and lower arris, each side of the upright (median) | 3–10 mm | 15–25 mm | 30–45 mm | ≥ 47 mm (merged) |
| dense collar down the upright from the joint | 1–2 cm | 2–4 cm | 3–5 cm | becomes the run |
| top rail front face, rust height above the lower arris | 0–3 mm | 3–10 mm | 10–25 mm | 25–45 mm |
| top rail lower-arris row rusted | 8–20 % | 30–50 % | 60–80 % | ≥ 90 % |
| top rail upper face, share of the rail's rust | ≤ 5 % | ≤ 10 % | ≤ 25 % | 30–50 % |
| bottom rail top-face row rusted | 5–15 % | 25–45 % | 55–75 % | ≥ 85 % |

### 1.5 Tarnished bare metal

| State | L\* | a\* | b\* | Metallic; roughness | Where | Tag |
|---|---|---|---|---|---|---|
| **target "exposed metal": tarnished steel, as seen** | 38–48 | 0 to +4 | +2 to +8 | 0.3–0.5 (60–80 % oxide over metal), base colour linear 0.08–0.15; 0.55–0.75 | rims round rust, chip floors | U; S [26]; C |
| bright rubbed steel | ≈ 77 (iron F0 0.530/0.513/0.494 [27]) | +0.7 | +1.9 | 1; 0.35–0.5 | the top rail's upper face in the hand zone only | S; coatings note §3 |
| dark oxide (magnetite) film | 25–38 | +1 to +4 | 0 to +6 | 0; 0.65–0.85 | old exposed metal under shelter | M rust note §6; C |
| mill scale | 25–35 | ≈ 0 | ≤ 3, bluish | 0; 0.5–0.7 | chips on hot-rolled bars, under old paint | coatings note §3 |
| flash-rust haze | 55–65 | +8 to +12 | +20 to +28 | 0; 0.7–0.85 | within 1–3 mm of chips under about a year old | S (snippet), coatings note |
| red-oxide / grey primer | 36–44 / 55–65 | +24–30 / ≈ 0 | +14–26 / ≈ 0 | 0; 0.6–0.8 | rims of spot repairs | coatings note |

Substance's PBR guide lowers metallic where oxidation covers metal, and a practitioner rule keeps metal base colour at
sRGB 180–250 with oxide or paint as a non-metal layer [26]. Under a uniform sky a rough metal at F0 0.35 reads about
L\* 66, so the user's "darker, tarnished/worn" (about L\* 45) must come from the oxide share, not a darker metal [I].
`LAB_BARE` (L\* 55) and `C_FLASH` (L\* 52.5) are 7–15 L\* too light [M, repo].

### 1.6 Four ways to ship it

The default south front has 120 bays of 2.3 m open rail, each with 20 uprights (16 × 16 mm), 3 posts (44 mm), a
45 × 64 mm top rail and a 30 × 30 mm bottom rail [M, repo `pieces.py`]: 2,760 bars and posts, 240 rails, ~300 m² [I].

| Option | Memory per building | Detail at the bar | Follows the generator | Repeats | Verdict [I] |
|---|---|---|---|---|---|
| (a) member space: UV0 along each member; 8 floats per upright and post (88 KB); rail strips, 1 cm × 8 rows RGBA8 (2 MB); a shared run atlas (1.6 MB) | ≈ 4 MB | 2,048 px/m, shared | exactly, per member | never | **recommended** |
| (b) a unique rail atlas | all faces: 317 Mpx at 1,024 px/m, about 0.85 GB with normal and mips; 210 MB at 512 px/m; front faces only at 512 px/m about 50 MB | as baked | yes | never | over the 40 MB budget, and still soft at 1 m |
| (c) four rust variants of the bay piece | 4 × 16 MB at 1,024 px/m; about 270 MB at 2,048 | 1,024–2,048 px/m | no: four states for 120 bays | every 4 bays | hero pieces at most |
| (d) decals | atlas about 1 MB; about 2,400 instances | the atlas's | yes | never | over Godot's caps, projection rules; keep for concrete |

## 2. Patterns that ignore geometry

### 2.1 How pros key patterns to surfaces

- **3D position** [S]: Painter's tri-planar projection covers a mesh "without creating any visible seams", Tri-Planar
  Advanced blends by world-space normals [3], Metal Edge Wear projects its grunge triplanar [2]; UE's noise is seeded
  by world position and pinned to an object by subtracting the actor position or by a bounding-box UVW [11].
- **Per object or element** [S]: ObjectPositionWS, Per Instance Random and per-instance data [5][6][11]; Designer's
  Flood Fill to Random Grayscale and per-island offsets [4, snippet]; Painter's ID-map selection and polygon fill.
- **The shared idea** [I]: the random value comes from the surface's identity or 3D position, never from an elevation
  coordinate that two surfaces share.

### 2.2 Decorrelating a 2D projection: methods and pitfalls

Our paint-failure `defect` is an fbm at S6–S8 (σ 0.25, 0.125, 0.0625 m) plus a 1.4 cm grain; the wear break field
has σ 0.25 m and the chip clusters 0.3 m. All are 2D fields on the plane grid, and the fine reveals hex-sample one tile
per layer at (x, y) [M, repo]. For blurred white noise the correlation at distance d is ρ = exp(−d²/4σ²).

| Method | What it separates | Cost | Pitfalls |
|---|---|---|---|
| Surface-ID AOV from the kit (piece instance × face group; panels split at joints) | every surface exactly, panels at one depth included | one integer AOV in `crop_capture.py` | none if the kit labels faces; planes take it by mode at 50 px/m |
| IDs from discontinuities: cut at ≥ 3 cm or ≥ 30° at 50 px/m, ≥ 4 mm at 1 mm/px | occlusion steps; grooves at the fine grid | connected components | misses steps under the threshold; 50 px/m cannot see a 10 mm groove; faces steeper than about 56° step 3 cm per pixel |
| Fixed depth slices | steps | cheap | cuts a sloped surface into bands: seams |
| 3D noise of (x, y, depth) | steps larger than the noise: ρ 0.003 across 1.2 m at σ 0.25 m | a 3D noise per octave over 7 Mpx per plane | nothing at one depth: ρ ≈ 1.0 across a 10 mm groove at every octave |
| Independent fields per ID, by colouring the ID adjacency graph | neighbours exactly | 5 fields per noise call instead of 1 | none with hard switches at real edges |
| Random domain offsets per ID | only past about 4.3σ (1.1 m at σ 0.25 m) | a field larger than the plane | short offsets keep correlation |
| Feathered blend between two fields | — | — | σ falls by √(w² + (1−w)²), to 0.71 midway [32]; renormalise or switch hard |

- **Bleed and shared coordinates** [M, repo; I]: upsampling spreads a 50 px/m value, and the 10 cm local opacity
  `pk`, 2–4 cm onto the other surface; hex-tiled chip and flake tiles at (x, y) run across the step. Upsample, take
  `pk` and salt the reveals per ID, as the skill already does per class.
- **The engine re-couples what the generator separated** [I]: a facade mask projected along the plane normal gives
  every hidden surface the occluder's texels, so the lower 1.1 m of a walkway's back wall, the player's nearest
  surface, would wear the parapet's chips. Hidden surfaces need their own mask layer.

### 2.3 Joints, grooves and arrises

- **Our groove** [M, repo `bal_front_profile.vfl`; S]: a construction-joint groove at floor level on the balcony and
  corridor fronts, 20 mm tall and 10 mm deep with sharp lips, beside 12 mm chamfers on the outer arrises. Precast
  joints are at least ¾ in (19 mm) wide, with sealant at 2:1 width to depth [30].
- **Lips** [S; I]: paint pulls back to 50–70 % of the flat film at edges [17] (30–50 % by one vendor [18]); chamfers
  protect concrete corners, but coatings still pull back from their corners [31]; lips also take the knocks.
- **Inside** [S; I]: paint over a moving joint cracks once stretched past its elastic limit and notches the sealant
  until it tears; plasticiser softens the paint and sharply lowers its dirt resistance, so the joint darkens [28];
  Japanese makers sell non-bleed sealants because ordinary ones blacken painted joints [29]. The floor is sheltered.
- **Water** [S; I]: the upper lip is a drip edge [21]; water falls onto the lower ledge, runs sideways and spills at
  low points (the generator's groove streak sources), wetting the face below; run-off drops dirt where it slows at
  breaks (PCI DN-29, coatings note §4).

| Zone (groove 20 × 10 mm) | Failure against the open face | Kind | Sizes | Tag |
|---|---|---|---|---|
| lip bands: face side 0–6 mm, groove side 0–3 mm, each sharp lip | chips 3–8× (rule floor 3×) | chips that break the arris, half each side; from Worn 5–10 % expose concrete | 1–10 mm along the lip (lognormal, median 3 mm), 1–4 mm onto the face; impact chips 10–25 mm | S [16][17][18]; C |
| 12 mm chamfered arris | 2–4× | the same, smaller | 1–6 mm | S [31]; C |
| groove floor (sealant or cold-joint face) | impact chips 0.3–0.6× | a crack along the joint on 20–40 % of its length at Typical, 50–80 % at Worn, ≥ 80 % at Derelict; 2–6 mm flake strips along it from Worn; 5–15 L\* darker (bleed, dirt) | cracks 0.2–1 mm | S [28][29]; C |
| face below the lower lip, 0–15 mm | flaking 1.5–2.5× | blisters and flakes from the spill; a dirt line | 3–15 mm | I; C |
| face above the upper lip, 0–10 mm | 1–1.5× | drip-edge dirt | — | C |
| open face, ≥ 0.1 m from a lip | 1× | P1's ISO 4628-5 amounts | 3–30 mm | rulebook P1 |

So "more or less" is both: more at the lips and below the lower lip, fewer impact chips inside, and inside a
different failure, a line rather than flakes [U; I].

### 2.4 Edge chipping that follows the edges

- **Pro tools** [S]: Metal Edge Wear multiplies a weighted curvature term (Standard, Sobel or Smooth) by a grunge and
  keeps occluded areas clean by AO masking [2]; Houdini bakes curvature, cavity and edge maps and its Mono to SDF COP
  gives each pixel's distance to a contour [33]; one breakdown ages from Sobel edges on world normals [15]. Recipe:
  chips = threshold(grunge + k × convexity at radius r), r of mm for chips and cm for the band, with AO or concavity
  keeping them out of inside corners (`surface-detail-techniques.md` §2).
- **Ours can be exact** [I]: the capture's depth at 1 mm/px marks each groove; a distance transform gives d to the
  nearest lip; convexity = exp(−d/λ), λ 2–4 mm on the face and 1–2 mm inside. No bake, no curvature noise, and the
  same field drives the engine's joint trim.

## 3. Recommended design

### 3.1 Member rust

1. **Members from the kit.** Balustrade and handrail pieces emit a member list (id, type, bay, endpoints, profile,
   joints) and prim attributes `member_id`, `muv` (u around the profile in m from the front-left arris; v along it in
   m, down from the top joint on uprights, from the bay's left end on rails) and `mface`, rendered as AOVs.
2. **Rust on the member graph** (new in `rust_flow.py`; the raster path stays for panels and doors). Nodes are
   T-joints, feet and post caps; edges are members with face rows. Onsets c (rule 4's form; calibrate with
   `_calib_rust.py`) [C]: T-joint underside corners 0.035, feet 0.05, bottom-rail junction pools 0.06, rail front face
   0.35, rail top 0.60, upright faces 0.85. Rail rows grow from the joints by a 1D min-plus arrival, k 1.0 along the
   underside and lower arris, 0.4 up the front face, 0.25 on the top (targets: the §1.4 table).
3. **Per-upright data** (8 floats): reach f = f_S(S) × U(0.7, 1.3) × (0.8 + 0.2 w), f_S 0.1 at S 8.5, 0.35 at 14,
   0.85 at 21 and 1.0 from 24 [C]; head density ρ = 0.6 + 0.4 × the joint's rust age; seed; lateral offset (±0.25 of
   the face); collar height; arris share; wetness; joint age. **Rail strips**: 1 cm texels, 8 rows (underside, lower
   arris, front low and high, upper arris, top, back, spare): R arrival time, G age, B wetness, A bare-metal chance.
4. **The run**, one function for the mirror and both shaders (v down from the joint, L = f × 0.93 m, t = v/L, w the
   face): **head** v ≤ 0.02 + 0.03ρ m, whole face, opacity 0.85 + 0.15ρ; **body** (t ≤ 0.85) width w × lerp(0.8,
   0.35, t^0.7) round the offset plus a meander ≤ 0.15 w at 0.1–0.3 m wavelength, opacity × (1 − 0.55 t^1.3), tide
   lines 25–40 % denser in the outer 0.5–1.5 mm; **tail** (t 0.85–1) to 0.4× and fading, 30–50 % ending in a bulb
   1.2–1.8× wide and 4–8 mm long; **collar** 1–8 cm when L reaches the bottom rail. Reveal by the edge rule against
   the run tile (2,048 px/m, equalised), coloured by density class (§1.3): ochre, never pink [I, C].
5. **T gather, rails and scale**: corner patches carry dense old rust (R9's dark class); the lower-arris row grows
   sideways, the front face up from it, the top only from 0.75; bare metal and rims (R7) come from channel A in the
   §1.5 colours. The member result box-filtered to 50 px/m is the facade rust layer (R1–R5, far LOD), ±3 % per bay.
6. **Export** [S; I]. UE: uprights and posts as (Nanite) ISM instances with `unreal_num_custom_floats = 8` and
   `unreal_per_instance_custom_data0…7` [7], passed from the vertex shader through interpolators; rails as instances
   with a strip row each; UV0 member space in metres, UV1 the strip coordinate. Godot: one MultiMesh per piece type
   per facade with `INSTANCE_CUSTOM` and the instance colour (4 + 4 floats) [8]; the strip atlas uncompressed RGBA8,
   nearest across rows, at most 2 mips. Shared run atlas (8 bodies of 64 × 2,048 px, 16 head and drip cells of
   64 × 128) as BC5, about 1.6 MB. Steel then needs no facade rust channel, and decals stay on the concrete.

### 3.2 Surface-keyed wear and grooves

1. **Surface IDs.** The kit writes `surf_id` (piece instance × face group; groove faces their own group; panels split
   at joints), rendered as an AOV and taken by mode at 50 px/m; discontinuity IDs must agree on ≥ 95 % of boundaries.
2. **Fields per surface.** In `layer_peeling` (`defect`, `fine`), `layer_wear` (`brk`, chip clusters, `jit`) and the
   damage clusters, build 5 independent fields per call, give each ID one by greedy colouring of the adjacency graph
   (IDs that touch, or lie within 0.1 m across a step) and switch hard at ID edges. Amounts stay per zone (P2) [I].
3. **Per-ID upsampling and reveals** in `wx_hires.py`: `masked_up` and `pk` per ID; each ID's hex and band tiling
   takes salt + 7919 × id and a domain offset of (37 h₁, 59 h₂) m from a hash of the ID.
4. **Groove zones** (§2.3) from the capture depth, coverage kept per 50 px/m cell (weights renormalised over 3 × 3
   coarse cells, so T3 holds). Lips reveal against a lip-chip band tile sampled along the groove (chips 1–10 mm,
   1.5–3× longer along the lip, centred on it); the floor gets a crack line, 2–6 mm flake strips and bleed dirt.
5. **Engine.** Sample reveal details at f + (0.37, 0.61) × depth, depth = dot(P − O, N): the balcony's back wall
   shifts (0.44, 0.73) m against its front and no plane distorts. The joint trim's lips carry the chip heights and
   its floor the crack and bleed line (the planned 64 px joint strip, `texturing-at-scale.md` §10.4). A **back mask
   layer per front** covers surfaces hidden in elevation (loggia back walls, corridor walls below the parapet tops),
   captured with the front pieces hidden, at 25 px/m for paint failure, wear and soiling: 3–6 MB per front, chosen
   per piece by an index, taking the masks from 28–31 MB (`texturing-at-scale.md`, round I) to 34–43 MB [I].

## 4. Proposed rules

In the rulebook's form (each binding, with its origin tags); bands tagged C need calibration against the user's picks.
"1:1" means crops at 1,920 px/m (4K at 1 m), as `wx_texcheck.py` makes its close-ups.

| Rule | Measure | Pass | Origin |
|---|---|---|---|
| **R10** metal: runs read at the player's distance (supersedes R8, which counted α ≥ 0.06 at 50 px/m) | 1:1 crops of the railing bays: for each T-joint, the stain on the upright below, rows where bar pixels at dE ≥ 15 against the clean bar span ≥ 4 px (2 mm), gaps ≤ 2 cm bridged; reach as a share of the clear height; head dE (top 5 cm); hue and C\* of run pixels; the member result at 50 px/m against the facade layer | Typical: runs below 20–40 % of T-joints, median reach 5–16 %; Worn: 50–70 %, median 20–50 %; Derelict: ≥ 75 % of T-joints, median reach ≥ 75 % (0.70 m), ≥ 40 % reaching the bottom rail; head dE ≥ 30 (≥ 40 at Derelict); run hue 50–80°, pixels under dE 15 at hue ≥ 65° and C\* ≥ 8 (no pink); never wider than the bar; body 30–80 % of the face; per-bay amount within 3 % | U ("running all the way down or almost all the way down"; "still no rust going DOWN"); P (r4 §3; rust note S44a); C |
| **R11** metal: T-joints rust first, at their underside corners | railing corrosion (as R1, feet and runs left out) within 3 cm of a T-joint's underside corners (the rail underside and lower arris within 3 cm either side of an upright, and the upright's top 3 cm); the top rail's upper face as a share of the rail's rust; T-joints rusted | ≥ 60 % of rail and upright corrosion at T-joints at 0.25; the upper face ≤ 10 % of the rail's rust up to 0.5 and ≤ 25 % at 0.75; ≥ 85 % of T-joints rusted at Derelict | U ("TrTrTrTr"); L (50–90 % of attacks at edges and welds [16]; weld toes 50–70 % [17]); I (Concus–Finn) |
| **R12** metal: rails rust along their length, step by step | per step: rusted share of the top rail's lower-arris row (lower 8 mm of the front face) and of the bottom rail's top-face row; mean rusted segment; share of new rail rust within 0.1 m along its row of earlier rust or a joint | lower-arris row 8–20 / 30–50 / 60–80 / ≥ 90 % at 0.25 / 0.5 / 0.75 / 1.0, each step ≥ 1.5× the last until 80 %; mean segment ≥ 1.4× per step; ≥ 80 % of new rail rust continues a patch | U ("more horizontal rusting growth between steps"); M (creep 0.1–3.5 mm a year); C |
| **R13** colour: exposed metal is tarnished, not bright | 1:1 crops: bare-metal pixels outside the hand zone (the top rail's upper face): L\*, a\*, b\*; flash-rust pixels (L\* 55–65, b\* ≥ 18) by distance to a chip new since the last step | median L\* 38–48, a\* 0 to +4, b\* +2 to +8; ≤ 20 % above L\* 55; flash rust only within 3 mm of new chips; the hand zone may reach L\* 55–65 | U ("a little darker, tarnished/worn"); L [26], coatings note §3; C |
| **P4** peeling: patterns stop at depth steps | at 50 px/m and on 1:1 crops, at every boundary between surface IDs whose depth differs by ≥ 3 cm: the share of flake, chip and peel labels touching both sides; the Pearson correlation of the paint-failure and wear alphas (blurred 3 cm) between pixel pairs mirrored across it at 2–6 cm, both on paint | labels crossing ≤ 2 %; correlation between −0.2 and 0.2 (about 1 today, by construction); each side's amount follows its own zones (P2) | U ("the same chipping pattern ... front of the balcony ... the wall behind it"); L [3][4][11]; I |
| **N6** edges: grooves and their lips are respected | 1:1 crops of walls with joint grooves (≥ 1 m of groove each): chips per m² in the lip bands (face side 0–6 mm, groove side 0–3 mm), on the groove floor and on the open face 0.1–0.5 m away; crack-line cover along the floor; floor dL\* against the face; labels spanning face and floor | from Worn (or edges 0.25): lip-band density ≥ 3× the open face (target 4–8×); floor impact chips ≤ 0.6× the face; a crack or open line along ≥ 30 % of the groove at Worn and ≥ 60 % at Derelict; floor 5–15 L\* darker at Worn and Derelict; chips spanning face and floor only within 6 mm of a lip | U ("The chipping should respect the channel"); L [17][18][28][29][30]; C |

**Interactions** [I]: R10 measures runs as stain, so R3's cap on other upright faces keeps counting corrosion only.
R11 changes R3's onset order and settles round J's question about R4's first step (new rust at feet and joints only).
R12 sits inside R1's 5/10/20/40 % totals. P4 leaves P1–P2's amounts alone; N6 shares the edge amounts with N1–N4.

## 5. Unchecked

- **Nothing measured from photos this round**: run reach by age, T-joint patch sizes, stripe widths and tide lines
  are craft estimates anchored on r4 §3 and the rust note's S44a–d.
- **Underside against top face on painted rails**: bare-steel evidence is mixed [25] and I found no painted-rail
  study; the T-first order rests on weld, edge and crevice data and the user's reading. **No source** for chip
  density or chip size at concrete arrises (3–8×, 1–10 mm are C).
- **Could not read** PCI's and Enterprise Precast's reveal sheets (compressed PDFs), PCI's Ascent weathering page, the
  HAL page of Heitz and Neyret, or the CoatingsPro staircase body. **Not confirmed**: UE 5.7+ per-instance data in the
  pixel shader; the Houdini Engine version for the custom-data attributes; Godot 4.7's per-instance uniform limit;
  thin-bar decal bleed in UE. **Not searched**: 手すり 溶接部 錆 pages, UR joint surveys, JASS 8 joint tables.

## 6. Sources

1. Adobe, Painter, Dripping Rust generator — https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/effects/generators/dripping-rust
2. Adobe, Painter, Metal Edge Wear generator — https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/effects/generators/metal-edge-wear
3. Adobe, Painter, Tri-planar projection — https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/painting/fill-projections/tri-planar-projection ; Tri-Planar Advanced — https://experienceleague.adobe.com/en/docs/substance-3d-painter/using/effects/generators/tri-planar-advanced
4. Adobe community, flood fill per island (snippet) — https://community.adobe.com/t5/substance-3d-designer-discussions/flood-fill-issues/td-p/14533084 ; Flood Fill Mapper — https://helpx.adobe.com/substance-3d-designer/substance-compositing-graphs/nodes-reference-for-substance-compositing-graphs/node-library/filters/effects/flood-fill-mapper.html
5. Epic, Custom Primitive Data (32 floats; dynamic instancing kept) — https://dev.epicgames.com/documentation/en-us/unreal-engine/storing-custom-data-in-unreal-engine-materials-per-primitive
6. Epic API, ISM custom data — https://dev.epicgames.com/documentation/unreal-engine/API/Runtime/Engine/UInstancedStaticMeshComponent/SetNumCustomDataFloats ; https://docs.unrealengine.com/4.26/en-US/API/Runtime/Engine/Components/UInstancedStaticMeshComponent/PerInstanceSMCus-/index.html
7. SideFX forum, per-instance custom data from Houdini — https://www.sidefx.com/forum/topic/103384/
8. Godot, MultiMesh (`use_custom_data`, `INSTANCE_CUSTOM`) — https://docs.godotengine.org/en/stable/classes/class_multimesh.html
9. Godot, Decal; Using decals — https://docs.godotengine.org/en/stable/classes/class_decal.html ; https://docs.godotengine.org/en/stable/tutorials/3d/using_decals.html
10. Epic, Decal materials (Receives Decals, DBuffer response); mesh decals — https://dev.epicgames.com/documentation/en-us/unreal-engine/decal-materials-in-unreal-engine ; https://dev.epicgames.com/documentation/en-us/unreal-engine/using-mesh-decals-in-unreal-engine
11. UE forum and docs, noise from world position, ObjectPositionWS (snippets) — https://forums.unrealengine.com/t/noise-recalculating-every-frame/61444 ; https://forums.unrealengine.com/t/world-position-per-instance-grass/1153198 ; https://docs.unrealengine.com/4.27/en-US/RenderingAndGraphics/Materials/ExpressionReference/Vector
12. 80.lv, abandoned blowers (UV0/UV1/UV2, 512 px/m) — https://80.lv/articles/making-abandoned-blowers-with-blender-substance-3d-unreal-engine-5
13. 80.lv, rusty gate diorama — https://80.lv/articles/designing-a-diorama-of-a-realistic-rusty-gate-using-zbrush-and-unreal-engine
14. Polycount, vertex-colour rust on pipes (snippet) — https://polycount.com/discussion/comment/1601659/ ; UE forum, Height Lerp vertex blends — https://forums.unrealengine.com/t/materials-blended-by-vertex-using-height-on-non-landscape/437318
15. The Rookies, technical aspects of environment art (512 px/m; Sobel edges on world normals) — https://www.therookies.co/blog/breakdowns/technical-aspects-to-take-your-environment-art-to-the-next-level
16. Knudsen et al. 2023 (SINTEF), root causes of corrosion on painted steel — https://sintef.brage.unit.no/sintef-xmlui/handle/11250/3125983
17. AMPP CIP 1 study guide, stripe coating and critical areas — https://open-exam-prep.com/study-guides/ampp-cip1/ampp-cip1-ch5-application-methods/stripe-coating-and-critical-areas
18. Japanese coating supplier, edge film 30–50 % (snippet) — https://pr.mono.ipros.com/en/kinzokutoso/product/detail/2001654398/
19. AGA, rust bleeding on overlapping surfaces — https://galvanizeit.org/knowledgebase/article/rust-bleeding-on-overlapping-surfaces ; CoatingsPro, rusted staircase (snippet) — https://ampp.mydigitalpublication.com/articles/the-case-of-the-rusted-parking-garage-staircase
20. Concus–Finn corner wicking (snippets) — https://par.nsf.gov/servlets/purl/10511253 ; https://pdxscholar.library.pdx.edu/open_access_etds/6974
21. Gibbs' criterion at edges — https://arxiv.org/pdf/1410.6783
22. US 8,815,989, enamel contact angle after outdoor exposure (snippet) — https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/8815989
23. Coffee-ring effect (Deegan et al. 1997) — https://en.wikipedia.org/wiki/Coffee_ring_effect
24. Rivulets: contact angles on a plate; meandering (snippets) — https://arxiv.org/pdf/2310.02266 ; https://meetings-archive.aps.org/dfd/2012/m30/9
25. ASTM G50; Q235 skyward against earthward pits (snippets) — https://www.q-lab.com/corrosion/corrosion-test-standards/astm-g50 ; https://link.springer.com/content/pdf/10.1007/s11665-022-06839-9.pdf
26. Substance PBR Guide vol. 2 (copy; snippet) — https://www.scribd.com/document/413439897/286277128-PBR-Guide-Vol-2 ; dark metal in PBR — https://3dartist.neocities.org/dark_metal/dark_metal.html
27. Physically Based database — https://physicallybased.info/
28. Resene, Architect's memo 50 (paint over sealants) — https://www.resene.co.nz/archspec/archmemo/memo50.htm
29. Non-bleed sealant products (snippet) — https://mono.ipros.com/product/detail/2000073805
30. Joint width per PCI MNL-122 (JVI); 2:1 sealant (Pecora, Sika) (snippets) — https://jvi-inc.com/?p=5757 ; https://www.pecora.com/wp-content/uploads/2026/06/PCS.pdf ; https://nga.sika.com/dms/getdocument.get/57844682-e4c2-4047-b43f-8de530526999/sikaflex-428-precast.pdf
31. Chamfers and coatings at corners (practitioner; snippets) — https://theconstructor.org/concrete/chamfered-edge-concrete/27227/ ; https://civiltechnologylearning.blogspot.com/2019/07/how-to-make-chamfered-edge-in-concrete.html
32. Heitz & Neyret 2018, histogram-preserving blending — https://doi.org/10.1145/3233304 ; repo `tiling-and-distribution-algorithms.md` (σ × √Σw²)
33. SideFX, Mono to SDF; Curvature COP; Bake Geometry Textures — https://www.sidefx.com/docs/houdini/nodes/cop/monotosdf.html ; https://www.sidefx.com/docs/houdini/nodes/cop/curvature.html ; https://www.sidefx.com/docs/houdini/nodes/cop/bakegeometrytextures.html
34. Repo notes — `weathering-rust-water.md`, `coatings-concrete-corrosion.md`, `r4-visual-reference.md` §3, `surface-detail-techniques.md`, `texturing-at-scale.md`, `r5-wear-simulation.md`, `pro-asset-pipeline.md`
35. Repo code at 40a9963 — `scripts/weathering/rust_flow.py`, `wx_hires.py`, `gate_j.py`, `gate_r.py`, `weather_fields.py`, `wx_noise.py`; `examples/danchi/src/py/pieces.py`, `src/vex/bal_front_profile.vfl`, `src/vex/assign.vfl`
36. Time of wetness and hygroscopic salts (snippets) — https://store.ampp.org/time-of-wetness-in-marine-atmospheres-what-are-we-measuring- ; https://www.osti.gov/servlets/purl/1367735

## 7. Actions

| # | Action | Status |
|---|---|---|
| 1 | Kit member list and `member_id`, `muv`, `mface` AOVs in `crop_capture.py` | parked (the members come from the 50 px/m steel mask this round: `rust_flow.members()` finds Ts, their underside corners, rail rows and feet; revisit when the kit is captured with member AOVs for the engine round trip) |
| 2 | Rust on the member graph: T-joint underside corners first, rail rows growing from each joint, top face late; onsets recalibrated with `_calib_rust.py` against R11 and R12 | done (`scripts/weathering/rust_flow.py` members, seeds, wetness and arrival: the Ts' underside corners first, the drip line next, the top late; rules R3's T clause and R10, rulebook 1.8) |
| 3 | Run reach per upright from the steel years (Derelict at least 0.75 of the upright), with the other per-upright parameters | done (`scripts/weathering/rust_flow.py` `run_frac` and `_runs_k`: reach as a share of the bar by amount, per bar lognormal; rule R8, Derelict's median 75-100 % of the bar) |
| 4 | One run function (head, stripe, tide lines, tail, drip, collar) in the mirror and both shaders, revealed against a 2,048 px/m run tile, coloured by density | parked (the mirror's run is done in `scripts/weathering/wx_hires.py` `_run_member`: head, stripe, tide lines, ragged edges, drip end, collar; the UE and Godot shaders wait for the first engine round trip, with row 6) |
| 5 | Tarnished exposed metal: `LAB_BARE` to L* 38-48, flash rust only beside new chips, oxide share 60-80 % (metallic 0.3-0.5, roughness 0.55-0.75) | done (`scripts/weathering/rust_flow.py` LAB_BARE_K, `scripts/weathering/wx_hires.py` TARN at full opacity; rule R7's close-up colour clause) |
| 6 | Member export: UV0 member space; 8 per-instance floats (UE via the Houdini attributes, Godot INSTANCE_CUSTOM and colour); rail strip atlas; shared run atlas; no rust decals on bars | parked (member export: UV0 member space, per-instance floats, rail strip and run atlases; revisit at the first engine round trip, pro-asset-pipeline actions 3, 6b and 10) |
| 7 | The member result box-filtered to 50 px/m is the facade rust layer, within 3 % per bay | parked (the mirror draws each run's 50 px/m coverage across its bar, so coverage holds per cell by construction; the 3 % per-bay check needs the member export of row 6) |
| 8 | Rules R10-R13 in the rulebook and gate (R10 at 1:1 in `wx_texcheck.py`); R8 superseded, its bands added to skill_lint | done (rulebook 1.8: R8 rewritten as a share of the bar, R8c at 1:1 in `scripts/weathering/wx_texcheck.py`, the Ts in R3, the rails in R10, the metal in R7; the old R8 bands are in `scripts/skill_lint.py`) |
| 9 | `surf_id` AOV from the kit, with discontinuity IDs as its check | parked (surfaces come from the capture depth: `scripts/weathering/weather_fields.py` `surfaces()` splits the paint at 3 cm steps; a kit AOV waits for the kit capture of row 1) |
| 10 | Five independent fields per noise call in the peeling, wear and damage layers, assigned by colouring the surface graph | done (`scripts/weathering/weather_fields.py`: `surfaces()` and `surf_field()` give the paint failure a field per surface colour; breaks clipped to their surface, spall risk per surface, `arrises()` for breaks and edge wear; rule P4. Soiling and growth stay continuous across steps, parked with row 14) |
| 11 | Per-ID upsampling, local opacity, salts and offsets in `wx_hires.py` | done (`scripts/weathering/wx_hires.py` `fine_surfaces`, per-surface offsets SURF_OFF, per-panel flake offsets) |
| 12 | Groove zones from the capture depth, coverage kept per 50 px/m cell; lip-chip band tile; floor crack, flake strips and bleed dirt | done (`scripts/weathering/wx_hires.py` `groove_zones` and `groove_floor`: lips chipped by wear and the flaking around, a crack along the joint by years since repaint, dirt in the floor; rule N6. Flake strips along the floor not drawn: the floor fails by the crack) |
| 13 | Engine: depth shear of the facade projection for reveal details; joint trim lips and floor | parked (engine: the depth shear of the facade projection and the joint trim's lips and floor; revisit at the first engine round trip) |
| 14 | A back mask layer per front for surfaces hidden in elevation, at 25 px/m, and the budget re-checked | parked (a back mask layer for walls hidden in elevation, which also carries soiling and growth per surface; revisit with the member export of row 6, since both change the export's layout) |
| 15 | Rules P4 and N6 in the rulebook and gate | done (rulebook 1.8 P4 in `scripts/weathering/gate_rk.py`, N6 in `scripts/weathering/wx_texcheck.py`) |
| 16 | large-scale-texturing traps: thin members need member space; elevation noise crosses depth steps; projected masks give hidden surfaces the occluder's values | done (`.claude/skills/large-scale-texturing/SKILL.md` traps: thin members need their own space, elevation noise crosses depth steps, occlusion lines are not arrises, projected masks give hidden surfaces the occluder's values) |
