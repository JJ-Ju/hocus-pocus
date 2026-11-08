# Meta research: gaps in our procedural-art research, and a self-critique toolkit for agents

Rounds 3–4 and the r5 layering and wear-simulation reports studied the **surface**. They did
not study the **image** (value, colour, composition, focus), the **generator** (how a director
judges hundreds of seeds), or the **style** the brief names (80s–90s anime backgrounds).
Danchi v4 shows the cost. Its walls came out a saturated, over-bright cream, and its surfaces
read less real than v3's (review 31). That is a value and colour failure, and none of our
checks would have caught it. Tags: [S] sourced, [I] inferred.

## 1. Ranked gap areas

| # | Area | Why it matters for our output | Impact | Effort | Next research question | Key sources |
|---|---|---|---|---|---|---|
| 1 | **Value structure and read tests** (greyscale, squint, 3- and 5-value notan, depth-plane separation) | The v4 failure. Painters build depth from a few grouped values, one narrow range per plane [S]. We never check it. | Very high | Low | Which value statistics separate good environment frames from muddy ones, and can thresholds come from reference stills? | Muddy Colors on value planes; Proko notan critiques; Sessions.edu on value structure |
| 2 | **Colour management**: palette, saturation budget, harmony, atmospheric colour, colour script | Saturation and brightness drift is our recurring defect. Gurney's gamut masks and atmospheric rules are explicit and measurable [S]. Naughty Dog colour-scripts mood across a game [S]. | Very high | Low–med | What saturation and lightness distributions do reference photos and anime backgrounds of our subjects have? | Gurney gamut masking; Cohen-Or colour harmonization; Game Informer on Uncharted 4 |
| 3 | **Composition, focal hierarchy, visual-noise budget** | Our 80/20 rule clusters detail on the *surface*, but nothing checks the *frame*. Polycount critiques keep naming clutter and a missing focal point [S]. Pangilinan: every element "has to have a function" [S]. | High | Med | How do directors allocate rest areas and focal contrast, and can a saliency map check it? | 80.lv on Pangilinan (GDC 2017); Polycount threads; Framed Ink |
| 4 | **Evaluating generators at scale** (expressive range, contact sheets, seed audits) | We judge one hero seed. PCG research judges the *distribution*, because thousands of near-identical outputs are worthless [S]. | High | Med | Which 4–6 metrics span our generator's expressive range, and where does it collapse or break? | Smith & Whitehead 2010; PCG book ch. 12 |
| 5 | **Agent critique loop**: VLM-as-judge plus measured checks | The agent is its own art director. VLM judges align with people when *comparing pairs* [S]. Verification gains from spending compute on the verifier [S]. VLMs fail at simple geometry and counting [S]. | High | Med | Which rubric and pairwise protocol agree best with the user's own A/B picks? | GPTEval3D; BlenderGym; BlenderAlchemy; "VLMs are blind" |
| 6 | **Stylisation: anime background practice** | The brief references Akira and Evangelion, but `surfacing.md` has only a short stylised section. Oga distils "the essential point" [S]. Ogura worked from monochrome photos so as not to constrain the palette [S]. Akira needed 327 colours because it is a night film [S]. | High (for this brief) | Med | Concretely, how do Mizutani, Ogura, Oga (and Kobayashi, unverified) simplify texture, shape the light and limit the palette, and which of these can a renderer reproduce? | Animation Obsessive on Oga; RIBA J. on Ogura; Riekeles *Anime Architecture*; Slashfilm on Akira |
| 7 | **Reference-matching statistics** (render vs photo) | We compare to photos by eye. Colour moments, spectral slope, gradient statistics and texture-tolerant perceptual metrics can all do it numerically [S]. | Med–high | Med | Which statistics best tell our renders apart from matched photos, and which survive changes of lighting? | Reinhard 2001; Graham & Field; Redies PHOG; DISTS; CMMD |
| 8 | **Lighting design for presentation and guidance** | Our light is "a 28° sun". Level lighting builds a hierarchy (main exits brighter), keeps a consistent lighting language, and favours upper-midtone albedos [S]. | Med–high | Low–med | A lighting recipe per shot type (hero, bay, skyline) with key-to-fill ratios and rim placement | Robert Yang & David Shaver, GDC 2018; Patry, Ghost of Tsushima |
| 9 | **Art-direction artefacts**: art bible, visual targets, paintovers | They give the agent a *written* standard to replace taste. A paintover should state the principle, not just the fix [S]. Art boards set direction for a whole team of painters (Oga on Totoro) [S]. | Medium | Low | A one-page art bible template the agent fills in at Phase 0, with palette, value key, detail budget and style rules | MoH Airborne visual-direction deck; Game Developer on art direction; Animation Obsessive |
| 10 | **Level-art integration**: landmarks, Lynch's five elements, weenies, set dressing | Generated blocks need landmarks and readable districts, or a city reads as noise. Totten maps Lynch's elements onto level design [S]. | Medium | Med | What landmark density and hierarchy should a generated city block have (global, local, micro)? | Lynch 1960; Totten; Horizon placement (GDC 2017) |
| 11 | **Vegetation**: space colonisation, L-systems, Labs Tree tools | The v3 trees were faceted blobs; v4 is better but hand-rolled. Space colonisation gets silhouettes from competition for space [S], and Labs ships free tree tools [S]. | Medium | Med | Can the Labs Tree tools or a space-colonisation SOP reach hero-quality street trees at game budgets? | Runions et al. 2007; Labs Tree Tools; Feriani (Houdini SCA) |
| 12 | **Layout by constraint or WFC on irregular grids** | Interiors, set dressing and plazas. Infinigen Indoors pairs a constraint DSL with a solver [S]. Townscaper keeps large shapes predictable and lets small ones vary [S]. | Medium | Med–high | Can a small constraint solver dress rooms and balconies more plausibly than seeded scatter? | Infinigen and Infinigen Indoors; Game Developer on Townscaper; Merrell |
| 13 | **Performance-aware art** (texel density, draw calls, LOD and impostor policy) | `game-output.md` covers LODs; texel-density and instance budgets are missing. Nanite is not always faster than LODs for foliage [S]. | Medium | Low | Texel-density and per-block triangle and instance budgets for our target engine | Epic Nanite docs; Nanite vs LOD study (preprint) |
| 14 | **Inverse procedural modelling, differentiable fitting** | Fitting generator parameters to photos: facade grammars, material graphs [S]. Research-grade. | Med–low | High | Could CMA-ES over HDA parameters, scored by §2's statistics, replace hand tuning? [I] | Wu et al. facade IPM; MATch |
| 15 | **Simulation-driven generation** (city growth, erosion) | Gives history for free, at a high cost. Erosion is cheap in Houdini 21 [S]; 4D cities are research [S]. | Low–med | High | Is a light "age the block" pass (add-ons, repairs) worth it? | Weber et al. 2009; SideFX terrain docs |
| 16 | **ML generation** (3D generative models, image-to-material, neural materials) | **Hype for us:** 3D generators give messy topology that needs retopology [S]; neural materials have not shipped in games [S]. **Useful now:** diffusion for concept targets and paintovers (BlenderAlchemy's "visual imagination") [S]; image-to-material to read reference roughness and height [S]. | Low (gen) / Med (targets) | Med | Can a generated paintover of our own render act as a visual target the agent measures against? | Substance Sampler docs; NVIDIA neural appearance; Scenario 3D docs |

**Covered already:** grammars and WFC as architecture choices (`generator-architecture.md`).
**Weak:** learned aesthetic scores. LAION's predictor is about 60 % photo-contest data and
tracks preferences poorly [S], so count it as one weak vote at most.

## 2. Self-critique toolkit for agents

Each test runs on a Karma render plus AOVs (depth, ID, normal) with numpy and PIL, or with a
small pretrained model where noted. **All thresholds are [I] starting points.** Calibrate them
on reference photographs, stills of the target style, and the user's verdicts on danchi v1–v4.

| Test | How to automate | What it catches |
|---|---|---|
| **T1. Value range and clipping** | Convert to CIE L\* (or Oklab L). Report the 1st, 50th and 99th percentiles, the share of pixels above L\* 95 and below L\* 5, and the median L\* of the sunlit wall mask (object ID) against reference photos of the same material in sun. | Over-bright pale paint (v4's cream walls), crushed shadows, low dynamic range |
| **T2. Squint and notan** | Blur with σ ≈ 1–1.5 % of the image width, or downsample to 64 px. Quantise L\* into 3 and into 5 levels (k-means or fixed cuts). Measure the area share per level, the connected regions per level, and the size of the largest region. Good: one level dominates (roughly 2:1 against the next) [S, the 2:1 ratio from painting self-critique] and there are few large regions. Bad: equal thirds, or confetti. | Muddy frames, even busyness, no big-shape design |
| **T3. Depth-plane separation and aerial perspective** | Split the depth AOV at its 33rd and 66th percentiles. For each plane, compute the mean and IQR of L\*, the mean chroma, and the mean hue. Expect planes separated more than their IQR overlap, and contrast and chroma that fall, and hue that cools, with depth. Gurney gives the rule and its warm-light exception [S]. | Flat "CG" depth, a background as sharp and saturated as the foreground, missing haze |
| **T4. Silhouette and thumbnail read** | Render a matte (alpha or ID) against the sky at 64–128 px, and save a pass at each level's viewing distance from the skill. Measure skyline height variance per segment, perimeter² ÷ area, and the count of distinct protrusions. A VLM then names the building type from the matte alone. | Flat rooflines, blob trees, styles that read only up close ("the silhouette alone should name the style") |
| **T5. Saturation budget and colour accent** | Take an Oklch chroma histogram. Keep the share of pixels above a high chroma bound under about 5–10 %, and require the accent pixels to fall mostly inside the intended focal mask. Compare the median chroma of large surfaces with references. | Over-saturated walls, rainbow props, accents that compete with the focal point |
| **T6. Palette and harmony** | Fit 5–8 k-means colours in Oklab and report ΔE to the art-bible palette. Fit the 8 Cohen-Or and Matsuda hue templates to the chroma-weighted hue histogram; report the share of hue mass inside the best template and that template's type [S]. | Off-palette assets, discordant hue spread, a drift from the colour script |
| **T7. Reference statistics** | On luminance, compare against matched photographs: (a) the Reinhard per-channel mean and std in Lab [S]; (b) the radial power-spectrum slope, which for art and natural scenes sits near amplitude exponents of −1.2 to −1.4 [S] (steeper reads as CG-smooth, shallower as noisy); (c) the PHOG self-similarity and anisotropy measures [S]; (d) DISTS between render crops and photo crops, which tolerates texture resampling [S]; (e) CMMD across sets of 50 or more images [S]. | "CG look" in general: smoothness, wrong contrast, missing mid frequencies, wrong grain |
| **T8. Focal point and saliency** | Run DeepGaze IIE (pretrained PyTorch weights; use a uniform centre bias for renders) [S], or spectral-residual saliency as a numpy fallback [I]. Report the share of saliency mass inside the focal ID mask, the saliency entropy (high means no focus), and the top three peaks, each named with the object ID under it. | Eye wander, a bright distractor (a sign, a sky hotspot, a white AC unit) stealing focus, a hero that does not pop |
| **T9. Visual-noise budget and rest areas** | Take Sobel or Laplacian energy in 16–32 px windows on the squinted image. Report the share of low-energy "rest" windows (for example ≥ 30 % [I]), the Gini coefficient of detail energy, and the share held by the top 20 % of windows (our 80/20 measure lifted to frame level). | Detail spread evenly across the frame, no place for the eye to rest, the opposite failure of an empty frame |
| **T10. Repetition** | High-pass the luminance and take its 2D autocorrelation; non-zero-lag peaks above a threshold flag tiling [S, the method]. For props, hash instance ID, transform-relative orientation and material, then count identical neighbours within *r* metres. Polycount: duplicates sharing a texture are "very noticeable" [S]. | Visible texture repeats, clone-stamped props, mirrored seams |
| **T11. Expressive range** | Generate 50–200 seeds and compute 4–6 global metrics per seed (for example height, bay rhythm, damage share, median chroma, saliency entropy). Plot 2D histograms [S], and flag collapse (low variance) and outliers. Render a 4×4 thumbnail contact sheet, and have a VLM pick the most similar pair and the most broken seed. | Sameness across seeds, parameter regions that break, a hero seed that hides a weak median |
| **T12. Distance and LOD read** | Render at each level's judged distance. For value match across LODs, use the T1 statistics per LOD. For shimmer, measure high-frequency energy at distance against a supersampled frame. | Popping, aliasing, detail that is noise at its true viewing distance |
| **T13. VLM art-director pass** | Give the VLM the image, the T1–T12 numbers and the art bible, and a fixed rubric: What do you see first? Is that the intent? Does the 3-value thumbnail read? Where does the eye rest? What tells scale? Does each element have a function and a story (Pangilinan) [S]? Which surface is least believable? It localises each issue on a 4×4 grid. **Compare in pairs** (old vs new, render vs reference), as GPTEval3D's Elo does [S], in both orders to cancel position bias [I]. Spend samples on verifying (BlenderGym) [S]. **Never trust it for** counts, overlaps or fine geometry [S]. | Story and intent problems that numbers miss; a sanity check on the numbers |

**Order of use.** T1–T3 and T5 cost milliseconds; run them on every `look`. Run T7–T10 at
each level gate, T11 before packaging, and T13 last, with the numbers attached.

**Studio critique conventions to encode** [S unless marked]:
- Squint, greyscale and thumbnail first, then detail.
- Use 2–3 test shots from player height, each with one leading line (Polycount).
- Light the main path more than side routes, and light like things alike (Yang).
- Big picture first, then "the details that will sell it" (MoH Airborne).
- Write every note as principle, location and fix; a paintover alone gets copied [S].

## 3. Next three research rounds

1. **R5: image-level art direction** (gaps 1–3, 7, 8). Deliver an `art-direction.md`
   reference with a Phase-0 art-bible template, and a tested `frame_critique.py` running
   T1–T10 on Karma renders with AOVs. Calibrate on about 40 photographs of danchi and Japanese
   streets and on Akira, Patlabor and Evangelion stills. Pass condition: it flags v4's cream
   walls and ranks v3 above v4 on surface realism, as the user did.
2. **R6: replacing the eye** (gaps 4, 5, 9). The user makes 20–30 A/B picks on existing
   renders. Measure which metrics and which T13 rubric agree with them, keep those, and drop
   the rest. Add T11 contact sheets to the Phase-9 review. This turns the user's taste into a
   reproducible standard.
3. **R7: stylisation for this brief** (gaps 6, 8). Study how Mizutani, Ogura, Oga and
   Kobayashi simplify texture into shape, paint light (Ogura's lens halos, Akira's night
   palette), limit the palette and layer cels. Translate that into Karma and Copernicus:
   hand-shaped stains, posterised value, GGXrd-style stepped shading [S], painted skies,
   projection painting. Add a style-target test: T6 and T7 against anime stills instead of
   photographs.

Then: vegetation (11), landmarks (10), constraint dressing (12).

## 4. Sources

Procedural modelling and PCG:
- [S] Müller et al., Procedural Modeling of Buildings (2006): https://history.siggraph.org/?p=113547
- [S] Smelik et al., survey of procedural modelling (CGF 2014): https://www.cs.purdue.edu/homes/bbenes/papers/Smelik14CGF.pdf
- [S] Wu et al., inverse procedural modelling of facade layouts: https://history.siggraph.org/?p=103601
- [S] Merrell, model synthesis: https://paulmerrell.org/model-synthesis/
- [S] How Townscaper works: https://www.gamedeveloper.com/game-platforms/how-townscaper-works-a-story-four-games-in-the-making
- [S] Labs WFC: https://sidefxlabs.artstation.com/projects/DAB6lO
- [S] Runions et al., space colonisation (2007): https://www.algorithmicbotany.org/papers/colonization.egwnp2007.html
- [S] Feriani, Houdini SCA tree tool: https://nccastaff.bournemouth.ac.uk/jmacey/MastersProject/MSc17/01/
- [S] Labs Tree Tools: https://sidefxlabs.artstation.com/projects/PoLJlo
- [S] Infinigen (CVPR 2023): https://arxiv.org/pdf/2306.09310
- [S] Weber et al., 4D cities (2009): https://diglib.eg.org/handle/10.2312/CGF.v28i2pp481-492
- [S] SideFX terrain workflow: https://www.sidefx.com/docs/houdini/model/terrain_workflow.html
- [S] Horizon Zero Dawn procedural placement (GDC 2017): https://www.guerrilla-games.com/read/gpu-based-procedural-placement-in-horizon-zero-dawn
- [S] Smith & Whitehead, expressive range (2010): https://www.pcgworkshop.com/archive/smith2010analyzing.pdf
- [S] PCG book: https://pcgbook.com/ ; ch. 12: https://www.pcgbook.com/chapter12.pdf

ML and evaluation:
- [S] MATch: https://match.csail.mit.edu/
- [S] BlenderAlchemy: https://arxiv.org/abs/2404.17672v3
- [S] BlenderGym: https://huggingface.co/papers/2504.01786
- [S] GPTEval3D: https://openaccess.thecvf.com/content/CVPR2024/papers/Wu_GPT-4Vision_is_a_Human-Aligned_Evaluator_for_Text-to-3D_Generation_CVPR_2024_paper.pdf
- [S] VLMs are blind: https://arxiv.org/abs/2407.06581v6
- [S] LAION aesthetic predictor audit: https://arxiv.org/pdf/2601.09896
- [S] DeepGaze IIE: https://openaccess.thecvf.com/content/ICCV2021/html/Linardos_DeepGaze_IIE_Calibrated_Prediction_in_and_Out-of-Domain_for_State-of-the-Art_Saliency_ICCV_2021_paper.html ; code: https://github.com/matthias-k/DeepGaze
- [S] Graham & Field, spectra of art: https://people.hws.edu/graham/Graham_perception08.pdf ; exponents: https://www.frontiersin.org/articles/10.3389/fnhum.2015.00514/pdf
- [S] Redies et al., PHOG measures: https://projet.liris.cnrs.fr/imagine/pub/proceedings/ECCV-2012/html/7583/75830522.htm
- [S] DISTS: https://arxiv.org/pdf/2004.07728
- [S] CMMD: https://arxiv.org/abs/2401.09603v1
- [S] Reinhard et al., colour transfer: https://www.academia.edu/9445485/Color_Transfer_between_Images
- [S] Cohen-Or et al., colour harmonization: https://www.microsoft.com/en-us/research/wp-content/uploads/2006/07/harmonization.pdf
- [S] TexTile tileability metric: https://web3.arxiv.org/abs/2403.12961
- [S] Substance Sampler, Image to Material: https://helpx.adobe.com/substance-3d-sampler/filters/tools/image-to-material.html
- [S] NVIDIA neural appearance models: https://research.nvidia.com/labs/rtr/neural_appearance_models/assets/nvidia_neural_materials_author_paper.pdf
- [S] Scenario, 3D generation: https://help.scenario.com/en/articles/introduction-to-3d-generation/

Art, direction and level art:
- [S] Gurney, gamut masking: https://linesandcolors.com/2011/09/19/james-gurney-on-gamut-masking/ ; Krita gamut masks: https://docs.krita.org/user_manual/gamut_masks.html
- [S] Aerial perspective: https://perspectiveresearchcentre.com/aerial-perspective/
- [S] Value planes (Muddy Colors): https://www.muddycolors.com/?p=16666 ; Sessions.edu: https://www.sessions.edu/notes-on-design/looking-at-light-value-structures-2/
- [S] Proko, notan critique: https://proko.com/course-lesson/critique-notan-master-thumbnails-level-1
- [S] Self-critique, unequal shapes (2:1): https://realismtoday.com/10-suggestions-on-how-to-self-critique-your-art/
- [S] Framed Ink review: https://www.sessions.edu/notes-on-design/print-picks-framed-ink/
- [S] Pangilinan, Uncharted 4 (80.lv): https://80.lv/articles/the-art-of-the-background-shapes-and-lines
- [S] Uncharted 4 colour script: https://www.gameinformer.com/b/features/archive/2015/01/21/the-secret-depth-of-uncharted-4-s-art-design.aspx
- [S] Yang & Shaver, lighting a level (GDC 2018): https://www.blog.radiator.debacle.us/2018/03/gdc-2018-how-to-light-level-slides-and.html
- [S] Ghost of Tsushima, Patry: https://www.advances.realtimerendering.com/s2021/jpatry_advances2021/index.html
- [S] Polycount critiques: https://polycount.com/discussion/comment/831104 ; https://polycount.com/discussion/comment/2805693 ; https://polycount.com/discussion/comment/2461810/
- [S] MoH Airborne visual direction: https://www.slideshare.net/slideshow/moh-airborne-adprocess/33254852
- [S] Art direction, a touching story: https://www.gamedeveloper.com/art/art-direction-a-touching-story
- [S] Totten, An Architectural Approach to Level Design: https://www.routledge.com/Architectural-Approach-to-Level-Design-Second-edition/Totten/p/book/9781351116305
- [S] Lynch elements: https://www.uxmatters.com/mt/archives/2013/05/information-wayfinding-part-2-elements-of-the-information-environment.php
- [S] Nanite docs: https://dev.epicgames.com/documentation/de-de/unreal-engine/nanite-virtualized-geometry-in-unreal-engine
- [S] GGXrd, GDC 2015: https://www.ggxrd.com/Motomura_Junya_GuiltyGearXrd.pdf

Anime backgrounds:
- [S] Oga on backgrounds: https://animationobsessive.substack.com/p/what-kazuo-oga-thinks-about-when ; Totoro: https://animationobsessive.substack.com/p/defining-the-world-of-my-neighbor
- [S] Ogura (RIBA Journal): https://ribaj.com/culture/exhibition-anime-architecture-backgrounds-of-japan-house-of-illustration-london ; Japan Foundation: https://sydney.jpf.go.jp/events/hiromasa-ogura-in-conversation-with-philip-brophy
- [S] Mizutani and Akira: https://gallerynucleus.com/detail/38126 ; https://www.thisiscolossal.com/2022/06/akira-architecture-neo-tokyo/
- [S] Akira's 327 colours: https://slashfilm.com/807579/how-akiras-record-breaking-use-of-color-resulted-in-50-new-shades
- [S] Riekeles, *Anime Architecture*: https://www.thamesandhudsonusa.com/books/anime-architecture-imagined-worlds-and-endless-megacities-hardcover
- [I] Kobayashi's methods and the Evangelion background staff: not verified this round. They are R7 questions.
