# 13 — Solaris lookdev on 1.1: the city in LOPs, MaterialX, Karma

**Seat:** an AI agent working as a lookdev TD. I used only the MCP tool surface, `docs/tools.md`, the README and review 12. I did not read the server source.
**Build:** `release/1.2` at `c812972`, installed editable into a scratch venv. The working tree also had other agents' uncommitted edits to `catalog.py`, `docs.py` and `bridge/instructions.py`, so the `tools/list` size below reflects them. `hocuspocus version` prints `1.1.0`.
**Host:** Houdini 22.0.466 hython, headless, pid **44296**. I started it with `hocuspocus launch --headless --hip <scratch>/city/city_v01.hip` (the 1.0 city) and killed it at the end. `profile = "full"` was set in `hocuspocus.toml` and in `HOCUSPOCUS_PROFILE`. `houdini_status` reported `"profile": "full"`, and all four `full` tools answered.
**Client:** the review-12 one-shot `mcp.Client` (`hp13.py`). Each call started a fresh `hocuspocus-mcp`. Every call was logged with tool, args bytes, text bytes, pretty bytes, isError and elapsed time.
**Date:** 2026-10-12, 20:03:45 to 20:10:05 local time (6 min 20 s wall clock, 34.5 s of that inside tool calls).
**Result:** a lit, shaded city in `/stage`, rendered by Karma CPU at 640×360 in **5–7.7 s per frame**. `/stage` has 0 problems. I used **0 `houdini_python` calls**. The hip is saved as `<scratch>/lookdev/city_lookdev.hip` (763,101 B, `dirty: false`). The evidence image is `docs/redesign/evidence/city-destruction/30_lookdev_karma.png` (640×360, 284 KB). **That image did not come back through `render`.** I copied it from disk because every `render` call on a USD render ROP returned `outputs: []` and no thumbnail (papercut 1).

---

## 1. What I built

```
/stage
  city       sopimport   soppath /obj/city_gen/OUT_CITY, pathprefix /city
                         -> /city (Xform, kind component) + 192 Mesh prims (bldg_000..190, ground)
  matlib     materiallibrary
     concrete  mtlxstandard_surface  base_color (0.38,0.37,0.35), specular 0.3, roughness 0.75
     asphalt   mtlxstandard_surface  base_color (0.035,0.035,0.04), specular 0.4, roughness 0.9
             -> /materials/{concrete,asphalt} (Material + Shader + _preview Shader)
  assign     assignmaterial  nummaterials 2:
                 /city/bldg_*  -> /materials/concrete
                 /city/ground  -> /materials/asphalt
  key        distantlight::2.0  r (-38,-60,0), ry keyed -60@1 -> -20@48, intensity 1.8, color (1,.92,.8)
  fill       domelight::3.0     intensity 0.45, color (0.7,0.8,1.0)
  cam_main   camera             t (430,300,430), look-at (0,15,0), 32 mm, vAperture 11.787
  rset       karmarendersettings  camera /cameras/cam_main, resolutionx 640 (autoheight -> 360),
                                  4 primary / 16 path-traced samples, picture <scratch>/lookdev/render/...exr
  karma_rop  usdrender_rop      renderer BRAY_HdKarma, outputimage <scratch>/lookdev/render/city_ov.$F4.png
/out/karma_city  usdrender       loppath /stage/rset (made to test whether the /out ROP behaves differently; it does not)
```

- **Import.** One `node_create` made the SOP import. `sopimport`'s default `pathattr` (`path,name`) turned the city's prim `name` attribute (192 unique values) into one Mesh per building plus `/city/ground`, so no further partitioning was needed. `geo_read stats` confirmed the 192 names in one 551 B call.
- **Materials.** One 4-item `node_create` built the material library, both shaders inside it and the assignment. It set the multiparm count and the instance parms (`nummaterials: 2`, `primpattern1/2`, `matspecpath1/2`) in the same item, and it worked on the first try. `usd_stage include: bindings` confirmed `/materials/concrete` on the buildings and `/materials/asphalt` on `/city/ground`.
- **Lights, camera, render.** One 5-item `node_create` built these after one failed attempt (papercut 4). `usd_stage` confirmed `inputs:intensity`, `inputs:color`, the look-at matrix and `verticalAperture 0.1178719`. The second value is in Houdini's scene units, so the 0.35 focal length reads strangely but is correct.
- **Look.** After the first render, one 6-item `parm_set` fixed the look. The first render was over-bright and framed too tight. The fix lowered the key from 3.0 to 1.8, rotated it, pulled the camera back and darkened the concrete. Each render took 5–6 s.

**Counts and bounds.** `geo_info` on `OUT_CITY` gives 80,636 points and 80,123 polygons, with bbox 428 × 93.05 × 428. On the stage I counted 193 prims under `/city` (192 meshes plus the Xform). That took 4 paged `usd_stage` calls (14.4 KB). **I could not get stage bounds from any tool.** `usd_stage` has no bbox option, and the only bound it shows is each mesh's local `extent` attribute (papercut 5).

---

## 2. Measurements

**Totals: 66 calls · 72,732 B text (99,133 B pretty) · 7,803 B args · 7 errors (2 deliberate probes, 1 my own argument mistake) · 34.5 s in tools · 1 image returned (a `viewport_capture` of `/obj`, not of the stage) · 0 `houdini_python`.**

| Tool | Calls | Errors | Args B | Text B total | Text B avg | Max | Secs |
|---|---:|---:|---:|---:|---:|---:|---:|
| `usd_stage` | 17 | 2 | 1,180 | 24,222 | 1,424 | 3,727 | 0.4 |
| `node_type_info` | 12 | 0 | 940 | 23,701 | 1,975 | 3,299 | 0.2 |
| `events` | 2 | 0 | 23 | 7,037 | 3,518 | 6,451 | 0.0 |
| `parm_get` | 4 | 1 | 321 | 2,516 | 629 | 962 | 0.0 |
| `node_create` | 5 | 1 | 3,520 | 2,380 | 476 | 598 | 1.2 |
| `node_type_search` | 3 | 0 | 114 | 2,331 | 777 | 1,234 | 0.3 |
| `houdini_status` | 2 | 0 | 4 | 2,261 | 1,130 | 1,224 | 0.0 |
| `parm_set` | 4 | 1 | 723 | 2,211 | 552 | 1,157 | 0.1 |
| `render` | 6 | 1 | 362 | 1,513 | 252 | 674 | 26.8 |
| `network_describe` | 2 | 0 | 77 | 1,472 | 736 | 908 | 0.0 |
| `geo_info` | 1 | 0 | 33 | 822 | 822 | 822 | 0.7 |
| `job` | 3 | 0 | 129 | 738 | 246 | 287 | 0.0 |
| `viewport_capture` | 2 | 1 | 75 | 582 | 291 | 387 | 4.1 |
| `geo_read` | 1 | 0 | 105 | 551 | 551 | 551 | 0.3 |
| `hip_save` | 1 | 0 | 159 | 250 | 250 | 250 | 0.1 |
| `problems` | 1 | 0 | 38 | 145 | 145 | 145 | 0.2 |

- **Where the bytes went.** Lookup and inspection cost far more than building. 12 `node_type_info` calls (23.7 KB) and 17 `usd_stage` calls (24.2 KB) are two thirds of all result bytes. All 5 `node_create` calls together returned 2.4 KB for 13 nodes, about 180 B per node, in line with review 12.
- **Time to first image** (from the first tool call at 20:03:45):
  - First Karma frame (EXR) on disk: **3 min 01 s**. The `render` call took 7.7 s.
  - First viewable PNG on disk: **3 min 43 s**, after two failed attempts to get an image out of `render`.
  - First Karma image returned **through the tool**: **never**.
  - First image of any kind returned: **4 min 19 s**. It came from `viewport_capture`, but it shows `/obj` rather than the stage (papercut 3).
- **`houdini_python`: 0 uses.** The `locked` error hint suggested it (papercut 4). I used `parm_get` instead and set only `resolutionx`.
- **`tools/list` with `profile = full`:** 35 tools, **36,578 B** serialised. The 1.2 budget target is ≤ 40 KB.
- **Host:** `launch` returned the registry line at once. The host survived 66 one-shot bridges and used 590 MB at the end.

### Errors

| # | Tool / argument | Message (abridged) | Hint | Did the hint help? |
|---|---|---|---|---|
| 25 | `node_create` item 3 `parms.resolution: [640,360]` on `karmarendersettings` | `locked`: `/stage/rset/resolution is locked.` | `Unlock it in Houdini, or with houdini_python: hou.parm('/stage/rset/resolutionx').lock(False).` | **No.** It names the wrong component and points to the escape hatch. The real cause was `resolutiony` being an expression under `res_mode: autoheight`. I found that with `parm_get`. The whole 5-node batch was rolled back. |
| 28 | `parm_get {path, parms}` (my mistake) | `3 argument problem(s) ... did you mean paths?` | `fix the listed arguments` | Yes, fixed in one retry. |
| 35 | `render {output: ".../city_ov.$F4.png"}` | `cook_failed`: `Command Exit Code: 1 ... Use a Log Viewer with External Render Processes enabled` | none | **No.** The real cause (`Unable to load USD file '...city_ov.0001.png'`) appears only in the host log. |
| 43 | `viewport_capture {camera: "/stage/cam_main"}` | `/stage/cam_main (camera) is not a camera.` | `Pass an OBJ camera such as /obj/cam1, or omit camera` | It was clear, but following it produced an image of the wrong scene. |
| 47 | `usd_stage {lop_path: "/stage/karma_rop"}` | `/stage/karma_rop is a Lop node, not a LOP.` | `usd_stage reads LOP (Solaris) nodes` | No. The message contradicts itself. |
| 61 | `parm_set /stage/fill/inputs:intensity` (probe) | `parm_not_found` | `Did you mean xn__inputsintensity_i0a?` with candidates | **Yes, excellent.** |
| 62 | `usd_stage prim /city/bldg_999` (probe) | `No prim at '/city/bldg_999' on this stage.` | five nearby prims as `candidates` | **Yes, excellent.** |

---

## 3. Friction log (in call order)

1. **Setup: the `__HVER__` directory.** I created `prefs/houdini__HVER__/hocuspocus.toml` literally. `hocuspocus doctor` then said `hocuspocus.toml: none (defaults)`, because Houdini expands `__HVER__` to `houdini22.0`. Doctor did tell me which pref dir it resolved, and that is how I noticed. A `profile = "full"` file in the literal directory is silently ignored. The `HOCUSPOCUS_PROFILE=full` environment variable would have saved the bridge but not the host. A warning such as "a literal `houdini__HVER__` directory exists next to the resolved one" would catch this.
2. **The `full` profile is wired on both sides.** `houdini_status` showed `"profile": "full"`, and `usd_stage`, `events` and the others answered at once.
3. **`node_type_info` handles `a|b` and `(no folder)` now** (both review-12 papercuts are fixed). With `parms: "*path*|soppath|*prim*|*import*"`, `sopimport` came back in one 2.8 KB call that included `pathattr`'s default `path,name`.
4. **Multiparm instance parms are findable, but only on a second try.** `folder: "(no folder)"` on `assignmaterial` showed only `nummaterials`. A glob (`*prim*|*mat*`) then revealed a pseudo-folder `"Number of Materials[]"` holding `primpattern#` and `matspecpath#`. That works, but nothing tells you the `#` parms exist until you search for them.
5. **`node_type_info` on `mtlxstandard_surface` returned 3.3 KB to tell me about 3 parms.** About 2.2 KB of it was the 42-entry `inputs` list, which is returned even when `parms` filters the result.
6. **The material batch worked on the first try**, including multiparm count plus instance parms in one item and nodes created inside a just-created material library. `include: bindings` puts a single `material` key on each prim, which is ideal.
7. **Light parms use Houdini's encoded USD names.** To set `inputs:intensity` and `inputs:color` I needed one `node_type_info` call per light type (2.2 KB and 2.0 KB) to learn `xn__inputsintensity_i0a` and `xn__inputscolor_zta`. The later probe with `inputs:intensity` got a very good "did you mean" hint, but the tool could simply accept the USD name.
8. **`node_type_search` flags deprecation.** `karmarenderproperties` came back with `deprecated: true` and `deprecation_reason: "Use karmarendersettings instead"`. That saved me from building on a deprecated node.
9. **The locked `resolution` rolled back the whole batch** (error 25). `res_mode: autoheight` drives `resolutiony` with a locked Python expression. Setting `resolutionx` alone gave 640×360. Rolling back the batch also left 16 `ChildCreated`/`ChildDeleted` events in the log for nothing.
10. **`usd_stage` attribute reads are verbose.** The camera with `attributes` plus `xform` was 1,854 B, and the two lights were 2,409 B. Most of that is `houdini:*` attributes, xformOps and a `world` matrix identical to `local`. Short token arrays are summarised (`xformOpOrder` showed the first 3 of 6), so I could not read the op order without a second tool.
11. **`render` reported a successful Karma render as having no output.** Calls 32, 38, 42 and 46 all returned `{"outputs": [], "missing": ["C:/Users/jujun/__render__.usd"], "state": "done"}` with no thumbnail and no notes. The EXR or PNG was on disk each time. The tool looks at `lopoutput` (husk's intermediate USD, a relative `__render__.usd`) instead of `outputimage` or the RenderProduct. The `/out` `usdrender` ROP behaves the same way. A model that trusts the result concludes that the render produced nothing.
12. **`render output:` writes the wrong parm.** It overrode `lopoutput`, so husk tried to load my PNG path as USD and failed with a generic exit-code-1 message (error 35). To its credit, the override was restored afterwards (`lopoutput` was back to `__render__.usd`), and renders never dirtied the hip.
13. **`viewport_capture` cannot see the stage.** It rejects a LOP camera, and without a camera it renders `/obj`: the SOP city in its `Cd` colours on a grey background, framed loosely. Nothing in the result says the materials, lights and camera of `/stage` were not used. For LOPs the answer is no, it does not work.
14. **Job flow works.** `render {wait_s: 0}` returned a running job with a `Poll with job ...` hint. `job status` and `job result` then returned the same (empty) render result 5.3 s later.
15. **`usd_stage` paging and patterns.** `limit` plus `next_cursor` paged 193 prims cleanly, but `total` appears only on the last page. **`prim` accepts a glob** (`/city/bldg_00*` returned 10 prims), which `docs/tools.md` does not mention. Children come back in reverse name order (`bldg_190` first).
16. **`time` works.** After keying `ry` from -60 to -20, `usd_stage time: 48` returned the frame-48 matrix (cos 20° = 0.9397) and the default call returned frame 1. Nothing tells you which attributes are time-sampled.
17. **`events` is noisy.** About 12 edits produced 54 events: 16 from the rolled-back batch, 2 from `render`'s set and restore of `lopoutput`, and about 18 Houdini callback updates (`*Converted`, `xn__houdiniguidescale_s3a`). The shaders created inside `matlib` are missing. The keyframe on `ry` is reported as `{"parm": "r", "count": 2}`. Paging works (`more: true`, `next_since: 50`).
18. **`problems` and `hip_save` worked.** `problems` scanned 11 nodes (145 B). `hip_save` wrote 763 KB and reported `dirty: false`.
19. **The outline does not mark the stage's display LOP.** `network_describe {root: "/stage", format: "outline"}` (908 B, 10 nodes) does not show which LOP is displayed. It does show `display: /stage/matlib/concrete` on the material library, which means nothing there. It also shows no wiring, which matters more in LOPs than in SOPs because the stage is a chain (review-12 leftover).

---

## 4. What worked well

- **The authoring path is right for Solaris.** 13 nodes in 3 `node_create` calls, including nodes inside a material library and multiparm instances in the same item. Bindings were confirmed with one `usd_stage` call.
- **`usd_stage` is the right shape.** It reads prims, kinds, child counts, bindings, layers, xforms and summarised arrays (`{"len": 880, "first": [...]}`). It supports paging, globs and time. Its errors give real candidates.
- **The hints for wrong names are excellent** (USD names, missing prims, argument typos).
- **Karma runs headless with no special setup**, at 5–8 s per frame for 80k polys, 640×360 and 16 path-traced samples. The `render` job machinery (sync under 10 s, a job with `wait_s: 0`, `job result`) is correct. Only the output discovery is wrong.
- **`render` overrides are restored afterwards, and rendering does not dirty the hip.**
- **The deprecation flag** in `node_type_search` and `node_type_info`.
- **0 `houdini_python` calls**, and no work-arounds were needed except setting `outputimage` by hand.

---

## 5. Top 10 papercuts

### P0 — wrong answer or blocked

**1. `render` on USD render ROPs reports no output and returns no thumbnail.**
- **Tool:** `render {rop_path: "/stage/karma_rop"}` (Lop `usdrender_rop`), and also `/out/karma_city` (Driver `usdrender`).
- **Exact result:** `{"outputs":[],"missing":["C:/Users/jujun/__render__.usd"],"job_id":"…","state":"done"}`, while `city_ov.0001.png` (and earlier the EXR) was written correctly.
- **Proposed change:** for `usdrender`, `usdrender_rop` and the Karma LOP, resolve outputs in this order: `outputimage` if set; otherwise the `productName` of every RenderProduct on the settings prim the ROP uses (evaluate the LOP stage at each frame and expand `$F`). Never use `lopoutput`. Make the thumbnail from EXR as well as PNG. If `state` is `done` and nothing was resolved, add a note (`output path not found; check outputimage / RenderProduct`) instead of silently reporting `missing`.

**2. `render output:` overrides the wrong parm on USD ROPs.**
- **Tool:** `render {rop_path: "/stage/karma_rop", output: ".../city_ov.$F4.png"}`.
- **Exact message:** `cook_failed`: `/stage/karma_rop failed to render frame 1.0: The attempted operation failed. Error: Command Exit Code: 1 Failed to complete render: exit code 1 Use a Log Viewer with External Render Processes enabled for more information.` The host log says `Unable to load USD file '…/usd_renders/usdrender_44296_129_2/city_ov.0001.png'`.
- **Proposed change:** map `output` to `outputimage` for USD render ROPs, using the same per-type table as papercut 1. On a husk failure, attach the last 20 lines of husk stderr (or of the host log) to `detail`, and add a hint such as `husk exited 1; see detail.log_tail`.

**3. `viewport_capture` silently shows `/obj` instead of the stage, and rejects LOP cameras.**
- **Tool:** `viewport_capture {camera: "/stage/cam_main"}`.
- **Exact message:** `/stage/cam_main (camera) is not a camera.`, hint `Pass an OBJ camera such as /obj/cam1, or omit camera to frame the scene automatically.` Without `camera`, the capture is the SOP city from `/obj` with no materials or lights, and the result carries no note.
- **Proposed change:** accept a LOP camera node or camera prim path, plus an optional `lop_path`. Headless, drive the OpenGL ROP from the LOP network (its LOP/stage source) with that camera. Add `scene_used: "/obj" | "/stage/…"` to the result, and a note when `/stage` has a display LOP but `/obj` was captured. Fix the hint so it does not send Solaris users to OBJ cameras.

### P1 — token or call waste

**4. A locked tuple component fails the whole batch, and the hint points to `houdini_python`.**
- **Tool:** `node_create`, item `karmarendersettings` with `parms.resolution: [640, 360]`.
- **Exact message:** `items[3] (/stage/rset): parms.resolution: /stage/rset/resolution is locked.`, hint `Unlock it in Houdini, or with houdini_python: hou.parm('/stage/rset/resolutionx').lock(False).`
- **Proposed change:** name the locked component and its expression, for example `resolutiony is locked and driven by an expression (res_mode = autoheight computes it from the camera)`. Suggest the fix inside the tools (`set resolutionx only, or res_mode: manual`). When the locked component already holds the requested value, skip it. Do not mention `houdini_python` first.

**5. `usd_stage` cannot count or bound the stage.**
- **Tool:** `usd_stage {prim: "/city", depth: 2, limit: 50}` ×4 = 14.4 KB, only to learn "193 prims". `total` appears only on the last page, and no call returns a world bbox.
- **Proposed change:** add `summary: true`, returning `{total, by_type: {Mesh: 192, Xform: 1}, bbox: {min, max, size}}` for the subtree (UsdGeomBBoxCache, purpose default/render) in about 200 B. Put `total` on every page. Document that `prim` accepts globs. Optionally add a `type` filter (`type: "Mesh"`).

**6. `usd_stage include: attributes` has no filter.**
- **Tool:** `usd_stage {prim: "/lights", depth: 2, include: ["attributes"]}` = 2,409 B, and camera plus xform = 1,854 B. Most of it is `houdini:*` attributes, xformOps, and a `world` matrix equal to `local`.
- **Proposed change:** add `attributes: "inputs:*|focalLength"` (a glob, like `node_type_info parms`). By default, omit `houdini:*` and the xformOp attributes when `xform` is also requested. Drop `world` when it equals `local`. Show arrays of 8 or fewer elements in full. Add `time_sampled: true` per attribute.

**7. Houdini's encoded USD parm names cost one type lookup per light.**
- **Tool:** `parm_set {path: "/stage/fill/inputs:intensity"}`.
- **Exact message:** `parm_not_found`, hint `Did you mean xn__inputsintensity_i0a?` (a good hint, but it still costs a round trip). I needed 2 `node_type_info` calls (4.2 KB) to find these names before building.
- **Proposed change:** accept USD attribute names (`inputs:intensity`, `inputs:color`) in `parm_set`, `parm_get` and `node_create parms` on LOP nodes, and resolve them with `hou.text.encode`. Optionally set the matching `_control` parm to `set`. In `node_type_info`, show the decoded USD name (or a `usd` column) for `xn__` parms.

**8. `node_type_info` returns full input lists and folder lists even when filtered.**
- **Tool:** `node_type_info {type: "Vop/mtlxstandard_surface", parms: "base*|specular_roughness|specular"}` = 3,299 B, about 2.2 KB of it the 42 `inputs`. `{type: "Lop/karmarendersettings", parms: "res*|aspect*", detail: "full"}` = 3,260 B, about 2 KB of it the 50-entry `folders` list.
- **Proposed change:** when `parms` or `folder` is set, return `inputs` only as a count (or only when `include_inputs` is set), and omit `folders` in `detail: full`. That would have saved about 9 KB, 38 % of my `node_type_info` bytes.

**9. `events` is mostly noise after LOP edits.**
- **Tool:** `events {since: 0}` = 6,451 B for 50 of 54 events after about 12 edits.
- **Detail:** the noise includes 16 created/deleted events from a rolled-back `node_create`, `render`'s own `lopoutput` set and restore, and about 18 callback updates (`focalLengthConverted`, `xn__houdiniguidescale_s3a`). Meanwhile the shaders created inside `matlib` are missing, and a keyframe on `ry` shows as `{"parm":"r","count":2}`.
- **Proposed change:** drop events inside rolled-back undo groups and from tool-internal set/restore. Tag changes that Houdini callbacks cause (`source: "callback"`) and collapse them, or hide them by default. Report `ChildCreated` for nested nodes that HocusPocus created. Report keyed component parms by name (`ry`, `keyed: true`).

### P2 — polish

**10. `usd_stage` on a ROP LOP returns a self-contradictory message, and the outline omits the LOP display node.**
- **Tool:** `usd_stage {lop_path: "/stage/karma_rop"}`.
- **Exact message:** `/stage/karma_rop is a Lop node, not a LOP.`
- **Proposed change:** say `/stage/karma_rop (usdrender_rop) has no output stage; read its input /stage/rset`. Separately, `network_describe format: outline` on `/stage` should mark the display LOP and list input names (the planned review-12 leftover), and should not report `display` for VOP networks such as `matlib`.

**Honourable mentions:**
- `parm_set` still returns `raw` when it equals `value` for numbers (`"value":1.8,"raw":"1.8"`).
- `usd_stage include: layers` lists anonymous layer ids (`anon:…:LOP`) without the LOP node that authored each one.
- `doctor` does not warn about a literal `houdini__HVER__` directory.
- `houdini_status` reported `HIP` correctly this time: the hip's directory, because I launched with `--hip`.
