# Grid breakup in the weathering generator: research note (round G)

Reviewer's note on the soiling film: "Some of the macro patterning/noise might be forming a
slight grid effect on the right side." The crop under review was N_front_mid (x 1500–2400,
y 700–1200) at grime 0.3, 0.4 and 0.5 (`roundF/real/S65f_grime_*`).

Tags: **[S]** a source states it (linked, fetched this session). **[S/2]** a secondary source
states it (encyclopedia, or a paper cited by another paper). **[S\*]** a primary source I know
but could not fetch this session. The web-search budget for the turn was already used up, and
some sites refused the fetcher. Treat [S\*] claims as unverified. **[I]** my inference, or my
experiment (script under `roundG/research/exp/`).

---

## 0. Verdict in one paragraph

The grid in the grime is mostly **not** the noise. It is the **3.6 m material tile**. The
roller-lap and scaffold-lift lines (`spraymacro_lap.png`) and the coat patches and seams
(`spraymacro_mask.png`) are printed one-to-one into the soiling through the J2 material
response. They repeat exactly every 180 px on both axes, a period unrelated to the 2.8 m storeys
or the 6 m bays.

Three measurements show it [I]:
- The weathering makes the lap lines about 4–9× more visible. In the clean base they are
  0.4–0.7 % darker than the wall beside them; after weathering at grime 0.3 / 0.4 / 0.5 they
  are 2.5 / 3.2 / 3.8 % darker.
- A periodicity detector scores the tile's harmonics at 12.8 in the soiling layer. Tile-free
  controls score 4.0–7.9.
- Regressing the two tile maps out of the soiling layer drops the score to 4.7.

Two more effects make it read as a grid [I]:
- **Storeys repeat.** Several random fields are much taller than a storey, and two 1D profiles
  along x are shared by every floor. Adjacent storeys therefore correlate at r ≈ 0.20–0.34 at
  the same x, so blotches line up in columns across the floor bands.
- **The `gfield` bilinear lattice is real but latent.** All of a field's curvature sits on the
  node lines. The S1–S3 lattices even coincide around x ≈ 1930–2170, the right half of the
  review crop. But the lattice carries only −63 dB of the field's power. No lattice locking is
  measurable in the composite, because the finer octaves mask it.

Fix the tile first, de-correlate the storeys second, then swap `gfield`'s upsampling (same
cost, tested). Gate all three with the rule in §5.

---

## 1. Diagnosis (part B): where a grid comes from in our code

### 1.1 Main cause: the 3.6 m material tile printed into the dirt (J2)

**Code path**

- `weather_fields.py:97-111` `material_map()` tiles a PNG by modulo indexing
  (`t[(arange(H) % th), (arange(W) % tw)]`). The tile is box-resized to `round(3.6 * ppm)` =
  180 px.
- `PlaneFields` (`:186-196`) builds `F.mat = 0.75 + 0.35*coat + 0.25*lap` from
  `spraymacro_mask.png` R (coat) and `spraymacro_lap.png` (laps). On concrete it adds
  `formed_mask.png` seam bands and voids.
- `soiling_field` (`:837-842`) multiplies the film tone by `F.matresp`. It also feeds the same
  map into the pattern through `zm`.

Line numbers are for `weather_fields.py` as it stands after 12:23 today. Another session
inserted about 144 lines above `layer_stains` while I worked. The soiling logic is unchanged,
and all measurements use the round-F outputs.

**What the tile contains** [I]

Rendered as the weathering samples it (`exp/out/tile_lap_tiled.png`, `tile_coat_tiled.png`):

- Lap tile: vertical roller-lap lines at irregular x within the tile, so the set repeats every
  3.6 m. Horizontal scaffold-lift lines every 1.8 m.
- Coat tile: faint seam lines about 0.9 m apart, plus two "patch" rectangles per tile (coat
  0.45). The rectangles form a 3.6 m lattice of rectangles over every wall.

**Measured on N_front at grime 0.5** [I] (`e8`, `e9`, `e4`, `e15`):

| measure | value |
|---|---|
| soiling layer on lap lines vs 3–6 px beside them | +7.3 % (whole wall); +7–10 % in the review crop |
| luminance of lap lines vs beside: clean base | −0.4 … −0.7 % |
| luminance of lap lines vs beside: weathered, grime 0.3 / 0.4 / 0.5 | −2.5 / −3.2 / −3.8 % (mean of crop halves) |
| coat-patch rectangles (3.8 % of the wall) in the soiling | −2.8 % (less dirt), repeating every 3.6 m |
| top peaks of the per-column \|∂²x\| periodogram of the soiling | 15.0, 22.6, 9.0, 44.5 px = 180/12, /8, /20, /4 |
| harmonic-sum detector (§5), soiling, x axis | 45 px: 12.8, 22.6 px: 10.6, 90 px: 7.3 (tile family) |
| after regressing lap and coat out of the soiling | top accidental 4.7. The fit explains only 0.8 % of the variance but carries the lines |
| tile-free controls under the same wall mask (full-res noise; current `gfield` noise) | 4.0–7.9 |

The line contrast is about the same in the left and right halves of the crop (−3.9 % vs
−3.65 %). The tile is therefore across the whole wall, not only on the right.

It is dirt-follows-material done literally. The material map is a **tiling** texture, so the
dirt inherits the tile's layout. That is the opposite of what a unique baked layer is for.
Professionals use the unique or macro layer to hide a tile's repetition, never to trace it (§2).

The concrete formwork mask has seams every 0.9 m in the 3.6 m tile. A real formwork grid is
legitimate, but it should be registered to the wall's pour joints and ends, not to an arbitrary
tile origin [I].

### 1.2 Contributing: storeys repeat at the same x (the "plaid")

**Code** (`weather_fields.py`)

| field | line | shape | correlation at one storey (2.8 m) [I] |
|---|---|---|---|
| `cols` | `:143` | aniso (20, 1), σy = 24 m | ≈ 1.0 |
| `mid` | `:160` | aniso (4, 1); S4 σy = 4 m | 0.88 |
| `mid` | `:160` | S5 σy = 2 m | 0.61 |
| `biopatt` | `:156` | aniso (4, 1) | 0.61 at S5 |
| `warp` | `:178` | aniso (4, 1), σy = 6 m | 0.95 |

The correlation of blurred white noise at lag d is exp(−d²/4σy²) [I].

Two 1D profiles along x are shared by every floor:
- **`ut_mod`** (`:816-818`). The under-top dirt of every slab top is modulated by the same
  x-profile.
- **`lam`** in `sources_along_tops` (`:495`). The streak and stain source density along every
  top edge is the same x-profile on every floor.

**Measured** [I] (`e7`, `e10`), on the 0.1–2 m band of the soiling layer. The control shifts x
by 0.75–2.25 m and gives r ≈ 0.

| region | adjacent-storey r at the same x |
|---|---|
| review crop, left / right | 0.25 / 0.20 |
| x 400–1200 | 0.31 |
| x 2900–3700 | 0.34 |
| whole plane | 0.26 |

On x-profiles: soiling 0.12–0.19 between adjacent storeys; streaks 0.26–0.53.

Part of this is legitimate: windows and sills sit at the same x on every floor. Part comes from
random fields running through the slabs. Physically that is wrong: water drips off each slab
and the run-off restarts, so `flow_accum` already resets there. The fields should reset with it.

### 1.3 Latent: the `gfield` bilinear lattice (what was asked about)

**Code** (`wx_noise.py:37-57`)
- `f = min(sy, sx) // 5`, so S1..S5 at 50 px/m use f = 80, 40, 20, 10, 5.
- The coarse grid has H//f + 3 rows. It is blurred at 5 coarse cells, then upsampled by
  `resize` (`:18-34`, bilinear) to H + 2f, and cropped by f.
- Node positions depend only on (plane shape, f), never on the key. **Every field at the same
  octave on a plane shares the same node lines.**
- Node spacing on a 1814 × 4096 plane [I]:
  - x: 78.81, 39.77, 19.98, 9.99, 4.995 px
  - y: 78.96, 39.46, 19.94, 9.97, 4.997 px
- These are near-harmonic (lacunarity exactly 2), so the octaves' lines drift in and out of
  register. S1, S2 and S3 node columns fall within 2 px of each other at x ≈ 1929, 2008, 2087
  and 2166: the right half of the review crop [I].

**What bilinear does** [I] (`e1`). Bilinear is linear along axis-parallel lines [S/2]. So
∂²/∂x² of the upsampled field is exactly zero between node columns, and all of the field's
curvature sits on the lattice.

| method (same coarse grid) | lattice-locking LI (1 = none) | field power at 1/spacing, S1 / S3 | ∂²x power at 1/spacing, S1 / S3 | ms / field |
|---|---|---|---|---|
| bilinear (current) | ∞ (every ∂²x on node columns) | −63 / −91 dB | −21 / −39 dB | 160–245 |
| Catmull-Rom bicubic | 1.05–1.23 | −89 / −126 dB | −31 / −63 dB | 150–240 |
| cubic B-spline | 0.93–1.05 | −95 / −140 dB | −67 / −107 dB | 150–310 |
| bilinear + 0.6 f box-Gaussian post-blur | 0.92–1.04 | −95 / −134 dB | −49 / −71 dB | 840–1070 |
| full-res white noise + `gauss()` (reference, no lattice) | 0.94–1.02 | −81 / −117 dB | −34 / −57 dB | 790–1240 |

Notes on reading the table:
- "Field power" is the share of the field's total power in the 3 bins at 1/node-spacing.
- At S1–S3, bilinear's ∂²x energy at the lattice frequency is **13–19 dB above the lattice-free
  reference**.
- In the field itself it is −63 dB: about 0.07 % of the amplitude.
- Catmull-Rom is not enough: its second derivative still jumps at the nodes.

**Why it is latent, not the cause**
- In the reviewed composite, folding |∂²| by each lattice's exact phase shows no locking [I]
  (`e6`). Over the whole plane, bin-0 / median is 0.95–1.05 with |z| < 2 for f = 80, 40, 20
  and 10, in x and y. Over x 1800–2400 it is 0.95–1.13 with |z| < 2; the one high value is the
  floor rhythm aliasing onto f = 20 (140 ≈ 7 × 19.94). The S6–S8 grain dominates the
  curvature.
- It will show wherever a derivative is taken: normals or height derived from dirt, curvature
  masks, narrow-threshold masks whose contours kink on the lattice. Perlin replaced his
  interpolant because this same second-derivative discontinuity showed as artifacts in bump
  mapping [S: GPU Gems ch. 5].
- It will also show if the fine grain is turned down. And linear interpolation of luminance is
  the textbook cause of Mach bands [S/2: Gouraud shading; Mach bands].

### 1.4 Also found: plane borders (edge clamp in `gfield`)

The coarse grid has about one cell of margin, and `_box1` pads by replicating edge samples
(`weather_measure.py:29-31`). Near every plane border, the macro octaves therefore carry 2–3×
the variance and are stretched across the border [I] (`e16`, 16 seeds):

| octave | variance, outer 5 % of rows / middle 50 % | columns | \|∂y\|/\|∂x\| in top 5 % (middle) |
|---|---|---|---|
| S1 | 2.78 | 2.41 | 0.74 (1.19) |
| S2 | 2.55 | 2.37 | 0.75 (1.02) |
| S3 | 2.61 | 1.60 | 0.89 (0.97) |
| S4 | 1.85 | 1.29 | 1.02 (0.99) |

This is a frame effect at plane ends, tops and feet. It also biases the A3 "no clean end"
redraws [I].

### 1.5 Ruled out or minor

- **Kernel axis bias.** The separable 3-box blur plus separable upsampling has none measurable.
  With a Hann window, power on the axes over power on the diagonals is 0.89–1.04 for `gfield`,
  against 0.83–1.20 for an exact FFT Gaussian (24 seeds) [I] (`e17`).
  - Without a window the same test reads 3.4–10×. That is the FFT's edge cross, a pitfall for
    the gate (§5.4) [I] (`e16`).
- **The floor and bay rhythm.** The y spectra are dominated by floor harmonics (140, 70, 46.7,
  35, 28 px). That is legitimate, and the rule keeps it (§5.2).
- **Mark placement** (weighted random choice, sources from features). It is a Poisson-like
  process with no lattice.
- **Side finding (not grid).** `gauss()` realizes only σ = √((2r+1)² − 1)/2 per axis, so a
  request for 5 cells gives 5.48 (+9.5 %). A small change to a requested sigma can flip the
  radius: 4.97 → r = 4 → 4.47. Keep this in mind when re-checking C1 band balance after any
  change to `gfield` [I] (`e18`).

---

## 2. How professionals break up grids and repetition (part A)

| technique | what it is, as sources state it | fits our numpy bake? [I] |
|---|---|---|
| **Macro variation layer** | Multiply the tiling albedo by one or more low-frequency maps at large, mutually incommensurate scales, so repeats differ in tone. Standard in Unreal landscape and environment materials [S\*]. | Our baked weathering *is* the macro layer. It must not copy the tile (§1.1). |
| **Texture bombing** | Divide UV space into cells and place an image per cell at a random offset (optionally rotation, scale, choice); check neighbour cells for overlaps; use a priority for order [S: GPU Gems ch. 20]. With few images per cell **the cell grid becomes visible**, so loop several samples per cell. Mip artifacts appear at cell borders, and a Voronoi variant exists [S: same]. | Our stamps already do this from real sources. Never place marks on a lattice. Use several per cell if a cell grid is used. |
| **Per-tile random offset / rotation / flip** | A hash per tile picks an offset or rotation, and tiles are blended at the borders. Cost: 2–4 lookups. Directional content cannot be rotated [S\*: Quilez, *Texture repetition*]. | Fine for isotropic stochastic maps (coat clouding). Not for laps (directional, structured). |
| **Stochastic tiling and blending, histogram-preserving** (Heitz & Neyret 2018) | Triangle grid; each vertex gets a random patch; each point blends 3 patches. Plain linear blending ghosts and loses contrast, so blend in a Gaussianized space preserving mean and variance, then invert. About 20× faster than procedural noise of comparable quality [S: Heitz & Neyret]. Production version: 3 samples plus a small LUT, and only for tileable stochastic or near-stochastic textures [S: Unity / Deliot 2019]. | Good for the coat channel. Wrong for laps, patches and seams, which are structured. |
| **Hex-tiling** (Mikkelsen 2022) | Builds on Heitz–Neyret and Deliot–Heitz with a new blending method that samples the original source texture directly, with no histogram preprocessing. Rotation works best when a normal map's average normal is +Z [S: hextile-demo README]. Hex grid, 3 rotated or offset samples, contrast-preserving weights [S\*: JCGT 11(3)]. | Same scope as stochastic tiling. Also the engine-side answer for the base material (§4, R6). |
| **Wang tiles** | A small set of edge-matched tiles gives non-periodic tilings, and they have been used to generate textures procedurally [S/2: Wikipedia, citing Cohen et al. 2003]. | Not needed for a bake, where we can synthesize unique maps. Useful in the engine. |
| **Offset and rotate each octave; lacunarity ≠ 2** | Shift and rotate the domain between octaves and use lacunarity like 2.01–2.03, so octave lattices never share lines or axes [S\*: Quilez fbm; Musgrave in *Texturing & Modeling*]. Houdini exposes lacunarity, roughness and offset per noise and warns of artifacts near offset 0 [S: Houdini Unified Noise]. | Our octaves are near-harmonic and share node lines (§1.3). Fix with a random sub-cell offset per call (R3). |
| **Lattice-free noise types** | Houdini: Simplex, on a tetrahedral lattice, avoids the grid patterns Perlin noise often shows; Sparse Convolution has no artifacts at grid points [S: Houdini Unified Noise]. The improved Perlin fade 6t⁵−15t⁴+10t³ removes the second-derivative jumps at cell borders [S: GPU Gems ch. 5]. Cubic B-spline reconstruction gives continuous first and second derivatives; linear is the first-degree B-spline [S: GPU Gems 2 ch. 20]. | Same idea as R3: C2 reconstruction (cubic B-spline). |
| **Domain warping** | Evaluate a noise at a point displaced by another noise, f(p + fbm(p)), nested for marbling [S: Book of Shaders ch. 13]. | Use to bend the straight lines of rule-made laps or seams, and to break straight iso-lines of macro tone. |
| **Voronoi / cellular breakup masks** | Worley (1996): distance to the nearest feature point (F1, F2...), one point per cell, computed on the fly [S/2: Wikipedia]. Used as region masks to switch variants per cell [S\*]. | Per-region masks (e.g. repaint patches). Cell centres must be jittered, never a grid. |
| **Incommensurate frequencies** | If a period must stay, make it irrational relative to the others so no short least common multiple exists [S\*: Musgrave]. Ours [I]: 3.6/2.8 = 9/7 (repeats every 9 storeys = 25.2 m); 6/3.6 = 5/3 (every 18 m). Both are short, readable beats. | Applies to any tile left in facade space. |
| **Blue-noise point sampling** | Poisson-disk sampling (all samples ≥ r apart) in O(N), k = 30 candidates. Uniform random clusters, jittered sampling reduces but does not remove clustering, and structured distributions induce anisotropy [S: Bridson 2007]. Regular grids alias; Poisson disk is even but irregular [S/2: Wikipedia Supersampling]. | Use for marks with a physical minimum spacing (fixings, tie holes, patches). Dirt itself clusters, so keep clustered Poisson there. |

**How tool users do it in production.** I could not fetch the Adobe and Epic pages, so
everything here is [S\*] / [I]:

- **Substance Designer.** The Tile Sampler and Tile Generator expose per-instance random
  position, rotation, scale, luminance and mask, so a pattern never sits on its grid. Splatters
  and "Make It Tile" break seams; Directional/Vector/Non-uniform warps bend straight edges.
- **Substance Painter.** Dirt comes from generators driven by baked mesh maps (AO, curvature,
  world position), which follow the geometry. Grunge fills use triplanar projection with a
  random offset or rotation and a seed per layer.
- **Houdini.** See the noise-type and offset notes above [S]. In Copernicus/VOPs the same
  levers (offset, lacunarity, simplex or sparse noise, warps) apply.
- **Unreal.** Artists use landscape and environment macro variation, distance blending,
  world-aligned or triplanar sampling, and texture bombing or stochastic or hex sampling in
  custom nodes.
- **Godot.** These need a custom shader; there is no built-in anti-tiling [I].

The common thread [I]: **structure that the building or the process causes is driven by the
building's metrics** (floors, bays, lifts, pour joints). **Everything random is unique, offset
or rotated per instance, and never shares a lattice with anything else.**

---

## 3. Detecting grid artifacts objectively (part A)

| method | what it sees | pitfalls [I] |
|---|---|---|
| **2D power spectrum peaks** | A lattice puts energy at k = m/P along an axis (lines of energy for line lattices, points for dot lattices). Autocorrelation and power spectrum are a Fourier pair (Wiener–Khinchin) [S/2: Wikipedia Autocorrelation]. | **Window first** (Hann), or use the periodic-plus-smooth decomposition [S\*: Moisan 2011]. Unwindowed, the image border alone creates a strong axis cross (we read 3.4–10× fake axis power). Masked openings imprint the building comb; exclude it (§5.2). |
| **Autocorrelation peaks on the axes** | Peaks at lags P, 2P... reveal periodicities hidden in noise [S/2: Wikipedia Autocorrelation]. | Broad null on short profiles; use a statistic on many lags (harmonic sum, below). |
| **Axis-aligned anisotropy** | Spectral power in ±10° wedges on the axes over the diagonals; Lagae–Dutré use radially averaged spectra and an anisotropy curve for point sets [S\*: Lagae & Dutré 2008]. | Same windowing pitfall. Vertical-by-design layers (run-off) are exempt. |
| **Lattice-aligned derivative discontinuities** | Fold \|∂²\| by the suspected lattice's exact phase (non-integer spacing). Curvature locked to node lines gives LI ≫ 1. This is the signature Perlin removed [S: GPU Gems ch. 5]. | Fine content in a composite masks it (§1.3), so test the generators, not only the output. |
| **Synchronous averaging (fold by P)** | Share of variance that repeats exactly with period P. | Biased at integer P on pixel grids: smooth lattice-free fields gave spurious peaks of hundreds at integer P (`e14`). Prefer the periodogram harmonic sum. |
| **Harmonic sum on an edge-energy profile** (used in §5) | A periodic set of thin lines gives a comb of harmonics. Summing the median-normalized periodogram over K harmonics catches line lattices that no single bin shows. | Run per layer: the composite D masks the tile (12.8 in the soiling layer, 5.2 in D). Run per 10 m window if locality matters. |

---

## 4. Ranked recommendations for the numpy generator

Ranked by visible benefit per unit of cost. "Measured" numbers are round F, N_front, grime 0.5.

### R1. Stop the material tile printing into the dirt (fixes the visible grid). Cost: low

- **What it fixes.** The 3.6 m line lattice and the patch lattice (§1.1): detector 12.8 → about
  4.7 when the tile is regressed out.
- **How.** Split the material map by kind.
  1. **Structured features** (laps, lifts, patches, formwork seams): make them by rule per
     plane, from the building's metrics. Real painting goes lift by lift, so vertical laps are
     staggered per lift and never continue across one [I]. Lifts are registered to the ground,
     and formwork seams to pour joints and wall ends. Patches by Poisson disk.
  2. **Stochastic coat strength:** sample the tile with per-plane tiling-and-blending (below)
     instead of modulo.
  3. **Feed the same per-plane maps to the clean base and the weathering**, so J2 still holds.

```python
def lap_lines(shape, ppm, ground_row, key, lift_m=1.8, drop_m=(0.7, 1.3), w_px=1.5):
    """Horizontal lap at every scaffold lift (registered to the ground), vertical laps at
    jittered spacing, independent per lift (staggered: no line runs through two lifts)."""
    H, W = shape
    r = nz.rng(*key)
    lap = np.zeros(shape, np.float32)
    step = int(round(lift_m * ppm))
    for y in range(int(ground_row), -1, -step):
        lap[max(0, y - 1):y + 1] = 1.0
        x = r.uniform(0.0, drop_m[1]) * ppm
        while x < W:
            lap[max(0, y - step):y, int(x):int(x) + 2] = 1.0
            x += r.uniform(*drop_m) * ppm
    # optional: bend the lines a little by domain-warping the row/column index before drawing
    return wm.gauss(lap, w_px)
```

```python
def tile_and_blend(t, shape, key, cell_px):
    """Per-plane stochastic sampling of a tileable *stochastic* map t (e.g. coat strength):
    triangle grid (basis (1, 0), (1/2, sqrt(3)/2), cell_px per edge), a random patch offset per
    vertex, variance-preserving blend of the 3 lookups (after Heitz & Neyret 2018 / Deliot &
    Heitz 2019). Process in row blocks on 4096-wide planes (about 10 full-size temporaries)."""
    H, W = shape
    th, tw = t.shape
    seed = int(nz.rng(*key).integers(1 << 30))               # keyed, stable across runs
    y, x = np.mgrid[0:H, 0:W].astype(np.float64) / cell_px
    s, u = x - 0.57735027 * y, 1.15470054 * y                 # skewed (lattice) coordinates
    i, j = np.floor(s).astype(np.int64), np.floor(u).astype(np.int64)
    fx, fy = s - i, u - j
    up = (fx + fy) > 1.0                                      # upper triangle of the skewed cell
    verts = [(i + up, j + up), (i + 1, j), (i, j + 1)]
    w = [np.where(up, fx + fy - 1.0, 1.0 - fx - fy), np.where(up, 1.0 - fy, fx), np.where(up, 1.0 - fx, fy)]
    mu = t.mean()
    acc = np.zeros(shape)
    for (vi, vj), wk in zip(verts, w):
        h = ((vi * 73856093) ^ (vj * 19349663) ^ seed) & 0x7FFFFFFF     # hash per lattice vertex
        oy, ox = h % th, (h // th) % tw                                  # its random patch offset
        acc += wk * (t[(np.arange(H)[:, None] + oy) % th, (np.arange(W)[None, :] + ox) % tw] - mu)
    return mu + acc / np.sqrt(w[0] ** 2 + w[1] ** 2 + w[2] ** 2)
```

The triangle-grid geometry and the weights above are derived here [I]. The mean- and
variance-preserving blend is the Gaussian case of Heitz & Neyret [S]. For a strongly
non-Gaussian map, add their histogram transform; the published listing is in Deliot & Heitz
[S\*].

Tested on the coat tile, 900 × 1800 px, cell 180 px [I] (`e19`, `out/e19_*.png`):

| | mean / std | 180 × 180 repeat share | controls |
|---|---|---|---|
| tile (reference) | 0.5301 / 0.0457 | — | — |
| tiled as now | 0.5301 / 0.0457 | 1.000 | 0.03–0.12 |
| blended | 0.5301 / 0.0458 | 0.033 | 0.021–0.031 |

As the sources predict, the tile's structured content does not survive blending. The patch
rectangles come out as ghosted, partly faded copies, and the coat tile's faint 0.9 m seam lines
come out as fragments. Take the patches out of the stochastic map and place them by rule
(Poisson disk). Remove the seams from the source tile; they look like a round-E generation
artifact [I]. A simpler alternative that is fine for a bake is to **re-synthesize the coat
field with `fbm` per plane**, matched to the tile's band energies.

### R2. Let the pattern restart at every drip edge (fixes the plaid). Cost: low

- **What it fixes.** Storey-to-storey repetition of 0.1–2 m blotches (r ≈ 0.20–0.34) and
  streak-source columns (r ≈ 0.43–0.53 between adjacent storeys).
- **How**, three small edits:
  1. **One profile per edge, not per plane.** `sources_along_tops` (`:495`):

     ```python
     lam = np.empty(xs.size)
     for y in np.unique(ys):
         s = ys == y
         g = nz.gfield((1, W), 0.6 * ppm, key + ("gap", int(y)))[0]
         lam[s] = np.exp(gap_sigma * g[xs[s]] - gap_sigma ** 2 / 2)
     p = density_per_m / ppm * lam          # was: ... * lam[xs]
     ```

     `soiling_field` `ut_mod` (`:816`): make it 2D, short vertically (independent per storey):

     ```python
     ut_mod = np.exp(0.7 * nz.fbm(sh, plane["ppm"], [5, 6, 7], F.key + ("utmod",), aniso=(0.5, 1.0)))
     ut_mod = (ut_mod / ut_mod.mean()) * F.acctex
     ```

  2. **Fields carrying 0.1–2 m pattern restart per storey.** This covers `mid`, `inner`,
     `biopatt`, `warp`, `chan` and the dust textures. Draw them per storey band (key + storey
     index) with a margin, and crossfade over about 0.1 m below each `floor_rows` / `flow_start`
     row. Alternatively, cap σy at ≤ 0.39 × storey pitch (≈ 1.1 m), which keeps one-storey
     correlation ≤ 0.2. Keep S1–S3 (`C`, `macro`) continuous: whole-wall exposure really is
     continuous.
  3. **Tie `cols` to the building.** Use one random factor per bay, smoothed across each
     bay's width, instead of free 1.2 m-wide stripes 24 m tall that cut through windows. A
     dirtier bay is a building-rhythm effect (legitimate); a random stripe through the slabs is
     not.

### R3. Replace `gfield`'s upsampling (fixes the latent lattice and the frame). Cost: none

- **What it fixes.**
  - The curvature lattice: LI ∞ → 1.03–1.07.
  - Shared and coinciding node lines across fields and octaves.
  - Border variance: 1.5–4.0× → 1.0–1.3× (8 seeds).
- **Cost.** Time per call is equal (224–405 ms vs 300–376 ms, 1814 × 4096) [I] (`e18`).
- **How.** Three changes, prototyped and tested in `exp/e18_gfield_v2.py` (about 25 lines):
  1. **Margin.** The coarse grid extends at least 3 coarse sigmas (plus 3 cells) past every
     edge, so edge replication never reaches the plane.
  2. **Offset.** A keyed random sub-cell offset per call.
  3. **Cubic B-spline.** Separable cubic B-spline lookup (4 + 4 gathers) instead of `resize`.
     Keep the same coarse sigma: the B-spline adds only f/√3 (+0.7 % at σ = 5f), and
     correcting for it can flip `gauss()`'s box radius (§1.5).
- **Check after.** Band powers match within ±1 dB at S4–S5. At S1–S3 they differ by up to
  ±4 dB, partly because the old field's border excess is gone. Re-run the C1 band-balance
  check and the macro calibration after adopting it.
- **Not recommended.** Catmull-Rom (LI 1.05–1.23: still kinks in ∂²). A post-blur (works, but
  4–5× the cost).

### R4. Optional polish. Cost: low to moderate

- Domain-warp the macro tone slightly, by about 2–5 % of its scale, to bend straight
  iso-contours [S: Book of Shaders].
- Random rotation of isotropic fields is **not needed**. Axis bias is within noise after R3
  (§1.5), and rotation costs 16 gathers per field.
- If any tile must stay in facade space, give it a period incommensurate with storey and bay
  (§2) and offset it per plane.

### R5. Mark placement: keep it, with one rule. Cost: none

Dirt clusters, so the current weighted-random and cascade sources are right. Use blue noise
(Bridson) only where physics sets a minimum spacing: fixings, tie holes, chips along an arris,
patches. Never place marks on a lattice or on cell centres without jitter [S: GPU Gems ch. 20;
Bridson].

### R6. Engine side: out of numpy scope, but related

The base materials tile at 3.6 m in Unreal or Godot. Their stochastic channels can use hex or
stochastic sampling, plus a macro multiply at two incommensurate world scales. Structured,
directional features (laps) must not be rotated, so bake those per plane [S: Unity / Deliot;
hextile-demo; I].

---

## 5. Proposed measurable rule: G "no accidental lattice"

Three measures. G-1 is the gate on the output, G-2 is a generator rule plus an output
diagnostic, and G-3 is a unit test on the noise. All three run in seconds per plane.

### 5.1 G-1 Accidental periodic lines, per layer and per axis (gate)

**Measure** [I] (`e15_harmonic_detector.py`). Run on the painted wall of each layer map L_x
(soiling, stains, streaks, base, bio) and on D.

1. **Edge-energy profile.** Per column, take the mean of |∂L/∂x| over the wall rows (clip at
   the 99.5th percentile, interpolate gaps). Do the same per row for |∂L/∂y|.
2. **Detrend.** High-pass with a 300 px (6 m) Gaussian and apply a Hann window.
3. **Normalize.** Divide the periodogram by its running median over ±(15 % + 3) bins, giving
   Sn ≈ 1 off-peak.
4. **Harmonic sum.** For P from 16 to 600 px (log-spaced):
   HS(P)/K = mean over the first K = 8 harmonics (period ≥ 6 px) of max Sn in the ±1-bin
   window, using only **non-building** bins.

**Pass band:** max HS/K ≤ **9** on every layer and axis.

| case | HS/K | result |
|---|---|---|
| tile-free controls under the same mask (full-res and current-`gfield` noise, x and y) | 4.0–7.9 | pass |
| round F as built, soiling, x (45 px) | 12.8 | fail |
| with the tile regressed out | 4.7 | pass |

Calibrate per building: score about 20 tile-free draws under each plane's mask and set the
threshold at their maximum + 1. **Report** the top 3 accidental periods with their scores, so
the cause can be found (180 px harmonics → the tile).

**Local variant (recommended).** Run the same measure in 10 m windows sliding by 5 m, with a
threshold of 10. This catches "on the right side" cases. The composite averages over the whole
wall, and D alone scores the tile at only 5.2, because streaks and stains mask it.

### 5.2 Telling the building's rhythm from accidental lattices

Mark as **building** (excluded from G-1, reported separately, allowed) all bins within ±1 of
every harmonic of:

- **Floor pitch:** median diff of `floor_rows` (140 px). Also twice it (280 px: skip-floor
  access corridors and alternating storeys are real).
- **Bay pitch:** median diff of `bay_cols` (300 px on the fronts, 105 px on the gable).
- **The plane's own feature comb.** Run the same spectrum on the clean feature map (wall mask,
  or `cls` edges: openings, cores, joints, downpipes). Every peak above 8× background is
  building. This covers cores, odd end bays and joints without hand-made lists.
- **Modelled scaffold lifts.** If lifts are modelled (R1), the lift pitch too.

A frequency that is both building and accidental cannot be told apart and is excluded. For
example, 15 px = 300/20 = 180/12. The harmonic sum still catches the tile through its other
harmonics: 45, 22.5, 11.25 and 9 px. A lattice that matches the building to the pixel (same
pitch, same phase) is indistinguishable by spectrum. Avoid it by construction: random offsets
(R3), and no tiles in facade space (R1).

### 5.3 G-2 Storeys don't repeat by accident

**Generator rule (unit test).** Every random 2D field carrying pattern below S3 (scale < 4 m)
must have a vertical autocorrelation at a lag of one storey pitch ≤ **0.2**. That means
σy ≤ 0.39 × pitch. The exceptions are fields that are restarted per storey or explicitly tied
to sources. Today `mid` S4/S5 give 0.88/0.61, `warp` 0.95 and `cols` ≈ 1.0: all fail.

**Output diagnostic.** Take the adjacent-storey correlation of the soiling's 0.1–2 m band at
the same x, minus the x-shifted control (0.75–2.25 m), measured as in `e10`.

- **Now:** 0.20–0.34, 0.26 for the whole plane.
- **Calibrate:** build the plane once with the pattern contrast k = 0 and every random field
  constant. The r that remains is what the features (windows, sills, shelter) explain:
  r_features.
- **Pass:** r − r_features ≤ **0.10**. This is provisional; set it after R2.

### 5.4 G-3 Noise generators are lattice-free (unit test, seconds)

For `gfield` / `fbm` / `lognormal` at every level S1–S8 and every aniso in use, on the real
plane sizes:

| check | pass band | current `gfield` | v2 (R3) |
|---|---|---|---|
| **LI**: \|∂²x\| and \|∂²y\| column/row means folded by the lattice phase (both f and the resize spacing), max bin / median | ≤ 1.10 | ∞ | 1.03–1.07 |
| **Border variance**: outer 5 % rows (and columns) over the middle 50 %, 8 seeds | ≤ 1.3 | 1.5–4.0 | 1.0–1.27 |
| **No shared lattices**: node offsets differ between calls (keyed) | assert | fails | passes |
| **Axis wedge ratio**, Hann-windowed (diagnostic only) | 0.8–1.25 | 0.89–1.04 | — |

---

## 6. Experiments (all under `roundG/research/exp/`, run with `python -I`)

| script | what it showed |
|---|---|
| `e1_upsample_lattice.py` | bilinear vs Catmull-Rom vs B-spline vs post-blur vs full-res: LI, lattice energy in the field and in ∂²x, time (`out/e1_results.txt`) |
| `e2_real_periods.py` | fold shares on N_front: floor rhythm 6.4 % of soiling variance (y, 140 px); 180 px barely above control by variance (thin lines carry little variance) |
| `e3_real_views.py`, `e5_real_d2_view.py` | contrast-stretched crop, \|∂²\| view with lattice ticks, 2D spectrum (`out/N05_*`) |
| `e4_real_lines.py` | \|∂²x\| column-profile peaks at 180 px harmonics |
| `e6_real_phase_scan.py` | no `gfield` lattice locking in the composite (\|z\| < 2) |
| `e7_real_floor_repeat.py`, `e10_halves_structure.py` | storey repeat r; crop halves alike |
| `e8_real_tile_imprint.py`, `e9_crop_halves.py` | lap-line and patch contrast; clean base vs weathered, by grime |
| `e11_period_scan.py`, `e12_remove_tile.py`, `e14_scan_octaves.py` | fold scan: same tile family flagged, but biased at integer P on smooth fields (do not use for the gate) |
| `e15_harmonic_detector.py` | the G-1 measure; real layers, tile removed, two lattice-free controls (`out/e15_results.txt`) |
| `e16_edges_aniso.py`, `e17_axis_bias.py` | border variance excess; axis bias windowed (none) vs unwindowed (FFT cross) |
| `e18_gfield_v2.py` | the R3 prototype: LI, border variance, band match, time (`out/e18_results.txt`) |
| `e19_tile_blend_check.py` | the R1 tile-and-blend sketch on the coat tile: statistics kept, 180 px repeat gone, patches ghost |
| `pdf_text.py` | text extraction from a downloaded PDF (Bridson), data only |

The generator's files were read and imported only. Nothing outside `roundG/research` was
written.

---

## 7. Sources

**Fetched this session**

- [S] GPU Gems ch. 20, *Texture Bombing* (R. S. Glanville):
  https://developer.nvidia.com/gpugems/gpugems/part-iii-materials/chapter-20-texture-bombing.
  "places small images at irregular intervals". Covers the cell grid, per-cell random
  parameters, several images per cell to hide the grid, priorities, the Voronoi variant and
  mip artifacts at cell borders.
- [S] E. Heitz, F. Neyret, *High-Performance By-Example Noise using a Histogram-Preserving
  Blending Operator*, HPG 2018: https://eheitzresearch.wordpress.com/722-2/. "blending
  operation that usually produces visual artifacts such as ghosting". Covers the triangle grid,
  3 patches, mean and variance preservation, Gaussianization, stochastic inputs and about 20×
  speed.
- [S] T. Deliot (Unity Labs), *Procedural Stochastic Texturing in Unity*, 2019:
  https://unity.com/blog/technology/procedural-stochastic-texturing-in-unity. "only compatible
  with tileable stochastic and near-stochastic textures". 3 samples plus a LUT.
- [S] M. Mikkelsen, hextile-demo README (demonstrates *Practical Real-Time Hex-Tiling*, JCGT):
  https://github.com/mmikk/hextile-demo. "a novel blending method which allows us to sample the
  original source texture".
- [S] K. Perlin, GPU Gems ch. 5, *Implementing Improved Perlin Noise*:
  https://developer.nvidia.com/gpugems/gpugems/part-i-natural-effects/chapter-5-implementing-improved-perlin-noise.
  "This causes artifacts to show up when Noise is used in bump mapping." Covers 3t²−2t³ →
  6t⁵−15t⁴+10t³ and gradient clumping.
- [S] C. Sigg, M. Hadwiger, GPU Gems 2 ch. 20, *Fast Third-Order Texture Filtering*:
  https://developer.nvidia.com/gpugems/gpugems2/part-iii-high-quality-rendering/chapter-20-fast-third-order-texture-filtering.
  Linear filtering is the first-degree B-spline; the cubic B-spline gives continuous first and
  second derivatives; bicubic in 4 bilinear fetches.
- [S] SideFX, Houdini *Unified Noise* VOP:
  https://www.sidefx.com/docs/houdini/nodes/vop/unifiednoise.html. "can avoid the grid
  patterns often visible in Perlin noise". Sparse convolution has no grid-point artifacts; an
  offset-0 warning; lacunarity and roughness.
- [S] *The Book of Shaders* ch. 13, fBm: https://thebookofshaders.com/13/. Lacunarity and gain;
  domain warping credited to Quilez, "use fBm to warp a space of a fBm".
- [S] R. Bridson, *Fast Poisson Disk Sampling in Arbitrary Dimensions*, SIGGRAPH 2007 sketch:
  https://www.cs.ubc.ca/~rbridson/docs/bridson-siggraph07-poissondisk.pdf. "generating samples
  from a blue noise distribution is important". O(N), k = 30, clustering and anisotropy of the
  alternatives. Cites Cook 1986 [S/2].
- [S/2] Wikipedia, *Gouraud shading*: https://en.wikipedia.org/wiki/Gouraud_shading. "linear
  interpolation of intensity causes derivative discontinuities which triggers Mach bands".
- [S/2] Wikipedia, *Mach bands*: https://en.wikipedia.org/wiki/Mach_bands. Mach bands appear
  where the luminance derivative is discontinuous.
- [S/2] Wikipedia, *Bilinear interpolation*:
  https://en.wikipedia.org/wiki/Bilinear_interpolation. The interpolant is linear along
  axis-parallel lines.
- [S/2] Wikipedia, *Autocorrelation*: https://en.wikipedia.org/wiki/Autocorrelation.
  "identifying repeating patterns or hidden periodicities within a signal obscured by noise".
  Wiener–Khinchin.
- [S/2] Wikipedia, *Supersampling*: https://en.wikipedia.org/wiki/Supersampling. Grid sampling
  can alias; jittered and Poisson-disk sampling are alternatives.
- [S/2] Wikipedia, *Wang tile*: https://en.wikipedia.org/wiki/Wang_tile. "Wang tiles have been
  used for procedural generation of textures". Cites Cohen et al. 2003.
- [S/2] Wikipedia, *Worley noise*: https://en.wikipedia.org/wiki/Worley_noise. Worley 1996;
  feature points per cell; F1 and F2.

**Not fetched** (search budget exhausted, or the site refused the fetcher), cited from
knowledge [S\*]:

- M. Mikkelsen, *Practical Real-Time Hex-Tiling*, JCGT 11(3), 2022:
  https://jcgt.org/published/0011/03/05/. The page rendered empty to the fetcher.
- I. Quilez, *Texture repetition*, *fBm* and *Domain warping*: iquilezles.org/articles/
  (texturerepetition, fbm, warp). These returned 404 to the fetcher.
- M. Cohen, J. Shade, S. Hiller, O. Deussen, *Wang Tiles for Image and Texture Generation*,
  SIGGRAPH 2003.
- A. Lagae, P. Dutré, *A Comparison of Methods for Generating Poisson Disk Distributions*, CGF
  2008 (radially averaged power spectrum, anisotropy).
- A. Lagae et al., *A Survey of Procedural Noise Functions*, CGF 2010:
  https://www.cs.umd.edu/~zwicker/publications/SurveyProceduralNoise-CGF10.pdf. The fetcher
  rejected its certificate.
- F. K. Musgrave in Ebert et al., *Texturing & Modeling: A Procedural Approach* (lacunarity,
  octave alignment).
- L. Moisan, *Periodic plus smooth image decomposition*, JMIV 2011.
- D. Mitchell, A. Netravali, *Reconstruction Filters in Computer Graphics*, SIGGRAPH 1988
  (anisotropy of separable filters).
- Adobe Substance 3D Designer *Tile Sampler* docs (403 to the fetcher), the Substance Painter
  generator docs, and Epic's Unreal material and landscape docs (macro variation).
