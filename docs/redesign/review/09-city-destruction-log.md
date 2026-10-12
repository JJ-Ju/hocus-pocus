> **Status: historical.** Evaluation record of 1.0 at commit `d18a621` on 2026-10-12. See [`../README.md`](../README.md).

# 09 — City destruction log: fracture + SOP-level RBD sim driven through HocusPocus 1.0

**Seat:** an AI agent working as a Houdini FX TD. I used only the MCP tool surface, `docs/tools.md` and review 08. I did not read the server source.
**Build:** `redesign/v1` @ `d18a621`, bridge `1.0.0a0`, profile `core`.
**Host:** the same Houdini FX 22.0.466 GUI, pid **63324**, that review 08 launched. It is still owned by review 08's persistent driver (`<scratch>/city/drv.py`, bridge `hocuspocus-mcp` pid 59528). `houdini_status` showed it connected with `city_v01.hip` loaded, so I reused that driver and did not launch or attach anything. I added a thin wrapper, `<scratch>/city/j.sh` → `c9.sh`, that drops requests into the same inbox and logs to `<scratch>/city/d9/calls.log`.
**Date:** 2026-10-12, about 10:05 to 10:15 local time (roughly 10 minutes of wall clock).
**Result:** 30 district buildings were fractured into **1,351 concrete pieces**. Three meteors hit them in a **96-frame** Bullet sim (frames 1–96), and the district collapses into rubble. A full sim recook takes **4.5 s**. The scene had **0 errors** (2 benign merge warnings) and needed **0 `houdini_python` calls**. The scene is saved as `<scratch>/city/city_v02_destruction.hip` (1,470,276 bytes, `dirty: false`). Evidence is in `docs/redesign/evidence/city-destruction/` (§4).

Byte counts are the size of the pretty-printed `structuredContent` (indent 1), as in review 08.

---

## 1. What I built

### `/obj/destruction` (geo)

```
IN_BUILDINGS (object_merge /obj/city_gen/OUT_BUILDINGS)
  ├─ district_only (blast group=district, negate)   22,162 polys, 30 buildings, bbox 185 x 93 x 184
  │    └─ fracture (rbdmaterialfracture::4.0, concrete, fractureperpiece=1, 1 level, scatterpts 45, seed 7)
  │         └─ cfg_pieces (rbdconfigure, inputs = fracture outputs 0/1/2, adddensity1 + addbounce1 -> density 1000, bounce 0.25)
  │              ├─ out0 ───────────────────────────────┐
  │              └─ out1 (glue constraints, 5,349 prims) -> weak_glue (wrangle: f@strength *= 20)
  └─ static_bldgs (blast group=district)             161 untouched buildings -> solver collision input
meteor_pts (detail wrangle: 3 points with vel + pscale 12/9/9)
meteor_shape (sphere polymesh) -> meteor_copy (copytopoints) -> meteor_name (assemble, prefix "meteor")
  -> meteor_vel (point wrangle: v from nearest launch point, input 1 = meteor_pts) -> cfg_meteor (rbdconfigure, userdensity 20000)
rbd_geo (merge cfg_pieces + cfg_meteor: 1,354 packed fragments)
rbd_solver (rbdbulletsolver: 0 = rbd_geo, 1 = weak_glue, 3 = static_bldgs; useground=1, substeps 5)
  -> OUT_SIM (null, commented, green)
OUT_SIM + static_bldgs + IN_GROUND (object_merge OUT_GROUND) -> scene_merge -> OUT_DISPLAY (display/render)
```

- **Meteors:** these are three packed spheres with an initial `v`. Meteor A has radius 12 and speed 140 m/s. It is aimed at (0,40,0) and reaches the towers around frame 25. Meteors B and C have radius 9 and speeds of 110 and 85 m/s, and they hit around frames 40–60. Their density is 20,000 versus 1,000 for concrete, so they plough through the district.
- **Glue:** `rbdmaterialfracture` produced glue strengths from 2,005 to 17,998 (mean 10,030). That figure comes from `geo_read` with `stats`. I scaled them ×20 so the towers stand under gravity until a meteor hits, and then they crumble and topple. The comments on `OUT_SIM`, `weak_glue` and `meteor_pts` record these choices inside the hip.
- **Other changes:** `/obj/city_gen` display is off, so the original district does not overlap the sim. The playbar range is 1–96 and the current frame is left at 72.
- **New objects:** `/obj/cam_district` (t 205,115,205, r -24,45,0, 35 mm), `/obj/sun` (hlight, distant, intensity 2) and `/obj/sky` (envlight 0.6).
- **New ROP:** `/out/ogl_gif`, an OpenGL ROP using `cam_district` at 480×270 that writes `$HIP/d9/gif/gif_$F3.png`.

### Sim stats

| | |
|---|---|
| RBD pieces | 1,351 concrete fragments + 3 meteors = **1,354** packed prims (45 per building ×30, minus a few empty cells) |
| Constraints | 5,349 glue prims |
| Static colliders | 161 buildings (convex hull) + ground plane |
| Frames | 1–96, 24 fps, 5 substeps |
| Cook time | **4.50 s** for a full recook of frames 1–96 after `resetsim` (job `elapsed_s` 4.55, `cook_time_ms` 4497.2). The first, cold cook was 5.79 s (`cook_time_ms` 5794.3). |
| Motion check (`geo_info` bbox of OUT_SIM) | f1 max y 229 (meteors in the sky). f24 155.6. f48 104.6 (the tallest tower is 93 m, so debris is thrown up). f72 111.3. f96 110.9, with x/z spread to 209.6/166.5 as meteors bounce out. The prim count stays at 1,354 throughout. |

Sim quality notes: the bbox min y reaches -5.2, so a few pieces sink through the ground plane at 5 substeps. The meteors render grey because `Cd` did not survive packing. Neither problem was worth fixing for a test.

---

## 2. Tool calls

**67 tool calls** through the persistent driver, with 1 error (rc=1). Wall clock was about 10 min.

| Tool | Calls | Avg bytes | Notes |
|---|---:|---:|---|
| viewport_capture | 13 | 506 (+image) | All `source: opengl_rop` with a camera, and all framed correctly. 4 were test shots. |
| geo_info | 12 | 1,690 | Bigger than in review 08: packed geometry adds `intrinsics.packed` bounds. Useful for the meteors. |
| geo_read | 6 | 573 | `stats` + `count:1` found the zero-`v` bug and the glue strength range in one call each. |
| parm_set | 5 | 575 | Includes `press: true` on `resetsim`, which worked. |
| node_type_info | 5 | **15,545** | rbdmaterialfracture 25.9 KB, rbdbulletsolver 25.5 KB, opengl 12.8 KB, rbdconfigure 11.4 KB, assemble 2.1 KB |
| node_create | 5 | 5,918 | 14-node graph in one call (17.8 KB), wired to output 1/2 of HDAs. 1 error (below). |
| render | 4 | 2,320 | 24-frame renders return 4 KB, almost all of it output paths. |
| cook | 4 | 394 | One escalated to a job. |
| job | 2 | 335 | status + result |
| problems | 2 | 749 | |
| node_edit | 2 | 1,067 | |
| time | 2 | 99 | |
| node_type_search, node_layout, node_connect, houdini_status, hip_save | 1 each | 12,989 / 1,993 / 542 / 1,403 / 286 | |

**Total structured bytes:** about 173 KB, plus 13 capture images and 4 render thumbnails. The four RBD/ROP `node_type_info` calls plus one `node_type_search` were **88 KB, half of everything**.

---

## 3. `houdini_python` uses

**None.** Every step was covered by a typed tool:

| Step | Tool |
|---|---|
| Building the graph, including wiring to HDA outputs 1 and 2 | `node_create` |
| Pressing the solver reset button | `parm_set press` |
| Running the long sim | `cook` → `job` |
| Rendering a frame range | `render` |
| Setting the playbar | `time` |

The brief allowed a Python frame loop as a fallback. It was not needed.

---

## 4. Evidence (`docs/redesign/evidence/city-destruction/`)

| File | Source | Size |
|---|---|---|
| `10_sim_f001.png` … `14_sim_f096.png` | `viewport_capture`, `opengl_rop`, `cam_overview`, 960×540, frames 1/24/48/72/96 | 453–461 KB each |
| `15_district_f072.png` | same, `cam_district`, f72 | 543 KB |
| `16_district_f036.png` | same, `cam_district`, f36 (extra: towers mid-topple) | 566 KB |
| `17_street_f060.png` | same, `cam_street`, f60 (extra) | 187 KB |
| `20_contact_sheet.png` | Pillow, 3×2 grid at 480×270 per cell: f1, f24, f48, f72, f96 overview + district f72. 1440×810, palettised | 268 KB |
| `21_destruction.gif` | Pillow, from `render` of `/out/ogl_gif`, frames 1–93 step 4 = 24 frames, 480×270, 125 ms/frame, 128 colours | 2.0 MB |

**`render` timing:** 24 OpenGL frames (1–93, step 4) of the full city plus the sim took about **4 s** wall clock, with the sim already cached. It returned synchronously within `wait_s: 60`, with all 24 outputs and the thumbnail attached. A single frame (45) also came back in about 1 s.

---

## 5. Errors and surprises (exact messages)

**Tool errors (isError):**
1. `node_create` with `{"parent":"/obj","type":"distantlight"}`:
   `node_type_not_found: "Item 0: No Object node type 'distantlight' (parent /obj)."`, with hint `distantlight is a Lop node type, but /obj holds Object nodes.`, candidates `indirectlight, ambient, envlight`, and `rolled_back: true` (the envlight in the same call was not left behind). **The hint helped.** It explained exactly why the type was missing. The candidates missed the obvious answer, though: `hlight` (label "Light") with `light_type: distant`. I knew it from experience, and my retry worked first time. Matching candidates on labels as well as names would have found it.

**Non-error surprises and observations:**
1. **`node_type_info` lists only one output for multi-output HDAs.** `rbdmaterialfracture::4.0`, `rbdconfigure` and `rbdbulletsolver` each report `"outputs": [{"index":0,...}]`. Each really has 3 outputs (geometry, constraints, proxy). `node_create` wired `fracture` output 1 and 2 into `cfg_pieces` without complaint, and the constraints arrived (5,349 glue prims), so only the description is wrong. An agent trusting `node_type_info` would conclude that the constraint output does not exist and build constraints another way.
2. **The opaque-cook-to-job escalation worked well.** `cook {frame:96, timeout_s:2}` on `OUT_SIM`, after a reset, returned in about 3 s with `job_id`, `state: running` and a clear message: *"Cooking /obj/destruction/OUT_SIM is taking longer than 2s; poll with job {action: status, ...}"*. `job status` → `done`, and `job result` returned the original cook block, with `cook_time_ms` 4497.2. This time the cook time was honest, because the solver actually recooked. Two gaps:
   - `progress` is only 0 or 1. There is no "frame 37/96" while a sim runs, so for a long sim an agent is polling blind.
   - `cook` on `fracture` after creation reported `cook_time_ms: 0.1`, because `node_create` had already cooked it. I never learned what the fracture costs, which is the number a TD wants when tuning scatter counts. This is the same issue as review 08 §4.3.
3. **`render` worked well on the heavy scene.** It ran synchronously within `wait_s`, returned all outputs and attached the thumbnail. Two issues:
   - **The finished result has no `state` field** (`{rop_path, frames, outputs, thumbnail, job_id}`), even though `state` is documented. A client that checks `state == "done"` will misread it.
   - **`outputs` lists all 24 absolute paths:** 4 KB of 4.0 KB. A `{pattern, count, first, last}` summary would do.
4. **A plain OpenGL ROP renders black in a scene with no lights, but `viewport_capture`'s `opengl_rop` source does not.** My first GIF pass was 24 silhouettes: RGB max 5, alpha correct. `viewport_capture` had lit the same scene, presumably with a temporary light or headlight. Nothing in either tool says so. The render thumbnail was attached, but `render` gave no warning about a near-black image. I added `/obj/sun` + `/obj/sky` and re-rendered. A `notes` entry such as "scene has no lights; OpenGL ROP output will be unlit" would have saved a pass.
5. **`node_create` echo size.** The two lights returned 5.1 KB, mostly ramp keys and `s`/`scale`/`dimmer` reported as `is_default: false` on freshly created lights. These are values the light's creation script sets, not values I set. The 14-node graph returned 17.8 KB including the VEX snippets again. This is review 08's suggestion 4, still valid.
6. **`problems` correctly kept reporting a real merge warning.** It reported `rbd_geo: A mis-match of attributes ... i.e.: bounce, v, density.` A `cook force` confirmed it is current, not stale. The warning is benign: only the meteors carry `v`, and missing `v` initialises to 0 as intended. I could not reproduce review 08's stale-warning complaint here.
7. **My own bugs, found quickly with the tools:**
   - **Glue strength set to 0.** I wrote `chf("glue_strength")` in a wrangle with no spare parm, so every strength was 0. I noticed it by reasoning, then used `geo_read stats` to read the real strength range and switched to a multiplier.
   - **Meteors with no velocity.** The first `rbd_geo` showed `v` max [0,0,0]. `geo_read stats` traced it in 3 calls: `vel` was correct on `meteor_pts` but all zero after `copytopoints`, which is Houdini behaviour, not the tool. I fixed it with a `nearpoint` lookup on input 1.
   - **Missing density and bounce.** `rbdconfigure` did not write `density` or `bounce` until I set `adddensity1` and `addbounce1` explicitly.
8. **The hip grew from 242 KB to 1.47 MB.** That is fine, but `hip_save` gives no breakdown. A TD would want to know whether sim cache or locked geometry was being written into the hip.

---

## 6. Response-size notes

- **`node_type_info` is the budget hog for FX work.** The four big RBD/ROP types cost 75 KB, because concrete/wood/glass/metal/custom variants and multiparm templates are all listed. I filtered client-side to the 30 parm names I needed. `folder` filtering exists, but I had to fetch everything once to learn the folder names. A `names: "concrete_*"` glob, or a folders-only first pass, would cut this by about 90%.
- **`node_type_search "rbd"` was 13 KB** for 40 rows, because each row carries a description and the older versions of each type are listed. Hiding non-current versions by default would halve it.
- **`geo_info` on packed geometry averaged 1.7–1.9 KB.** It went above the documented ~1 KB because of the `intrinsics.packed` block. The block was handy for the 3 meteors and is presumably capped for 1,354 pieces. It stayed under 2 KB, so that is fine.
- **`cook`, `job`, `problems`, `time`, `hip_save` and `viewport_capture` text were all small (under 800 B).**

---

## 7. Top 5 suggested improvements

1. **Fix `node_type_info` outputs for multi-output HDAs,** and add a parm-name glob filter (`parms: "concrete_*"`) or a folder-list-only mode. Wrong output metadata is a correctness bug for FX graphs, where constraint and proxy outputs are the whole point. The 25 KB compact descriptions cost half of this session's text budget.
2. **Real progress for long cooks.** For solver and DOP-backed SOPs, `job status` should report `progress` as the frame being simulated over the target frame, plus `elapsed_s`. Optionally it could add `cook {frames:[1,96], summary:"bbox"}` returning per-frame point and prim counts and bbox, which would replace my 5 `geo_info` calls when verifying motion.
3. **Make `render` results lean and consistent.** Always include `state` (documented but missing on done), and collapse `outputs` to `{pattern, count, first, last, missing}`. Add a `notes` warning when the scene has no lights for an OpenGL or Karma ROP, or when the thumbnail is near black. Also document that `viewport_capture` lights the scene itself and a real ROP does not.
4. **A lean return mode for `node_create`** (repeated from review 08), defaulting to path, type, errors and warnings. Do not echo creation-script defaults such as light ramps or `s`/`scale` as non-default.
5. **Honest upstream cook cost.** `cook {..., upstream: true}` or `force: "chain"` should recook and time the dependency chain. For example: "fracture 1.8 s, cfg_pieces 0.1 s, solver 4.5 s". Today `node_create`'s implicit cook hides the fracture cost, and `cook` reports 0.1 ms. Choosing scatter counts for a sim budget depends on that number.

**What worked notably well:**
- One `node_create` built and wired a 14-node RBD graph, including HDA output indices 1 and 2.
- `parm_set press` reset the sim.
- `cook` → `job` escalation was smooth.
- `geo_read stats` was the fastest debugger in the toolbox.
- `viewport_capture` with `opengl_rop` and a camera framed every shot correctly.

The whole destruction pass took about 10 minutes and 67 calls, with no Python.
