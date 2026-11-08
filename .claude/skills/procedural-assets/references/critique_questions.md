# A/B art-director questions for a VLM or agent pass

Use this after `frame_critique.py` has run on both images. It is the r5-meta T13 pass: a
fixed rubric, two images at a time, with the numbers attached. Profile: realistic unless the
art bible says otherwise.

## How to run it

1. **Inputs.** Give the model:
   - image A and image B at the same size (about 1024 px wide);
   - the `--pair` table from `frame_critique.py --pair A B --json pair.json`;
   - the diagnostic sheet (`--sheet`);
   - the level's art-bible line, for example "danchi street view, overcast-to-sunny
     afternoon, eye height, photographic".
2. **Run it twice, swapping A and B**, to cancel position bias. Keep only the answers that
   agree in both orders. Where they disagree, record "no preference".
3. **Answer every question** with A, B or "same", plus one sentence. Each note says the
   principle, where it is (a cell on a 4x4 grid, rows 1-4 from the top, columns a-d from the
   left, e.g. "2c"), and the fix.
4. **Leave counting and fine geometry to the numbers.** The model must not judge counts,
   overlaps, small alignments, exact values, clipping, saturation percentages or
   repetition periods. Where a question touches these, it quotes the numeric test instead.
5. **Spend samples on verifying.** If an answer contradicts a numeric test, look at the
   matching diagnostic panel and say which one is wrong.

## The questions

### Read (first glance and thumbnail)
1. What do you see first in each image? Is that what the shot is for?
2. Squint, or look at the 3-value panel. Does each image still read as a building in a
   place? Which one has fewer, larger, clearer value shapes?
3. At thumbnail size, does the subject's silhouette name the building type (a slab danchi,
   a tower, a shop row) without the detail?
4. Where does the eye rest? Is there a quiet area, and does it sit next to the busy one so
   that the busy one reads?

### Value
5. Which image has the more believable light: a sunlit side that is bright but not white,
   shadows that keep detail, and sky and wall that do not merge? Quote `value_range` for
   clipping. Do not estimate it.
6. Is the darkest dark and the lightest light where the shot needs them (the focal area),
   or are they spent on a sky hotspot, a white AC unit or a window glint?

### Colour
7. Which palette reads as a photograph of this place? Look at weathered concrete and paint,
   tinted by the light, against a sky that sets the key. Name any surface that looks like
   plastic or a toy (pale cream, candy pastels, uniformly saturated laundry).
8. Do accents (laundry, signs, rust) sit where the story is, or are they sprinkled evenly?
   Quote `saturation_budget` for shares.
9. Does colour change with distance (bluer and paler far away), or is the far building the
   same colour as the near one? Quote `depth_separation` if there is a depth AOV.

### Composition and camera
10. Is the camera at a human eye height, at a focal length a photographer would use here?
    Does it look up, down or straight? Quote `camera` for lean and horizon. Do not measure
    angles yourself.
11. Is there one leading line into the subject (a kerb, a wire run, a balcony edge), and
    does the frame have a foreground, a middle ground and a background?
12. What tells the scale (people, bikes, doors, poles, trees)? Would this pass as a
    miniature model? (Aerial views over a bare plane, tilt-shift blur and spotless ground
    all read as models.)

### Believability (surfaces and ground)
13. Which surface in each image is least believable? Give its grid cell, and say why: too
    clean, too even, too saturated, wrong scale of texture, or edges too crisp.
14. Does the ground meet the building the way it would in a photograph (a splash band, a
    debris line, planting, kerbs), or is the base clean?
15. Do context props (trees, poles, fences, cars) meet the same bar as the hero? Name any
    that are faceted, boxy or floating.

### Repetition and variation
16. Does anything look stamped: the same streak hatch under every coping, the same laundry
    on every balcony, the same window state? Say where it shows. The numbers
    (`streak_evenness`, `repetition`) decide how much; you decide whether it shows.
17. Across floors and bays, is variation grouped (a few neglected flats, one repainted bay,
    worse columns under leaking sills), or spread evenly like noise?
18. For a seed sheet: which two seeds look most alike, and which one is broken?

### Story
19. In one sentence, what happened to this building over 40 years? Which three marks tell
    you (a leak, a repaint, a retrofit, a hand-worn rail)? If you cannot name a story,
    say "no story".
20. Do the wear, dirt and clutter share causes (water from a sill making a streak, algae
    and a pale washed band), or were they placed independently?

### Verdict
21. Which image is more photographic overall: A, B or same? Give the single change to the
    loser that would help most, as principle, location and fix.
22. List any answer above that disagrees with a numeric test, with both readings.

## What the model must not do

- Count elements, measure angles, estimate percentages, or judge thin-line alignment,
  overlaps and interpenetration. The numeric tests and geometry checks cover these.
- Score with a single number. Each question gets its own answer.
- Paint over or describe a new design. Notes are principle, location and fix.

## Output format (JSON lines, one per question)

```json
{"q": 7, "pick": "B", "both_orders": true, "cell": "2b",
 "note": "A's sunlit wall is pale cream that reads as plastic; desaturate the paint toward a grey-beige and lower exposure (value_range FAIL, pale over-tint 34 %)"}
```
