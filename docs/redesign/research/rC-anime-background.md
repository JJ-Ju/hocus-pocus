# Round C: how 1980s–90s anime urban backgrounds were painted, and how to get the look from 3D

The user's direction: the generator stays realistic, or mostly realistic, by default. The
painterly anime-background look is an option layered on top (lookdev switches, a lighting key,
a Copernicus post), never a lowering of realism in the core. This note gathers what the
background painters and today's 3D-to-background pipelines did, and turns it into rules with
numbers. Round C measured the numbers on danchi v3 and v5 renders, before and after the
prototype post (`docs/redesign/evidence/styleC/`).

Tags: **[S]** a source states it, **[S/P]** the artist said it (interview, often translated),
**[S/2]** secondary (a curator, journalist or wiki citing a book), **[I]** inference or
observation, **[C]** measured in round C. Two research passes gathered the sources. Several
pages (RIBA Journal, Gallery Nucleus, world-architects, Pigment Tokyo) returned 403 or 429 and
were read from search snippets only; those facts are marked "snippet". No frames were downloaded;
stills are described, not reproduced.

## 1. How the backgrounds were made

**Medium and boards.**
- Poster colour (Nicker), an opaque gum-arabic gouache, on heavy poster board (Muse TMK) [S,
  manufacturer]. Oga worked with about 21 tubes and mixed the rest; thin coats only [S/P].
- The base coat went down wet in a 30–60 minute window and could not be fixed later (Ghibli's
  Naoya Tanaka on Oga) [S/2].
- Board sizes in exhibition captions: typical *Akira* boards about 25 × 37 cm; pans larger (cut 1
  detail 93 × 53 cm) [S/2]. *Ghost in the Shell* (1995) cut 477: watercolour on paper plus
  acrylic on film, 270 × 390 mm [S/2]. Outlets disagree on the medium labels ("gouache",
  "watercolour", "ink").
- In a 1981 Animage roundtable the painters treat the airbrush as the core tool for skies and
  gradients [S/P].
- *Akira* used about 20 background painters; straight lines and vanishing points were ruled
  [S/2]. *Wings of Honnêamise* used 16 painters under Ogura [S/2].
- A TV episode needs about 180–300 new backgrounds (250–400 cuts, 70–80 % new; Studio Pablo,
  2013) [S]. That is why painters used a fixed vocabulary of marks, not observation of every
  surface [I].

**Backgrounds and cels.** Backgrounds are tonal and carry no outlines. Only the cels carry line,
and the two often clash (Konno, 1981) [S/P]. Damage in *Akira* was added by laying cels over
intact backgrounds [S/2]. *Harmony* (ハーモニー) paints a character in the background's own style
under a traced line cel (Dezaki, Kobayashi) [S/2]. Foreground and middle-ground elements in GITS
sat on separate cels that could shift for parallax [S/2].

**Per artist.**
- **Toshiharu Mizutani (*Akira*, 1988).** The night palette leans on red and green, which gives
  Neo-Tokyo its odd brightness [S/2]. Black was avoided; deep shadow is strong red and blue
  [S/2]. Detail sits in the centre of the frame and thins outward [S/2]. One caption gives window
  sizes of about 3 mm on foreground buildings, 0.5 mm in the middle ground, and a dot beyond
  [S/2, single retailer source, snippet]. The "327 colours" figure in r5-meta is **cel paint**
  (Kimie Yamana), not background paint [S/2]: a correction.
- **Hiromasa Ogura (*Patlabor* 1–2, *GITS*, *Honnêamise*).** Location photographer Haruhiko
  Higami shot in black and white so the photos would not steer the colour [S/2]. Ogura shot his
  own colour photos for the palette [S/2]: mono for structure, colour from memory and his own
  photos. His camera fogged in humid Hong Kong nights, and he painted that bled halo around
  street lights into the boards [S/2]. GITS: the old city warm and subdued, the new city cold
  blue [S/2, snippet]. *Honnêamise*: subdued blue and brown; he found 3 a.m. against 4 a.m. hard
  to show [S/2]. Fine detail layered over areas of wash [S/2].
- **Shichiro Kobayashi (Kobayashi Production; trained Oga and Ogura).** Paint the distance clear,
  without blur, but with less in it: lines break up and details drop out [S/P]. He rejects haze
  and dislikes ambiguity [S/P]. Unify a film around one colour; keep a strong difference between
  sky and ground [S/P]. What is left undrawn carries meaning: light concentrated on the subject,
  the surround darkened [S/P]. Mould texture made by pressing paint on a wet stone and peeling it
  off [S/P].
- **Kazuo Oga (Ghibli; *Pom Poko* is set in Tama New Town, the danchi suburb).** His aim is to
  get the essential point across; he extracts and boosts the key elements, deliberately not
  naturalistic [S/P]. Wet-into-wet base coats give gradients that pass for watercolour [S].
- **Michiyo Yasuda (Ghibli colour design).** Realised in the late 1980s that shadows have colour,
  and put deep or vivid colour in shadow instead of grey or black [S/P].
- **Nizo Yamamoto.** Painted a whole sky with a flat brush, blending with a dry brush [S/2,
  snippet]. "Nizo clouds" are solid-looking cumulus [S].
- **Hiroshi Kato (*Evangelion*, 1995).** Called it the last anime with hand-drawn backgrounds
  [S/P]. Background studio Bihou did several TV episodes [S]. No primary source documents Eva's
  danchi backgrounds; anything about them is observation [I].
- **Layout.** Takashi Watabe's *Patlabor* 1 layouts computed lens distortion [S/2]; Satoshi Kon
  laid out over 100 of *Patlabor 2*'s 872 shots, in telephoto and wide-angle [S/P via AO].

**What stills of the period show** (descriptions, [I], not checked frame by frame):
- *Akira* night: saturated red and green neon against blue-violet darks, no pure black; window
  grids shrink with depth; glows run white core to cyan.
- *Patlabor 2* Tokyo: long static winter wide shots, muted grey-green, compressed long-lens
  skylines.
- *GITS* canal city: wet, low-contrast green-grey; layered signs; mirror water; haloed lamps.
- *Evangelion* suburbs: dense hard-edged poles and wires in silhouette against flat airbrushed
  skies (wire density confirmed by a Gigazine article [S]).
- Concrete walls in daylight read as two or three flat values per plane, with a few vertical
  stain strokes under sills and a thin light line on the lit corner [I].

## 2. How studios reproduce it from 3D today

| Production or source | What they do | Use for us |
|---|---|---|
| *Your Name* (CoMix Wave, 2016) | about 180 CG cuts; 3D layout renders became the base drawings; painted art camera-mapped back onto 3D [S] | 3D is the layout; the paint is a layer on top |
| *Weathering With You* | about 70 cuts from Google Earth as a base; scenes split into "BOOK" depth layers 1–6 for painters [S] | quantise depth into 4–6 planes |
| *Blue Thermal*, *Penguin Highway*, *Jujutsu Kaisen 0* | 3D layout as base layer; camera mapping; Unity layout [S] | same |
| *Shin Evangelion* | about 70 % of cuts 3DCG-based; a 1/45 miniature of Village 3 for previs [S] | — |
| Blue Protocol (CEDEC 2020/21) | PBR materials with **reduced texture detail**, geometry at full detail; the hand-painted feel comes from **filters**: lower colour contrast, no sharpening, shared blur and mosaic for bleed. Shadow colour is the diffuse colour **hue-shifted, not darkened**. Light-to-shadow split 7:3. Lines from depth, ID, normal and hand; darker in proportion to the brightness step; background edges uneven, with breaks [S] | the closest analogue to our post |
| Granblue Fantasy Relink | sky-blue reflection in shadow tones; clouds added last, different per shot [S] | coloured shadows; per-shot sky |
| ufotable | compositing and background barely separated; light makes most of the impression [S] | grade and post are part of the art |
| Mateusz Urbanowicz (ex-CoMix Wave) | footage → a watercolour filter → paintover [S] | — |
| Clip Studio tip 8939 | delete the photo sky, paint a gradient and clouds; repaint plants, sky, trees; man-made objects can stay photographic; shadows to blue, mid to cyan, highlights to yellow [S] | sky replacement; hue split |
| Clip Studio tip 8952 | shadow layer binarised at 100, blue fill 50 %; distance blue Screen 50 %; diffusion = Levels, Gaussian 50, Screen 100 % [S] | haze and diffusion recipes |
| White-box cartoonisation (CVPR 2020) | surface (guided filter r 1, ε 5e-3), structure (SLIC 200 regions; flat colour per region by its std: < 20 mean, 20–40 mean/median, > 40 median), texture (jittered luma) [S, code] | an ID mask can replace the superpixels [I] |
| Blender Kuwahara node | classic or anisotropic, size 1–100; manual examples 3, 6, 9; chaining flattens more [S] | radius ranges |
| Acerola anisotropic Kuwahara | kernel 2–20, 8 sectors, hardness 8, q 8 [S, code] | if we write an OpenCL version |
| Roystan outline shader | Roberts cross, 1 px, depth threshold 1.5, normal threshold 0.4 [S] | line thresholds |
| Gurney | three values, merge similar neighbours, avoid "middle-value mumbles" [S] | value rule |

The studios keep 3D for layout and light and do the "paint" as a separate layer, which is the
switchable structure the user asked for [I]. Nobody published stroke counts for weathering.

## 3. Rules, with numbers

### 3.1 Value

| Rule | Number | Origin |
|---|---|---|
| Values per material plane | 3: lit, shadow (sky-lit), occlusion accent | [S] Gurney three values; [I] per material |
| Band thresholds on irradiance (C ÷ albedo), as fractions of the lit wall | occlusion < 0.12, shadow < 0.55, lit above | [C] v3 hero street: lit 1.15–1.24, sky-lit shadow ~0.25, occluded 0.07–0.12 |
| One value dominates | ≥ 2:1 against the next | [S] r5 T2. [C] the prototype reaches 1.67–1.71; a deep sky drops it to 1.07 |
| Light-to-shadow area on a sunlit frame | about 7:3 | [S] Blue Protocol |
| Share of non-sky pixels within ±4 L\* of the three strongest histogram peaks | ≥ 0.65 | [C] realistic 0.44–0.65, stylised 0.68–0.85 |
| Detail with depth | far planes simpler but still crisp (Kobayashi), or simpler and hazed | [S/P] Kobayashi; [S/2] Akira window sizes |
| Detail placement | concentrated at the subject, thinning outward | [S/2] Akira; [S/P] Kobayashi |

### 3.2 Colour key and shadow colour

| Rule | Number | Origin |
|---|---|---|
| Shadows coloured, never grey | day keys: mean b\* of the darkest quartile ≤ −2 (blue), hue 200–300° | [S/P] Yasuda; [S] Blue Protocol, Clip Studio; [C] realistic +1.4 to +5.6, stylised −3.8 to −12.6 |
| No pure black | L\* 1st percentile ≥ 12 | [S/2] Akira avoided black; [C] realistic 6.6–12.9, stylised 14–34 |
| Hue split | shadows blue, midtones cyan, highlights yellow (day) | [S] Clip Studio 8939 |
| One key colour per film or sequence | — | [S/P] Kobayashi |
| Strong sky against ground | — | [S/P] Kobayashi |
| Mood | sad: less saturation, darker; happy: more saturation and colours | [S] Studio Pablo |
| Palette size | about 21 tubes mixed (Oga) | [S/P] |
| Saturation budget, non-sky | mean C\* 9–12, 95th percentile ≤ 40 on day keys | [C] realistic mean 6.8–7.7; stylised summer 8.7–12.2 |
| Art boards | one per time of day before any background | [S/2] |

Prototype keys (linear RGB multipliers on the flattened albedo) [I, tuned in round C]:

| Preset | Lit | Shadow | Occlusion | Sky zenith / mid / horizon | Saturation | Haze max |
|---|---|---|---|---|---|---|
| `summer_day` (Patlabor 1 summer) | (1.02, 0.98, 0.90) | (0.36, 0.40, 0.52) | (0.16, 0.18, 0.27) | (0.24, 0.44, 0.80) / (0.46, 0.62, 0.86) / (0.74, 0.80, 0.86) | 1.10 | 0.40 |
| `winter_overcast` (Patlabor 2) | (0.80, 0.81, 0.78) | (0.44, 0.47, 0.50) | (0.24, 0.26, 0.29) | (0.48, 0.52, 0.55) / (0.58, 0.61, 0.62) / (0.70, 0.71, 0.70) | 0.78 | 0.65 |
| `dusk` | (1.10, 0.72, 0.46) | (0.26, 0.24, 0.44) | (0.12, 0.11, 0.24) | (0.08, 0.09, 0.30) / (0.46, 0.27, 0.42) / (1.00, 0.58, 0.32) | 1.05 | 0.50 |

### 3.3 Sky

- Replace the rendered sky with a painted one: a 2–3 colour gradient plus drawn clouds [S, Clip
  Studio]. Clouds differ per shot and go in last [S, Granblue].
- Keep the sky in the **light** value group, as a pale cerulean. A deep zenith (0.10, 0.25,
  0.62 linear) put the sky in the mid group and dropped notan dominance from 2.57 to 1.07 on the
  v3 hero street; (0.24, 0.44, 0.80) gave 1.67 [C].
- Cumulus as hard-edged shapes (threshold width 0.003 on a 0–1 noise) with a shaded underside,
  more of them near the horizon, the top clear; open the mask by 4 px so noise islands do not
  read as specks [C].
- Hand gradients vary from pixel to pixel; digital ones are uniform even with noise added [S,
  Studio Pablo]. Add a ±2 % horizontal stroke texture to the gradient [I].
- Overcast: one low-contrast sheet close to the gradient. Contrasty cloud shapes in a grey sky
  read as stains [C].

### 3.4 Edges

- No black outlines on backgrounds [S/P, Konno]; lines are a cel convention.
- Straight edges ruled [S/2].
- Edge highlights: a thin light line on lit convex corners. **No source found**; it is an
  observation of stills [I]. The prototype draws 1 px lines from normal discontinuities, only
  where the lit band is, screened at 0.55 in a warm white [C].
- Silhouettes against farther things: a darker step of the local colour at 25 %, never black
  [I]. Blue Protocol makes lines darker in proportion to the brightness step, with breaks [S].
- Measured: Houdini `edgedetectnormal` output peaks at 0.2–0.36, so stretch 0.05–0.30 to 0–1;
  `edgedetectdepth` at its default tolerance of 0.08 flags 32 % of the v3 street frame (ground
  and trees at 32 spp); 0.25 keeps the silhouettes [C].
- Do not line vegetation facets: the faceted v3 trees got a light line on every facet [C].

### 3.5 Brush and texture

- Poster colour is opaque, applied thin: flat fields with a slight stroke direction, no
  photographic grain [S/P, Oga].
- Remove micro noise with an edge-preserving filter, not a blur. Kuwahara at radius 1.5 then 2.5
  px on albedo at 1280 px. At radius 4 and up it rounds the corners of small rectangles, and
  windows become blobs [C].
- Painted shadow shapes: Kuwahara at radius 3 px on the irradiance. It merges 32-spp speckle
  into shapes [C].
- Hand-cut band edges: displace the band input by about 1 px with a smooth noise field, so shadow
  edges are not ray-traced exact [I, C].
- Replace grain with two designed textures: strokes (elongated noise, ±3.5 %) and a broad wash
  (±4.5 %) [I]. Measured mean local std of L\* at pixel scale: realistic v3 8.6–9.7, stylised
  5.5–6.4 [C].
- Kobayashi's gritty texture and stone-print mould are special effects for a story beat, not a
  default [S/P].

### 3.6 Weathering as a few designed strokes

- No source quantifies stroke counts. *Akira* added damage as separate cel layers [S/2]; books
  on background painting keep libraries of reusable parts (clouds, trees, walls) [S, snippet].
- Rule [I]: keep the generator's cause-placed sources (sill ends, fixings, drip-less tops) and
  draw **fewer, wider, harder-edged** marks from them. Lookdev: streak count about ×0.3, width
  about ×2, edge sharpness up, and no micro grain inside the stain.
- Post fallback [C]: posterise albedo value against a local mean (Kuwahara radius 8) into four
  levels, 0.78 / 0.90 / 1.0 / 1.06. Apply it as a value gain so small coloured items (laundry,
  signs) keep their hue. Image mode cannot do this, because lighting and stain are not separable
  without an albedo AOV. On v5, stains flipped into the shadow band and made blotches [C].

### 3.7 Atmospheric perspective

- Distant forms turn bluer and paler, toward the sky colour [S, Musabi glossary].
- Kobayashi rejects haze: distant things stay clear but lose detail [S/P]. Treat this as a second
  preset (`--no-haze` plus distance simplification), not a contradiction [I].
- Split depth into 4–6 planes for grading (Weathering With You's BOOK layers) [S].
- Prototype: haze linear in depth from 40 m to 650 m, at most 0.40 toward the haze colour. A
  square-root ramp over-hazed the blocks at 200–300 m until they vanished [C]. Distance
  simplification is a larger Kuwahara (radius 4) blended in with the same ramp [C].

### 3.8 Compositing

- Diffusion: blur and Screen (Clip Studio: Gaussian 50, Screen) [S]. Prototype: blur 0.02 of the
  image width, Screen at 7 % [C].
- Glow and lens halos are a night and Ogura device, not a day default [S/2].
- *Akira* glows shift to cyan away from a white core [S, analysis].

## 4. Round C measurements

`frame_critique.py` (unchanged) and a scratch script with the candidate painterly checks, on
1280 × 720 renders. "Before" is the realistic render; "after" is the prototype, `summer_day`
at strength 1 unless noted. `real` and `paint` give the profile statuses for value_range,
value_grouping, squint, spectral_slope, saturation, depth, detail, micro and saliency.

| Frame | Notan dominance | L\* p1 | Shadow b\* | Peak-3 share | Micro amp (L\* std) | Spectral slope | Mean C\* non-sky |
|---|---:|---:|---:|---:|---:|---:|---:|
| v3 hero street, Karma (before) | 2.57 | 6.6 | +4.1 | 0.54 | 8.6 | −1.03 | 6.8 |
| v3 hero street, aov after | 1.67 | 14.3 | −3.8 | 0.69 | 5.7 | −1.13 | 10.3 |
| same, deep sky | 1.07 | 14.3 | −4.0 | 0.69 | 5.6 | −1.13 | 11.7 |
| same, strength 0.4 | 2.31 | 14.5 | −1.6 | 0.54 | 6.9 | −1.09 | 7.5 |
| v3 facade, Karma (before) | 1.14 | 8.9 | +3.7 | 0.57 | 9.7 | −0.98 | 7.7 |
| v3 facade, aov after | 1.71 | 15.4 | −3.9 | 0.68 | 6.4 | −1.01 | 8.7 |
| v3 hero JPG, image after | 1.14 | 24.7 | −5.8 | 0.71 | 5.5 | −1.12 | 12.2 |
| v5 street JPG (before) | 2.14 | 10.5 | +5.6 | 0.61 | 5.9 | −0.65 | 9.3 |
| v5 street JPG, image after | 1.51 | 31.2 | −4.8 | 0.73 | 5.8 | −0.85 | 11.9 |

What separates the two looks cleanly: shadow b\*, the black floor, and the peak-3 share. Micro
amplitude separates the v3 renders but not v5, whose original is already flat. The spectral
slope barely moves (−1.03 → −1.13), so it is no style test. Value grouping is the one that got
**worse**. The painted sky and the blue shadows broke the light mass on the hero street, and
only a paler sky won some of it back. That is a real composition finding, not a threshold
problem.

## 5. Conflicts and gaps

- Kobayashi's no-haze rule against plain atmospheric perspective: two presets.
- Ogura's mono reference photos against his own colour photos: mono for structure, colour from
  memory.
- No source found for edge-highlight lines, toothbrush spatter, ruling pens (溝引き), or how
  stains were painted. These rules are [I].
- Night (*Akira*): needs emissive windows and street lights in lookdev; the post cannot invent
  them from a day render. Not prototyped.
- Kyprianidis's anisotropic Kuwahara radius and α, the XDoG paper values, and the GGXrd handout
  could not be read.

## Sources

Painting practice:
- Colossal, *Akira* architecture exhibition: https://www.thisiscolossal.com/2022/06/akira-architecture-neo-tokyo/
- Manga-Passion, *Akira* exhibition Berlin: https://manga-passion.de/articles/6006/akira-ausstellung-in-berlin-die-architektur-von-neo-tokyo-in-eindrucksvollen-exponaten
- Bijutsu Techo, *Akira* and Ogura: https://bijutsutecho.com/magazine/news/report/27371
- Gallery Nucleus listings (snippets): https://gallerynucleus.com/detail/38126 · https://gallerynucleus.com/detail/38130/
- Dave Rupert on the *Akira* colours: https://daverupert.com/2022/11/50-colors-akira/
- 032c, GITS architecture: https://magazine.032c.com/magazine/anime-architecture-ghost-shell-built
- RIBA Journal (snippet): https://www.ribaj.com/culture/exhibition-anime-architecture-backgrounds-of-japan-house-of-illustration-london/
- Icon: https://www.iconeye.com/opinion/anime-architecture
- It's Nice That: https://itsnicethat.com/news/anime-architecture-backgrounds-of-japan-house-of-illustration-250517
- Japan Foundation Sydney: https://sydney.jpf.go.jp/media-releases/anime-architecture/ · https://sydney.jpf.go.jp/events/hiromasa-ogura-in-conversation-with-philip-brophy
- Otaku USA on Riekeles: https://otakuusamagazine.com/?p=285094
- Wikipedia, GITS (1995) and *Honnêamise* art direction: https://en.wikipedia.org/wiki/Ghost_in_the_Shell_(1995_film) · https://en.wikipedia.org/wiki/Art_direction_of_Royal_Space_Force:_The_Wings_of_Honn%C3%AAamise
- Animation Obsessive: Oga https://animationobsessive.substack.com/p/what-kazuo-oga-thinks-about-when · Totoro https://animationobsessive.substack.com/p/defining-the-world-of-my-neighbor · Yamamoto https://animationobsessive.substack.com/p/the-origin-of-a-master-painter · Yasuda https://animationobsessive.substack.com/p/the-artist-who-colored-ghibli · *Patlabor 2* https://animationobsessive.substack.com/p/life-under-martial-law · *Akira* light https://animationobsessive.substack.com/p/dangerous-light
- Animétudes, 1981 background roundtable: https://animetudes.com/2022/12/10/anime-background-art-roundtable/
- Kobayashi interview (anime!anime!, 2020): https://animeanime.jp/article/2020/02/08/51470.html · https://animeanime.jp/article/2020/02/08/51470_2.html · https://animeanime.jp/article/2020/02/08/51470_3.html
- *Patlabor* review (anime!anime!, 2025): https://animeanime.jp/article/2025/10/31/93512.html
- Newtype USA, Kato on Eva: https://www.evamonkey.com/writings/newtype-usa-document-of-evangelion.php
- ANN, Bihou: https://www.animenewsnetwork.com/encyclopedia/company.php?id=5077
- Studio Pablo (Otaku Mode): https://otakumode.com/news/51b76057c16063b47e0196ec · https://otakumode.com/news/51b7624f11f602847501e06a
- Watabe (ja.wikipedia): https://ja.wikipedia.org/wiki/渡部隆 · RealSound on Oshii: https://realsound.jp/movie/2025/11/post-2220060.html
- Harmony: https://dic.nicovideo.jp/t/a/%E6%AD%A2%E3%82%81%E7%B5%B5
- Nicker sky video: https://yutura.net/channel/74716/popular/dr1MK3Uq8jc/
- Gigazine on anime power lines: https://gigazine.net/gsc_news/en/20171225-why-anime-power-lines/

3D pipelines and filters:
- CGWORLD: *Your Name* https://cgworld.jp/feature/201610-cgw218t1-kiminona.html · *Weathering With You* https://cgworld.jp/feature/201910-254-tenkige.html · https://cgworld.jp/interview/201910-tenkinoko03.html · *Jujutsu Kaisen 0* https://cgworld.jp/article/202203-jujutsukaisen.html · Granblue Relink https://cgworld.jp/article/202405-cgw309-relink04.html
- Blue Protocol, CEDEC: https://www.famitsu.com/news/202009/08205405.html · https://www.gamebusiness.jp/article/2021/09/13/19051.html
- *Shin Evangelion* miniature: https://www.timeout.jp/tokyo/ja/news/small-worlds-tokyo-shin-evangelion-village3-040921
- Studio pipelines: https://animeanime.jp/article/2022/02/11/67491.html · https://realsound.jp/movie/2023/04/post-1306272.html · https://news.mynavi.jp/article/20120526-s_fatezero/10
- Urbanowicz interview: https://blog.alltheanime.com/interview-mateusz-urbanowicz/
- Clip Studio tips: https://tips.clip-studio.com/ja-jp/articles/8939 · https://tips.clip-studio.com/en-us/articles/8952
- White-box cartoonisation: https://github.com/SystemErrorWang/White-box-Cartoonization · https://openaccess.thecvf.com/content_CVPR_2020/html/Wang_Learning_to_Cartoonize_Using_White-Box_Cartoon_Representations_CVPR_2020_paper.html
- Scenimefy: https://ar5iv.labs.arxiv.org/html/2308.12968
- Kuwahara: https://docs.blender.org/manual/en/dev/compositing/types/creative/kuwahara.html · https://raw.githubusercontent.com/GarrettGunnell/Post-Processing/main/Assets/Kuwahara%20Filter/AnisotropicKuwahara.cs · https://diglib.eg.org/items/9865e5fe-3d23-470e-8cf6-e571bebafb9b
- Roystan outlines: https://roystan.net/articles/outline-shader/
- Oklab: https://bottosson.github.io/posts/oklab/
- Gurney on grouping values: https://jamesgurney.substack.com/p/grouping-values
- Musabi glossary, aerial perspective: https://art-design-glossary.musabi.ac.jp/aerial-perspective/
- SideFX docs (Houdini 22): https://www.sidefx.com/docs/houdini/nodes/cop/kuwaharafilter.html · https://www.sidefx.com/docs/houdini/nodes/cop/edgedetectdepth.html · https://www.sidefx.com/docs/houdini/nodes/cop/edgedetectnormal.html · https://www.sidefx.com/docs/houdini/nodes/cop/quantize.html · https://www.sidefx.com/docs/houdini/solaris/support/aovs.html · https://www.sidefx.com/contentlibrary/npr-crag/
- Orbitals (Unreal tech blog, snippet): https://www.unrealengine.com/tech-blog/stepping-inside-a-retro-anime-inspired-game-a-look-into-the-rendering-of-orbitals
