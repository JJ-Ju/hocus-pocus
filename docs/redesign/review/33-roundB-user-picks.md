# Review 33: round B, calibrating the critique on the user's picks

2026-10-27. Round A (review 32) built `procedural-assets/scripts/frame_critique.py`, a set of
numeric checks on renders. Round B asked the user for A/B picks on existing danchi v1–v5
renders, with a note on each, and kept only the checks that agree with them. The picks and
notes are in `docs/redesign/evidence/critique/roundB/picks.json`, and `agree.py` beside them
reproduces the numbers below.

## Picks

24 pairs in 7 groups (bay, close-up, corridor, end wall, facade, seed sheet, street); 23 were
decisive and 23 have notes.

| Pair | Winner | Loser |
|---|---|---|
| bay 1–6 | v2 ×3, v3 ×2, v5 ×1 | v4 ×3, v5 ×2, v3 ×1 |
| close 1–4 | v2 ×2, v3 ×2 | v1, v2, v5 ×2 |
| corridor 1–3 | v2 ×2, v5 | v4 ×2, v5 |
| end wall | v4 | v5 |
| facade | v2 | v3 |
| seed sheets 1–3 | v2, v5, (tie) | v4 ×2 |
| street 1–6 | v3 ×3, v5 ×3 | v4 ×2, v5, v1, v2 ×2 |

v2 and v3 won most pairs. v5, the run with the strongest damage pipeline, lost every bay and
close-up pair to v2 or v3, mostly on lighting. v3's hero street is "the best overall so far,
still far from perfect".

## What the user said, by theme

- **Streaks are still too uniform:**
  - even spacing along an edge;
  - nearly all long and narrow, with few short or partial streaks;
  - no wide streaks where water collects;
  - one intensity and one colour.

  Large stains need internal variance, built up from layered opacities. Some streaks reach
  the ground; others stop a quarter or half of the way down. A streak that starts mid-wall on
  a plain 90° wall looks odd.
- **80/20 at several scales.** Detail is needed at micro, mid and macro scales, and 80/20
  applies at each. Physics must still be followed: the v4 gable clustered its streaks too much.
  Rain should gather mostly at the top floors.
- **Not flat.** Even "clean" surfaces need subtle noise and variation in the base paint, and
  concrete is not uniform either (v5 is "too flat"). Colour fades in the sun, paint chips, and
  materials vary slightly in colour. The user expected concrete, not stucco, on the close-up.
- **Damage must fit the building's age and story.** The v5 parapet chunk is too big and too
  isolated for a fairly new building. Damage should radiate out from the most damaged area,
  getting smaller.
- **Corners and inner edges** collect water, debris and dust, so they wear more.
- **Lighting.** v5 looks like "an old video game" and "a mid-2000s game". v2 and v3 had the
  better render and lighting.
- **Composition.** An empty road between two blocks, or a building on an empty plane, is not
  believable.
- **Seed sheets compare badly.** A lineup at true scale shows "real heights and sizes". A grid
  of independent shots is good for picking variants but "looks like a collage from an asset
  bundle". These are different jobs.

## A correction

Review 31 and round A treated v4's "saturated cream walls" as its main failure. That was my
judgement as team lead, not the user's. In the picks, the user never commented on colour. v4
lost on its intense, uniform streaks and its pristine balcony faces. Its walls also clip to
L\* 99–100, so their texture is gone. The pale over-tint share does not separate the preferred
v2 (29–37 %) from v4 (26–39 %).

## Calibration

The bigger change is lighting. The preferred v3 frames have sunlit walls at L\* 89–96. The
user called v5's walls, at L\* 42–57, dull. In v3 the sun was on the camera's side of the
facade, 40° off its normal, with a textured sky dome. In v5 it raked across the facade away
from the camera.

Threshold changes in `BASE_T`, each with a `[B]` origin:

| Threshold | Round A | Round B |
|---|---|---|
| Surface L\* warn / fail | 90 / 94.4 | 96 / 98.5 |
| Surface L\* low warn | — | 60 |
| Clipped share warn / fail | 0.5 % / 2 % | 25 % / 35 % |
| Base-colour chroma fail | 1.5× | 2.5× (warn still over 1.0×) |
| Pale over-tint warn / fail | 4 % / 10 % | 10 % / 45 % |
| Micro amplitude floor | — | warn below 1.0 L\* mean local std |

Tests that agreed with the picks no better than a coin now report `info`, with the raw verdict
kept in `metrics.raw_status`:
- value grouping, squint, spectral slope, saliency, repetition, depth separation and palette;
- camera, except the bare-plane and void-backdrop checks;
- the stationarity half of `micro_uniformity` on renders. It stays binding on
  `--input-kind variance_map`, where distance and geometry do not mix into the grain.

`--pair` marks rows decided by an info test in brackets.

| Test | Round-A thresholds | Round-B thresholds |
|---|---:|---:|
| value_range | 67 % (12–6) | 81 % (13–3) |
| saturation_budget | 67 % (12–6) | 72 % (13–5) |
| detail_density | 75 % (9–3) | 75 % (9–3) |
| Overall, frame score = 2 × fails + warns | 12–10, 1 tie | 17–4, 2 ties |

**This is in-sample.** The thresholds were fitted to these 23 pairs and one viewer, so 17 of 21
overstates how the critique will do on new renders. The next calibration should test on picks
from a later round. The four remaining disagreements:
- **bay-1 and facade-1:** v2 beat v3 on interest and streaks. v2 warns on saturation, and on
  the facade it also fails detail density.
- **corr-3:** the v2 corridor is in shade at L\* 41 and warns low, but the user liked its
  "subtler lighting". The low-light warn cannot tell a shaded close-up from a dim key.
- **end-1:** v4's gable won on its story; the critique fails its clipped walls.

**What no test measures:**
- streak variety;
- damage that fits the building's age;
- composition and context;
- whether a seed sheet shows true relative scale.

These stay with the A/B questions and the believability critiques table.

## Skill updates

- `procedural-materials/references/weather-and-use.md`:
  - **streak variety:** spacing, partial lengths, wide streaks where water collects,
    intensity and colour by cause, build-up from 3–6 layered opacities, no mid-wall starts,
    no over-clustering;
  - more rain at the top floors;
  - inside corners collect;
  - fading and colour drift, with clean not meaning flat.
- `procedural-materials/SKILL.md`: items 1 and 5 point there.
- `procedural-mesh-damage/SKILL.md`: damage fits the building's age and story, and radiates
  out from a centre.
- `procedural-assets/references/believability.md`:
  - 80/20 at every scale, balanced against physics;
  - damage matched to age;
  - lighting and lookdev, using the v3 and v5 setups;
  - composition and context;
  - the round-B correction on cream;
  - two formats for showing variation;
  - four new rows in the critiques table.
- `procedural-assets/references/art-direction.md`: the two-sided value principle, which tests
  are binding, the round-B table, and next steps.

## Next

Each needs the user's go-ahead:
- **C:** anime-background stylisation as an optional profile. The realistic look stays the
  default.
- **Round 6:** a test run to see whether the streak-variety and lighting guidance changes the
  picture. It costs about 1.5–3 hours of a full Claude Code session on the subscription.
- **Reference set:** 20–40 danchi photos, downloaded with the user's permission, for
  `reference_match`.
