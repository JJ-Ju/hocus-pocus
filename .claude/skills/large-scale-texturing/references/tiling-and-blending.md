# Tiling, blending and scatter: the algorithms

Distilled from `docs/redesign/research/tiling-and-distribution-algorithms.md` (formulas, tested
numpy, sources) and `scripts/weathering/wx_detail.py` (what the danchi pipeline uses).

## Making tiles

- **Spectral synthesis** makes stochastic tiles that tile exactly: inverse FFT of white noise shaped
  by `(1 + (2π k ℓ)²)^(−β/4)`, with correlation lengths ℓy, ℓx (anisotropic for rivulets: ℓy ≫ ℓx).
- **Splats**: discs with power-law radii, convolved circularly (seamless); thin them by a cluster
  field for colonies (Thomas-like clustering).
- **Equalise** every detail a mask will be revealed against (rank to a uniform histogram), and keep
  its Gaussian twin `g = Φ⁻¹(u)` for blending.
- **Mips of a reveal detail are re-standardised** per level, or coverage drifts (a 10 % layer shows
  2 % by mip 2). Appearance maps (albedo, relief) are box-filtered as usual.

## Sampling without repetition

| Content | Method | Cost |
|---|---|---|
| Stochastic (coat, grime, biofilm, rust bloom) | hex tiling: triangle grid, three vertices with hashed offsets and rotations | 3 fetches |
| Same, when a threshold must stay exact | histogram-preserving: blend the Gaussian twins with `Σ wᵢ gᵢ / √Σ wᵢ²`, map back with Φ | 3 fetches + Φ |
| Colour with structure | Mikkelsen's weights `(0.4 + 0.6 lum) wᵢ⁷`, plus a gain | 3 fetches |
| Directional (rivulets, laps) | offset per vertical band, blended across bands only, flip but never rotate | 2 fetches |
| Structured (formwork, stone, tiles) | random offset per real panel, seams under the real joints | 1 fetch |

- **The triangle grid** (Heitz and Neyret 2018): skew `s = (x - 0.57735 y, 1.15470 y)`, `b = floor(s)`,
  `f = s - b`, `z = 1 - f.x - f.y`. Lower triangle (`z > 0`): weights `(z, f.y, f.x)` for `b`, `b + (0,1)`,
  `b + (1,0)`. Upper: `(-z, 1 - f.y, 1 - f.x)` for `b + (1,1)`, `b + (1,0)`, `b + (0,1)`. Unit-test that
  each vertex's weight is continuous along a finely sampled line; a swapped pair shows as lattice seams.
- Use **integer hashes** (PCG-style) of the lattice vertex, identical in numpy, HLSL and GLSL; a
  `frac(sin())` hash differs between GPUs.
- Pass the continuous uv's derivatives (rotated like the uv) to `SampleGrad`, or each cell seam
  takes a coarse mip.
- **Lighting**: blend slopes (or normals as derivatives), each rotated back with its sample's
  rotation; never derive a normal from blended heights (the weights' kinks crease along every
  triangle edge).
- Cell size: about a third of the tile or less; the hex lattice must not match a building rhythm.

## Masks to crisp edges

- Upsample masks with a **cubic B-spline** (four bilinear fetches from a 16-bit texture): no
  bilinear diamonds. Geometric edges (a window, a slab) use a signed-distance mask instead.
- **Edge rule** (coverage kept, zero stays zero): see the skill. Its `pk` is the layer's local
  opacity, a smoothed maximum over about 10 cm, so mask grain does not become specks.
- **Films** are modulated, mean kept: `a · max(1 + k g, 0)`.
- **Distance fade**: past about 25 m use the mask alone (`fd`), so far views keep the tuned amounts
  and mips do not shimmer.
- Mask each layer to its own surfaces at the fine grid (walls, steel), upsampling over that support
  only (normalised), or it bleeds onto frames and glass.

## Scatter (stamps and decals)

- From a mask amount `m` and mean stamp area `E[A]`, a Boolean model needs
  `λ = −ln(1 − m) / E[A]` per m² (the naive `m / E[A]` falls about 15 % short); ×1.1 for clustered
  (Thomas) placement. Sizes from a power law; orientation along the flow.
- Runs and rust streaks: trace the water path, split it into falling runs, chain overlapping decals
  (head, body, tail), about one per 1-1.5 m.

## Tests

- **Repetition**: the correlation coefficient of the high-passed luminance at each tile period, minus
  the median of its ring at that radius. Plain wrapped tiles score about 0.98; hex-tiled or untiled
  detail about 0.00-0.03. Pass ≤ 0.15. (A raw autocorrelation-peak ratio is too noisy: plain noise
  scores 2.)
- **Amounts kept**: box-filter the fine composite back to the mask density and compare.
- **Zero stays zero**: count fine pixels with a layer where its mask is 0 (must be none).
