# Art direction: judging the picture, not the parts

The checks are in `../scripts/frame_critique.py` (numpy and PIL only), and the A/B question list is
in `critique_questions.md`.
Baseline: **realistic**, meaning photographic or nearly so. A painterly or anime look is an
optional profile (`--profile painterly`), built as a switchable layer
(`procedural-materials/references/stylisation-anime.md`, round C); its thresholds are not yet
calibrated on the user's picks.
Thresholds were calibrated in round B on 24 of the user's own A/B picks (§5). They fit one
viewer's taste on danchi v1–v5 renders, in sample, so treat them as the current best guess.

## 1. Principles

**Value structure first.** A picture that works reads as three or four large value shapes
when squinted at. One value dominates, roughly 2:1 against the next. Detail lives inside the
shapes and never breaks them up. In sunlit exteriors:
- the sunlit wall is bright but not white;
- shadows keep detail;
- the sky and the wall stay separate values.

Real white paint has an albedo of 0.65–0.8, never above 240 sRGB (`realism.md`). Both ends
fail:
- **Blown out.** Walls at L\* 99–100 with clipped channels lose all their texture (v4).
- **Dim.** Camera-facing walls in half-light at L\* 40–60 read as "an old video game" (v5).

The user preferred sunlit walls at L\* 85–96 (v2, v3), with some clipping on the brightest
paint accepted. Light the face the camera sees (`believability.md` 6).

**Colour and saturation budget.** In a photograph, large surfaces are low in chroma. Japanese
landscape plans make this a rule for facade base colours, in Munsell chroma:
- red to yellow-red hues: at most 4, or 1.5 when the value is 8.5 or more;
- yellow-red to yellow: at most 6, or 2;
- all other hues: at most 2, or 1.

Accent colours stay under about 5 % of a facade. Strong chroma belongs in small accents
placed where the story is: laundry, a sign, rust at a leak. A pale surface tinted beyond the
limit reads as a toy. Tint is easiest to see near white, so pale surfaces get the tightest
limit. Distance should pull colour toward the sky: lower contrast, lower chroma, cooler.

**Composition and focal point.** Each shot has one job and one place the eye goes first.
The brightest contrast and the strongest accent should sit there. Two or three competing
peaks, or a bright artefact such as a white AC unit, a sky hotspot or a glint, are the
usual failures. Use a leading line and keep foreground, middle ground and background
distinct.

**Detail budget (80/20 at picture level).** Most of the detail goes into a minority of the
frame, around the subject. At least about 30 % of the frame stays quiet. The same rule
applies on each surface (`believability.md` 1): clustered damage, sourced streaks, a few
neglected flats. Streaks start at sources: sill ends, window corners, attachments, and
drip-less tops. In photographs only about a third hang from a top edge (review 31, the photo
study). A fringe under every coping is a stamp.

**Read at distance.** Judge each level at its own viewing distance (`SKILL.md`). Detail that
is noise at the true distance is a cost, not a gain. Micro grain must vary by cause (p90/p10
of local amplitude 3–6; `procedural-materials/references/micro-noise.md`). Uniform grain reads as sandpaper.

**Presentation does not give it away** (`believability.md` 6):
- camera at eye height, 1.5–1.7 m;
- verticals straight, or keystoning used on purpose;
- sun 15–35° high;
- real ground context.

An aerial view over a bare plane, or objects on a featureless backdrop, reads as a model.
Judge variation on eye-height street views, not only on aerial seed sheets.

**Seed spread.** A generator is judged by its median seed, not its hero. Look at a 3×3 or
4×4 sheet at the same camera:
- Do the seeds differ in more than paint colour?
- Do they all fail the same test?
- Which two are near-identical, and which one is broken?

## 2. Running the critique at each gate

```
python <skill>/scripts/frame_critique.py render.jpg --sheet render_diag.jpg --json render.json
python <skill>/scripts/frame_critique.py --pair old.jpg new.jpg --sheet ab.jpg --json ab.json
python <skill>/scripts/frame_critique.py sheet9.jpg --grid 3x3 --grid-trim 0.12     # seed spread
python <skill>/scripts/frame_critique.py r.jpg --mask ids.json --depth depth.png --ref photo1.jpg photo2.jpg
```

- **Every `look` at lit or final quality:** run the script. It takes a second or two. Act on
  the binding tests (`value_range`, `saturation_budget`, `detail_density`, the bare-plane and
  void-backdrop part of `camera`, the amplitude floor of `micro_uniformity`, and
  `streak_evenness` with a mask). The others report `info` (§5); read their explanations, but
  do not chase them.
- **Level gates (golden piece, bay, facade, building, block):** run the full set, plus
  `--pair` against the previous gate's render at the same camera. Pass a wall mask, made
  from a Karma ID or matte AOV converted to PNG, so that `streak_evenness` and
  `micro_uniformity` measure the wall. Without a mask, the streak test reports info only.
- **Distance read:** run at the level's judged distance. For micro grain on a texture
  map, or on a local-variance AOV, use `--input-kind variance_map`.
- **Before packaging:** run `--grid` on the seed sheet and the full set on two or three
  eye-height street views.
- **Last:** the A/B question pass in `critique_questions.md`, with the numbers attached, in
  both orders.

Each test reports a value, a target, pass/warn/fail/info and a one-line reason. There is no
total score. Fix fails first, then warns that the VLM pass agrees with. No test measures streak
variety, damage that fits the story, or composition; those need the A/B questions and your
own eye against `believability.md` 7.

## 3. Failures and usual fixes

| Test | Failure means | Usual fix |
|---|---|---|
| `value_range` | blown-out wall; dim camera-facing walls (warn below L\* 60); crushed shadows; flat range | lower paint albedo into the `realism.md` table or lower exposure; for dim walls, bring the sun round to the camera's side and add a visible sky dome |
| `value_grouping`, `squint` | no dominant value; confetti; structure only in small detail | group lights and darks with lighting and material value; quiet the busy zone; bring big shapes forward |
| `saturation_budget` | a large surface above the base-colour chroma limit; pale over-tint; accents over 5–10 % | desaturate the base paint toward grey-beige; bleach the sunny side; limit accents to the story spots |
| `palette` | scattered hues; off the reference | move props and paint onto one hue template; fit to reference photos |
| `depth_separation` | the far plane is as crisp and saturated as the near one | add atmosphere or height fog; desaturate and cool the distance |
| `detail_density` | detail everywhere; no rest area; or an empty frame | cluster detail at causes; leave quiet bays; add context where empty |
| `repetition` | near-copies at one shift (clone stamping) | per-instance variation; hex tiling; break up the prop set |
| `streak_evenness` | streaks hang from every top edge (fringe); darkening repeats per bay | spawn streaks from sources (sill ends, fixings, drip-less tops) with power-law strength; vary by column of openings |
| `micro_uniformity` | no grain at all (binding); stationary grain (info on renders, binding on variance maps) | subtle base variation and grain on clean paint and concrete; amplitude envelope from cause masks; switch the grain's character in worn zones |
| `saliency` | several competing peaks; top peak on a small bright artefact | dim or remove the distractor; put the strongest contrast at the subject |
| `camera` | leaning verticals; elevated view over a bare plane; void backdrop | level camera with shift; eye height; ground context; a horizon |
| `reference_match` | value or chroma histograms far from the reference photos | match exposure and palette to the references |

## 4. Round A status

The checks were run on danchi v1–v5 (review 32, round A). The judgments they were checked
against are the team lead's and partly the user's; they are not ground truth.

All four checks pass:
- v4's cream walls fail on value and on saturation; v5's concrete passes both.
- On the golden bays, the fringe share is v4 0.71 and v3 0.73 against v5 0.34. The test
  needs a wall mask.
- The v5 aerial sheet fails as a miniature.
- Uniform and clustered micro grain separate.

Weak spots:
- **Saliency** warns on nearly every frame. It is not calibrated.
- **Depth separation** is heuristic without a depth AOV.
- **Repetition** flags regular facades that are straight-on, because it cannot tell
  designed rhythm from clones without instance IDs.
- **Squint and spectral slope** warn on v5's street view, which was judged the most
  photographic.

## 5. Round B calibration

The user made 24 A/B picks on danchi v1–v5 renders, with notes (review 33). For each test,
agreement is the share of decisive pairs where the better status belonged to the user's pick.

| Test | Round A | Round B | Now |
|---|---:|---:|---|
| `value_range` | 67 % | 81 % (13–3) | binding: two-sided, L\* 60–96 warn, 98.5 fail; clipping warn 25 %, fail 35 % |
| `detail_density` | 75 % | 75 % (9–3) | binding, unchanged |
| `saturation_budget` | 67 % | 72 % (13–5) | binding: warn over 1.0× the base-colour limit; fail over 2.5×; pale over-tint fail 45 % |
| `micro_uniformity` | 42 % | 1–0 | the "too flat" floor is binding; stationarity is info on renders |
| `camera` | 25 % | 0–1 | info, except the bare-plane and void-backdrop checks |
| `value_grouping`, `squint`, `spectral_slope`, `saliency`, `repetition`, `depth_separation` | 25–50 % | — | info |
| `palette`, `reference_match`, `streak_evenness` | no decisive pairs | — | unchanged; streaks need a mask, the reference test needs photos |

Overall, scoring each frame as 2 × fails + warns, the critique picks the user's choice in 17
of 21 decisive pairs, up from 12 of 22 in round A. That is measured on the same picks it
was fitted to, so it overstates how well it will generalise.

What the numbers cannot see, from the user's notes:
- streak spacing, length, width and intensity variety, and layered build-up;
- damage that fits the age of the building;
- composition and context: an empty road, a building on a bare plane;
- whether the seed sheet shows true relative scale.

Four of the five saturation disagreements are v2 (warn) chosen over v3 or v5 (pass). The user
never commented on colour, so the base-colour standard stays a warn, as realism guidance the
picks neither confirm nor reject.

Next calibration:
1. **Reference set.** Collect 20–40 photos of danchi and Japanese streets, with the user's
   permission to download, as `--ref` targets for `reference_match` and `palette`.
2. **Hold-out picks.** Re-check on a new set of picks from a later round, not the ones above.
3. **Painterly profile.** Calibrate it the same way on stills of the target style before
   it is used.
