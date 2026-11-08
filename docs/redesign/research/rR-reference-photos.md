# rR: reference photos for frame_critique

2026-10-27. I collected 39 freely licensed danchi photos from Wikimedia Commons. I ran
`procedural-assets/scripts/frame_critique.py` (0.2, round B) on each photo, and then used the photos as
`--ref` targets on the 24 round-B picks (review 33). There are two questions:

- What do real photos measure, and which current thresholds would reject a real photograph?
- Do `reference_match` and `palette` agree with the user's picks once they have references?

Files:
- `docs/redesign/evidence/refs/`:
  - `manifest.json` (sources, authors, licences);
  - `fetch_refs.py` (downloads the images into `img/`, which git ignores);
  - `README.md` (attribution);
  - `measurements.json` (every number below, per photo and per pair).
- The images are not in git.

## 1. The set

The photos were found through the Commons categories *Danchi* (95 subcategories crawled), *Public
housing in Japan*, *Urban Renaissance Agency* and *Tokyo Metropolitan Housing Supply Corporation*,
plus title searches (団地, danchi, Kodan, 県営, 市営住宅, rust and stain categories). That gave about
1,100 JPEGs at least 1600 px wide. I chose the 39 by eye from contact sheets. The rules were:
- daylight;
- 1960s–90s slab or point blocks;
- no watermark;
- no face as the subject;
- one view category per photo.

| Category | Count | Typical content |
|---|---:|---|
| bay (5–15 m balcony or bay close-up) | 6 | balcony grids with laundry, one bay at 5 m, oblique runs |
| facade (across the street, 30–60 m) | 7 | Akabanedai, Todaso, Kurume-Nishi, Musashioka, Soshigaya, Nakatai |
| street (eye height, with context) | 7 | estate roads, crossings, poles and wires, parked cars |
| estate (several blocks) | 6 | rows across rice fields, canals and lawns |
| end (end wall or gable) | 6 | numbered gables, overcast and sunny |
| weathering (streaks, chips, rust) | 7 | Ogikubo and Saginomiya stained walls, a stair entrance, rusted stairs; 2 non-Japanese rust-streak close-ups |

Licences:
- CC BY-SA 4.0: 21
- CC BY-SA 3.0: 3
- CC BY-SA 2.0: 3
- CC BY 2.0: 3
- CC BY 3.0: 3
- CC BY 4.0: 2
- CC0: 3
- PD-self: 1

Commons now serves only standard thumbnail widths, and a `1600px-` URL returns HTTP 400. The API
answer for `iiurlwidth=1600` is the 1920 px thumbnail, so that is what was downloaded. One photo,
Musashioka, is 1600 px at the original size.

Gaps:
- No corridor-side (access gallery) photo good enough was found. The corridor picks are judged against
  balcony-side bays.
- The weathering set has no Japanese rust-streak close-up with a free licence and enough resolution.
- Most photos are overcast or winter light. Only about a third are in direct sun.

## 2. What real photos measure

The **full** columns run the tool as is, on the whole frame. The **wall** columns use the same photo with
`--crop` to the building, because the automatic surface picker often chooses the sky (§3.1). The crops
are listed in `measurements.json`. Micro-grain figures are from the wall crops. Values are given as
median [min–max].

| Category | Surface L\* full | Surface L\* wall | Clipped share | Limit ratio (wall) | Pale over-tint | area_for_80pct | rest_share | p90/p10 | CV | mean local std |
|---|---|---|---|---|---|---|---|---|---|---|
| bay (6) | 84 [74–96] | 84 [74–96] | 0.02 [0–0.09] | 0.24 [0.01–0.62] | 0.01 [0–0.04] | 0.55 [0.34–0.65] | 0.19 [0.06–0.47] | 22 [10–30] | 0.96 [0.87–1.32] | 5.3 [2.7–7.1] |
| facade (7) | 74 [59–95] | 83 [63–97] | 0.02 [0.01–0.14] | 0.33 [0–0.81] | 0.02 [0.01–0.18] | 0.43 [0.37–0.53] | 0.39 [0.21–0.43] | 14 [2.4–24] | 0.72 [0.33–0.89] | 9.6 [4.9–16] |
| street (7) | 56 [43–100] | 73 [59–97] | 0.13 [0.01–0.28] | 0.20 [0–1.00] | 0.02 [0–0.16] | 0.48 [0.42–0.57] | 0.25 [0.15–0.36] | 8.3 [4.3–17] | 0.62 [0.53–0.81] | 8.1 [4.6–10] |
| estate (6) | 82 [47–91] | 82 [68–92] | 0.04 [0–0.09] | 0.46 [0.18–1.04] | 0.01 [0–0.02] | 0.36 [0.27–0.42] | 0.44 [0.31–0.56] | 17 [3.3–36] | 0.56 [0.35–1.96] | 8.2 [1.6–19] |
| end (6) | 86 [67–98] | 66 [55–83] | 0.08 [0–0.34] | 0.29 [0.19–0.49] | 0.01 [0–0.03] | 0.43 [0.34–0.46] | 0.35 [0.28–0.47] | 16 [3.7–45] | 1.19 [0.96–1.29] | 2.9 [1.1–5.9] |
| weathering (7) | 81 [52–100] | 70 [59–85] | 0.05 [0–0.24] | 0.43 [0–1.08] | 0.00 [0–0.05] | 0.55 [0.35–0.73] | 0.16 [0–0.39] | 4.0 [1.5–12] | 0.59 [0.17–1.04] | 4.5 [1.6–18] |
| **all 39** | 83 [43–100] | 80 [55–97] | 0.03 [0–0.34] | 0.33 [0–1.08] | 0.01 [0–0.18] | 0.45 [0.27–0.73] | 0.31 [0–0.56] | 12.5 [1.5–45] | 0.81 [0.17–1.96] | 5.7 [1.1–19.5] |

Full-frame statuses of the binding tests on the 39 photos:

| Category | value_range | saturation_budget | detail_density | micro_uniformity |
|---|---|---|---|---|
| bay | 6 pass | 5 pass, 1 fail | 1 pass, 4 warn, 1 fail | 6 pass |
| facade | 4 pass, 3 warn | 5 pass, 1 warn, 1 fail | 4 pass, 3 warn | 5 pass, 1 info, 1 na |
| street | 1 pass, 4 warn, 2 fail | 5 pass, 2 warn | 3 pass, 4 warn | 7 pass |
| estate | 5 pass, 1 warn | 5 pass, 1 fail | 6 pass | 3 pass, 3 info |
| end | 2 pass, 4 warn | 4 pass, 1 warn, 1 fail | 4 pass, 2 warn | 5 pass, 1 na |
| weathering | 4 pass, 1 warn, 2 fail | 7 pass | 2 pass, 4 warn, 1 fail | 4 pass, 2 info, 1 na |
| **all** | 22 pass, 13 warn, 4 fail | 31 pass, 4 warn, 4 fail | 20 pass, 17 warn, 2 fail | 30 pass, 6 info, 3 na |

**30 of the 39 real photos warn or fail at least one test.** All of them are ordinary photographs of
the subject the generator imitates. Each failure therefore shows either a measuring problem or a
threshold that is wrong for photographs.

Renders of the same kind, for comparison. These are full frame, with no crop. Night shots and texture
sheets are left out:

| Run | Surface L\* | Clipped | Limit ratio | Pale over-tint | area_for_80pct | rest_share | p90/p10 | CV | mean local std |
|---|---|---|---|---|---|---|---|---|---|
| v2 (7) | 91 [41–93] | 0.08 [0–0.15] | **1.83 [0–2.28]** | **0.14 [0–0.37]** | 0.43 [0.27–0.63] | 0.33 [0.10–0.54] | 4.4 [1.6–10] | 0.65 [0.19–2.05] | 7.5 [0.9–13] |
| v3 (7) | 91 [40–96] | 0.01 [0–0.21] | 0.73 [0–0.92] | 0.03 [0.01–0.08] | 0.39 [0.14–0.59] | 0.43 [0.17–0.72] | 3.7 [1.4–14] | 0.70 [0.27–1.45] | 2.5 [0.7–8.9] |
| v4 (6) | **99 [94–100]** | **0.25 [0.11–0.47]** | **1.78 [0.77–2.19]** | **0.20 [0.08–0.39]** | 0.47 [0.22–0.64] | 0.26 [0.06–0.60] | 10 [2.0–67] | 0.64 [0.27–0.88] | 6.9 [4.6–12] |
| v5 (6) | **46 [42–57]** | 0.00 | 0.31 [0.21–0.40] | 0.00 | 0.36 [0.21–0.53] | 0.46 [0.20–0.65] | 5.9 [1.9–12.5] | 0.53 [0.23–1.04] | 3.7 [0.7–8.1] |

What the comparison shows:

- **Colour.** Real danchi walls sit at 0.0–0.8× the Tokyo base-colour limit, with a median of 0.33×.
  Two exceptions reach 1.04× and 1.08×: a beige Chiryu block, and the non-Japanese teal wall. v2's
  and v4's cream and pastel walls, at 1.6–2.3×, are about twice the highest real photo. v1 is at
  2.9–3.0×. v3 and v5 are inside the photo range. Real pale walls are also barely over-tinted: the
  median is 1 %, and the over-10 % cases are sky (§3.6). v2 renders reach 29–37 %.
- **Brightness.** The brightest real wall in a crop is L\* 97.0. No real wall reaches v4's 99–100.
  v5's walls (L\* 42–57) are darker than every real wall crop, whose lowest value is 55. They are
  darker than all but three full frames.
- **Detail.** At bay and close-up distance, real photos are as busy as the renders or busier
  (area_for_80pct 0.55, rest 0.19). Wide views are calmer (estate 0.36 and 0.44; end 0.43 and 0.35).
- **Grain.** Every real wall has measurable grain, with a mean local std of 1.1 L\* or more. p90/p10
  is far above the 3–6 "target band", with a median of 12.5. v3 (median std 2.5) and v5 (3.7) are at
  the smooth end of the photos. Their stationarity, p90/p10 3.7–5.9, is lower than the photo median.

## 3. Thresholds that real photos violate

Each item gives what fails, why, the proposed change, and the in-sample effect on the 23 decisive
round-B picks. The effects were recomputed from each render's metrics with `agree.py`'s rule; the
scratch script is not in the repo. Overall, scoring each frame as 2 × fails + warns, the critique is
at 17–4 (2 ties) now and **17–3 (3 ties)** with changes 3.1–3.8 applied together. The proposals do not
cost agreement overall.

### 3.1 The automatic surface picks the sky (measurement problem)

Six photos have an overcast or hazy white sky that `_sky_grid` does not detect: end_01, end_02, street_03,
street_04, weathering_01 and weathering_02. Wires and branches break the smooth region. The
"brightest large surface" is then the sky at L\* 96–100, which gives 4 `value_range` fails and 2 warns.
On wall crops, the real walls of those photos measure L\* 55–83.

**Change:** do not judge a cluster as a surface if it has:
- `clip_share ≥ 0.4`;
- `y_mean ≤ 0.4`;
- 10 % or more of the top row.

Better, treat clipped or near-white regions connected to the top edge as sky in `_sky_grid`. Checked
on the 39 photos and all 32 renders, the rule removes exactly those six sky clusters and no render
surface. The v4 clipped walls (clip 0.30–0.38, y 0.47–0.50) and the greybox (0.97, y 0.52) are still
judged. There is no effect on the picks.

### 3.2 `surf_L_low_warn` 60 flags overcast and shaded-side photos

Eight full frames sit under L\* 60:
- facade_02: 59;
- street_02, street_05, street_06 and street_07: 43–56;
- weathering_07: 52;
- estate_06: 47, with the wrong cluster chosen.

Wall crops of end_01, end_04, street_05, street_06 and weathering_05 are also at 55–60. These are
normal overcast or shaded-side photographs. All six bay photos are at L\* 74 or more.

**Change:** make the warn depend on the view:
- 60 for bay, close-up and corridor shots, where the user rejected v5's L\* 56 walls;
- 50 for street, facade, estate and end views.

The effect on the picks is none (value_range stays 13–3). v5's street, end-wall and seed frames
(45–47) still warn. Photo warns drop from 8 to 3. Later, the test could compare wall L\* with sky L\*.
An overcast photo has walls well below a bright sky, which a dim render key does not.

### 3.3 Clipped share counts clipped sky

Three photos are over the 25 % warn, and all of them because of white sky:
- end_04: 34 %;
- street_05: 28 %;
- street_03: 27 %.

On wall crops, the highest is 29 %: a sunlit white slab (facade_07), which is a real photo of a real
white wall.

**Change:** compute `clipped_share` on non-sky pixels, or on the judged surface, and keep 25 % warn and
35 % fail on walls. Every real wall stays under 35 %, while v4's 38–47 % still fails. There is no
effect on the picks.

### 3.4 `surf_L_warn` 96 is just under real sunlit white walls

Three real walls are at L\* 96.1–97.0 (bay_05, facade_07, street_01), all white paint in direct sun.
The camera JPEG records them brighter than the albedo table in `realism.md` predicts, because of
exposure and the tone curve. The 98.5 fail is confirmed: no real wall exceeds 97.0.

**Change:** set `surf_L_warn` to 97.5. In `realism.md`, add that the "never above L\* 94.4" ceiling
describes albedo under a linear exposure, not a photographic JPEG. There is no effect on the picks: v3's
95.9 passes either way, and v4 at 99 fails either way.

### 3.5 `crush_warn` 2 % flags sunny high-contrast photos

Six photos have 2.0–4.6 % of pixels crushed (end_01, end_05, facade_05, facade_07, street_07, and the
estate_02 crop). These are dark foliage, doorways and backlit trees in sun.

**Change:** set it to 5 %, or measure it outside vegetation. The in-sample cost is one pair: seeds-1
becomes a tie, because v4's 9-up sheet warns only on 3.1 % crushed black. I would still make the
change, because crushed shadows of that size are normal in photographs. The overall score above keeps
2 %; with 5 % it is 16–3.

### 3.6 The accent share counts sky and vegetation

`saturation_budget` fails on 4 photos and warns on 1 because of the high-chroma share:
- facade_07: 26 %, a sunlit lawn (median hue 117°);
- estate_04: 16 %, a rice field;
- end_05: 11 %, deep blue sky the sky detector missed (hue 286°);
- bay_05: 10 %, grass;
- end_04: 8 %, blue sky.

None of these are facade accents.

**Change:** exclude vegetation from the accent share by hue (about 90–170°) at any lightness. The
`segment_surfaces` rule (L\* < 70) misses sunlit grass. Also exclude saturated blue regions connected
to the top edge. Renders
have a 0–4 % high-chroma share, so there is no effect on the picks. The pale over-tint warns
(facade_02 18 %, street_02 16 %, street_06 16 %) are tinted overcast sky: about 80 % of those pixels
lie in the top third of the frame. Fix 3.1 should remove them.
Keep 10 % warn and 45 % fail.

### 3.7 `detail_density` is a wide-view rule applied to close-ups

19 of the 39 photos warn or fail, mostly bay, weathering and street views. Bay photos need 55 % of the
frame for 80 % of the detail (up to 65 %). Weathering photos need 55 % (up to 73 %), and their rest
share is 0.16. A balcony grid at 10 m fills the frame with real detail. Wide views fit the current
numbers: estate 0.36, end 0.43, facade 0.43.

**Change:** set thresholds by view:

| View | area_for_80pct pass ≤ | fail > | rest warn < |
|---|---:|---:|---:|
| bay, close-up, corridor, weathering | 0.60 | 0.70 | 0.12 |
| street | 0.55 | 0.65 | 0.20 |
| facade, estate, end, seed sheet | 0.45 (unchanged) | 0.62 | 0.30 |

With these, photo warns and fails drop from 19 to 4. They are bay_05, weathering_01, weathering_04
(a uniform aggregate close-up) and street_06.

The in-sample cost is real. detail_density goes from **9–3 to 3–1**. The bay agreement came from v4
and v5 bays at 0.50–0.53 against v2 and v3 at 0.43–0.44. That gap is smaller than the spread between
real bay photos (0.34–0.65). The user's notes blame those bays on streaks and lighting, not on how
detail is spread. I think the 9–3 was mostly coincidence. Overall agreement holds (17–3), because
value_range carries the bay pairs. The v2 facade (a80 0.63, rest 0.10) still fails. It is busier
than any facade photo (at most 0.53, rest at least 0.21), which matches the user's facade-1
disagreement noted in review 33.

### 3.8 `micro_uniformity`: the floor holds, the stationarity targets are too narrow

- **Amplitude floor 1.0 L\*:** confirmed. The smoothest real wall is a sunlit gable (end_05) at 1.14.
  Keep the floor binding.
- **Stationarity:** p90/p10 or kurtosis fail on facade_03 (2.4, kurtosis 3.5), weathering_04 (1.5,
  3.0) and weathering_05 (1.6, 3.7). The CV is under 0.4 on 4 photos. Real photos range from 1.5 to
  45 in p90/p10, so "3–6" is not a band that photos sit in. Keep stationarity as info on renders, as
  round B decided.
- **Wording:** change the "target 3–6" text to "at least 3 on clean paint; photos run from 3 to 30".

There is no effect on the picks: stationarity is already info.

### 3.9 Base-colour limit: photos support it, the picks do not

There is no photo violation to fix: all Japanese walls are at or under 1.04×. The photos do support
the Tokyo standard, with warn at 1.0×. On photo evidence alone, a fail near 1.5× (twice the highest
real wall) would be justified. That would fail v2, which the user preferred. Keep 2.5× until the
hold-out picks. Add to the `paint_fail_ratio` origin that real danchi photos measure 0–1.04×.

## 4. reference_match and palette against the picks

For each pick pair, both images were scored with `--ref` set to the photos of the matching category:

| Pick group | Reference photos |
|---|---|
| bay, corridor | bay (6) |
| close-up | bay and weathering (13) |
| end | end (6) |
| facade | facade (7) |
| seed sheet | estate (6) |
| street | street (7) |

I used frame_critique's own `t_reference`, `t_palette` and `calibrate` on cached frames. This was
checked against the CLI on the v3 hero street with the street refs: emd_L 9.88, emd_C 3.53 and
palette dE 10.0 in both. Agreement uses `agree.py`'s rule: the share of decisive pairs where the
winner has the better status, with `info` counted as a tie.

| Test | Agree | Disagree | Tie | Rate |
|---|---:|---:|---:|---:|
| `reference_match` status, current thresholds (EMD L\* 8/15, C\* 5/10) | 9 | 1 | 13 | **90 %** |
| `reference_match` status, proposed (L\* 13/20, C\* 10/15) | 11 | 4 | 8 | 73 % |
| same, without corridor and seed-sheet pairs (current / proposed) | 8 / 10 | 1 / 1 | 9 / 7 | 89 % / 91 % |
| `reference_match` emd_L (lower wins) | 14 | 9 | 0 | 61 % |
| `reference_match` emd_C (lower wins) | 13 | 10 | 0 | 57 % |
| `palette` status (as agree.py) | 0 | 0 | 23 | — |
| `palette` raw status | 0 | 2 | 21 | 0 % |
| `palette` reference dE (lower wins) | 10 | 13 | 0 | 43 % |

Per-pair results. W is the winner, L the loser, and values are (emd_L, emd_C). Proposed thresholds are
in the last column.

| Pair | Refs | Winner | Loser | ref_match W / L | Palette dE W / L | Current | Proposed |
|---|---|---|---|---|---|---|---|
| bay-1 | bay | v2 bay_lit | v3 bay_9m | warn (7.9, 6.9) / fail (15.7, 5.7) | 11.3 / 10.8 | agree | agree |
| bay-2 | bay | v2 bay_lit | v4 bay_close | warn (7.9, 6.9) / fail (21.0, 5.6) | 11.3 / 12.0 | agree | agree |
| bay-3 | bay | v2 bay_lit | v5 bay_street | warn (7.9, 6.9) / fail (17.2, 5.9) | 11.3 / 13.4 | agree | agree |
| bay-4 | bay | v3 bay_9m | v4 bay_close | fail (15.7) / fail (21.0) | 10.8 / 12.0 | tie | agree |
| bay-5 | bay | v3 bay_9m | v5 bay_street | fail (15.7) / fail (17.2) | 10.8 / 13.4 | tie | tie |
| bay-6 | bay | v5 bay_street | v4 bay_close | fail (17.2) / fail (21.0) | 13.4 / 12.0 | tie | agree |
| close-1 | bay+weath | v2 piece | v1 closeup | warn (10.2, 5.2) / warn (11.3, 4.9) | 11.7 / 11.5 | tie | tie |
| close-2 | bay+weath | v3 piece | v2 piece | warn (10.4, 4.0) / warn (10.2, 5.2) | 9.9 / 11.7 | tie | tie |
| close-3 | bay+weath | v3 piece | v5 parapet | warn (10.4, 4.0) / fail (16.0, 5.8) | 9.9 / 12.9 | agree | agree |
| close-4 | bay+weath | v2 piece | v5 parapet | warn (10.2, 5.2) / fail (16.0, 5.8) | 11.7 / 12.9 | agree | agree |
| corr-1 | bay | v2 corridor | v4 corridor | fail (23.0) / fail (16.1) | 16.2 / 13.3 | tie | disagree |
| corr-2 | bay | v5 corridor | v4 corridor | fail (22.6) / fail (16.1) | 15.1 / 13.3 | tie | disagree |
| corr-3 | bay | v2 corridor | v5 corridor | fail (23.0) / fail (22.6) | 16.2 / 15.1 | tie | tie |
| end-1 | end | v4 gable | v5 end wall | fail (25.6, 10.5) / fail (17.1, 7.2) | 16.9 / 16.0 | tie | disagree |
| facade-1 | facade | v2 facade | v3 facade | warn (11.2, 7.3) / warn (11.1, 7.9) | 12.5 / 12.1 | tie | tie |
| seeds-1 | estate | v2 9 seeds | v4 9-up | warn (11.3, 9.0) / fail (13.2, 13.2) | 16.1 / 15.0 | agree | agree |
| seeds-2 | estate | v5 9-up | v4 9-up | fail (26.0) / fail (13.2) | 17.9 / 15.0 | tie | disagree |
| seeds-3 | estate | (tie pick) v5 9-up | v2 9 seeds | fail / warn | 17.9 / 16.1 | — | — |
| street-1 | street | v3 hero | v4 hero | warn (9.9, 3.5) / fail (18.1, 6.2) | 10.0 / 12.2 | agree | agree |
| street-2 | street | v5 street | v4 hero | fail (18.1, 5.3) / fail (18.1, 6.2) | 13.5 / 12.2 | tie | tie |
| street-3 | street | v3 hero | v5 street | warn (9.9, 3.5) / fail (18.1, 5.3) | 10.0 / 13.5 | agree | agree |
| street-4 | street | v5 street | v2 SE | fail (18.1) / fail (15.8) | 13.5 / 11.9 | tie | tie |
| street-5 | street | v5 street | v1 estate | fail (18.1, 5.3) / warn (13.5, 2.9) | 13.5 / 11.2 | **disagree** | tie |
| street-6 | street | v3 hero | v2 SE | warn (9.9, 3.5) / fail (15.8, 7.0) | 10.0 / 11.9 | agree | agree |

**What this says:**

1. **reference_match is the best-agreeing test so far, but its current thresholds reject the photos
   themselves.** Each photo was scored against the other photos of its own category (leave-one-out):
   - emd_L: median 10.5, p90 13.9, max 19.1;
   - emd_C: median 7.0, p90 10.6, max 21.1.

   With warn at 8 and 5, every one of the 39 photos warns or fails against its own category (33 warn,
   6 fail). Almost every render fails, so 13 of 23 pairs tie fail–fail.

   **Proposed:** `ref_emd_L` warn 13 / fail 20 and `ref_emd_C` warn 10 / fail 15, about the leave-one-out
   p90 and maximum. Photos then score 30 pass, 7 warn and 2 fail. Pick agreement is 11–4.
   Three of the four new disagreements come from references that do not fit the view. corr-1 and
   corr-2 compare corridor renders with balcony-side photos, and there are no corridor photos.
   seeds-2 compares a contact sheet of nine renders with estate photos. The fourth, end-1, is the v4
   gable that won on its story despite its blown walls.

   Without the corridor and seed-sheet pairs, the result is 10–1 proposed and 8–1 current. I would
   make `reference_match` binding at the proposed thresholds, but not for seed sheets, and not for
   corridor views until corridor-side photos are added.
2. **palette carries no signal.** As agree.py counts it, every pair ties, because palette is info
   whenever it is not a pass. The raw status disagrees 0–2. Ranking by palette distance agrees 10–13,
   below chance. Real photos against their own category sit at dE 11.8 median (p90 16.2, max 23.2),
   and renders at 9.9–17.9: the same range. A 6-colour k-means palette distance does not tell renders
   from photos at this scale. Keep palette as info. If its distance is kept, set `ref_dE_warn` to 17
   and fail to 25, so that real photos pass.
3. **The distance that agrees is the value histogram, not colour.** emd_L agrees 14–9 and emd_C
   13–10. The renders that lose to the photos are v4 (blown) and v5 (dim). The value-histogram
   distance sees the same thing as `value_range`.

## 5. Caveats

- **JPEG processing.** The photos are camera JPEGs: tone curve, sharpening and noise reduction, then
  Commons' thumbnail resampling (1920 px, Lanczos, re-encoded). The pixel-scale grain band that
  `micro_uniformity` measures includes sharpening halos, chroma noise and block artefacts. The renders
  are Karma output with their own denoiser. Grain numbers compare processes as much as surfaces.
- **Exposure.** Each photographer exposed for their own scene. Overcast frames are exposed for the
  sky or the wall, sunny frames often for the sky, and several phone photos have auto HDR. Absolute
  L\* is the photographer's choice. That is why the brightness thresholds are read as ranges, not
  targets.
- **Light and season.** Most photos are overcast or winter. Photos in direct sun, as in v3's
  lighting, are about a third of the set, so the "sunlit wall" statistics rest on few frames.
- **Sample size and selection.** Each category has only 6–7 photos, chosen by me from about 1,100,
  and leave-one-out on 6 photos is noisy. The pick results are in-sample on one viewer's 23 decisive
  pairs. Every agreement figure here, including the proposed-threshold effects, is fitted to those
  pairs and overstates generalisation.
- **Category fit.** There are no corridor-side photos. The weathering close-ups mix two non-Japanese
  rust walls with Japanese stained walls. Seed contact sheets are not photographs, so no photo
  reference fits them.
- **Masks.** The wall figures come from hand-placed rectangular crops, not wall masks. The automatic
  surface picker still chooses the brightest cluster inside the crop. In a few crops (end_01, end_04)
  that is a shaded gable, not the sunlit face. A Karma-style wall mask cannot be made for a photo.
  With more time, painted PNG wall masks for the 39 photos would give cleaner wall statistics.
- **Licences.** The images are used only for measurement, and none is redistributed in the repo.
  `README.md` carries the attribution needed if any is shown or published.

## 6. Applied

2026-10-27, `frame_critique.py` 0.3 (round R). All of §3 and §4 is implemented. Each moved number
has an `[R]` origin in `BASE_T` or `VIEW_OVERRIDES`.

- **`--view close|corridor|street|wide|sheet`.**
  - The default is `wide`, and `--grid` implies `sheet`.
  - Low-light warn is 60 on `close` and `corridor`, and 50 on the other views.
  - `detail_density` uses the §3.7 table.
  - `reference_match` is binding except on `corridor` (no corridor photos yet) and `sheet`.
- **Sky (§3.1).** `_sky_grid` also takes clipped or near-white regions that are:
  - low in texture (local std under 2.5 L\*);
  - connected to the top edge;
  - centred in the upper 35 % of the frame.

  The cluster rule stays as a backstop.
- **Other moves:**
  - clipping is measured on non-sky pixels (§3.3);
  - `surf_L_warn` is 97.5 (§3.4);
  - `crush_warn` is 5 % (§3.5);
  - the accent and pale over-tint shares leave out vegetation by hue, and blue regions on the top
    edge or next to the detected sky (§3.6);
  - the micro wording is fixed (§3.8);
  - the `paint_fail_ratio` origin carries the photo range (§3.9);
  - `ref_emd_L` is 13/20, `ref_emd_C` 10/15 and `ref_dE` 17/25 (§4).
- **Docs.** `realism.md` notes that the L\* 94.4 ceiling is albedo, not a JPEG.
  `art-direction.md` §2 covers `--view` and the photo set, and §5 has a round-R table.
- **`agree.py`.** It passes `--view` per pick group and `--ref` photos of the matching category from
  `--refs DIR` (default `docs/redesign/evidence/refs/img/`). It caches by image, view and
  reference set, invalidated by tool version. It runs the tool with `python -I`.

One change goes beyond §3.6. The sky fix in §3.1 did not remove the three pale over-tint warns, as
I had expected it to. Those pixels are pale blue sky behind wires (hue 237–278°, C\* 9–15), not
near-white. So the blue-sky mask also applies to the pale over-tint share, and it counts blue
next to the detected sky. A deep blue sky in end_05 sat below a detected strip of sky without
touching the top edge.

Photos, binding tests only, worst status per photo. Before is round B with no view. After is round
R with bay and weathering as `close`, street as `street`, and the rest as `wide`.

| Category | n | Before: pass / warn / fail | After: pass / warn / fail |
|---|---:|---|---|
| bay | 6 | 1 / 4 / 1 | 5 / 1 / 0 |
| facade | 7 | 2 / 4 / 1 | 4 / 3 / 0 |
| street | 7 | 0 / 5 / 2 | 4 / 3 / 0 |
| estate | 6 | 4 / 1 / 1 | 5 / 1 / 0 |
| end | 6 | 1 / 4 / 1 | 4 / 2 / 0 |
| weathering | 7 | 1 / 3 / 3 | 4 / 2 / 1 |
| **all** | 39 | **9 / 21 / 9** | **26 / 12 / 1** |

By test:
- `value_range`: before 22 pass, 13 warn, 4 fail; after 35 pass, 4 warn.
- `saturation_budget`: before 31 pass, 4 warn, 4 fail; after 39 pass.
- `detail_density`: before 20 pass, 17 warn, 2 fail; after 30 pass, 8 warn, 1 fail.

What still warns or fails:
- **`detail_density`, wide views (5 photos).** Facade and end frames sit at 0.46–0.53, just over
  the unchanged 0.45. The facade photos suggest about 0.55 for `wide`, but I left it, as decided.
  v2's facade at 0.63 fails either way.
- **`detail_density`, other views (4 photos):**
  - bay_05, a balcony grid at 0.65;
  - street_06 at 0.57;
  - weathering_01, with rest 0.08;
  - weathering_04, a uniform aggregate close-up that fails at 0.73.
- **Low light (4 photos):**
  - street_05 at L\* 41 and street_07 at 45, overcast;
  - estate_06 at 47, where the wrong cluster is chosen;
  - weathering_07 at 52, a shaded wall under the `close` limit of 60.

Renders, all 32:
- No sky mask, judged surface or surface L\* changed.
- The pale over-tint is unchanged. The high-chroma share fell only on v4's cause field (4.4 → 2.2 %)
  and v1's close-up (0.7 → 0.1 %).
- Three statuses changed at the default view:
  - v4's 9-up sheet and v2's night shot pass `value_range` under the 5 % crush limit;
  - v5's bay at L\* 56 passes `value_range` at the `wide` default. It still warns with
    `--view close`, as `agree.py` runs it.

Agreement, `agree.py` with the 39 photos (in-sample: same 23 decisive picks, one viewer):

| Test | Round B | Round R |
|---|---:|---:|
| `value_range` | 13–3 | 12–4 |
| `detail_density` | 9–3 | 3–1 |
| `saturation_budget` | 13–5 | 13–5 |
| `micro_uniformity` | 1–0 | 1–0 |
| `camera` | 0–1 | 0–1 |
| `reference_match` | — (no photos) | 10–1, 12 ties |
| `palette` | — | 0–0, all ties (info) |
| other tests | info | info |
| **Overall, 2 × fails + warns** | **17–4 (2 ties)** | **17–2 (4 ties)**; 16–3 without photos |
