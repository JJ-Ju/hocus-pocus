# 18 — Copernicus (COP) image workload on 1.2.1

**Seat:** an AI agent working as a compositing/lookdev TD, doing plan-1.3 workload 18 through the MCP tools only. I read `docs/tools.md`, `README.md`, `docs/quickstart.md`, `plan-1.3.md` and review 16. I did not read the server source.
**Build:** `release/1.2.1` code on branch `release/1.3` (`88e654c`), installed editable into a fresh scratch venv (`uv venv`, `uv pip install -e`). `hocuspocus version` → `hocuspocus 1.2.1 (hp/v1, mcp 2.3.0, Python 3.12.14)`, and `houdini_status` reports `bridge_version` and `host_version` `1.2.1` (review 16's N5 is fixed).
**Host:** Houdini 22.0.466 hython, headless, pid **9284**, started with `hocuspocus launch --headless --work-dir <scratch>/c18/cop`. `HOCUSPOCUS_STATE_DIR=<scratch>/c18/state`, `HOUDINI_USER_PREF_DIR=<scratch>/c18/prefs/houdini__HVER__`, `profile = "full"` in `<scratch>/c18/prefs/houdini22.0/hocuspocus.toml` and in `HOCUSPOCUS_PROFILE`. `houdini_status` reported `"profile": "full"` and `$HIP` = the work dir with the note `$HIP is the launch directory until you hip_save.` At the end, `houdini_connect {quit: true}` returned `{"quit":true,"pid":9284,"exited":true}` and the process was gone. I killed nothing.
**Client:** review 16's one-shot `mcp.Client` (`hp18.py`). Each call started a fresh `hocuspocus-mcp`. Every call was logged with tool, args bytes, text bytes, pretty bytes, isError, image count and elapsed time.
**Date:** 2026-10-12, 22:22:15 to 22:28:17 local time (6 min 02 s wall clock from the first to the last call, 26.7 s of it inside tool calls).
**Result:** a procedural 1024×1024 "city map" in a Copernicus network at `/img/citymap` (13 nodes, 0 problems), written by a `rop_image` to `$HIP/img/citymap.0001.png`. **The image came back through `render` as an inline thumbnail on the first try, 3 min 13 s after the first call.** That is the only path that returns COP pixels. `viewport_capture`, `geo_info` and `render` on a non-ROP node all refuse a COP node. The bonus round trip worked: a SOP `attribfrommap` reads the COP live through `op:/img/citymap/overlay`, a wrangle extrudes the blocks, and `viewport_capture` shows the result. I used **0 `houdini_python` calls**. The hip is `<scratch>/c18/cop/citymap.hip` (383,131 B, `dirty: false`).

Evidence: `docs/redesign/evidence/city-destruction/70_copernicus_citymap.png` (1715×600, 315 KB). On the left is the written `citymap.0001.png`, which is the same image as the `render` thumbnail. On the right is the `viewport_capture` of the extruded SOP city that samples the COP.

---

## 1. What I built

```
/img/citymap            copnet (CopNet; created under /img)
  bg_grad    ramp          vertical, colour ramp 3 keys navy -> teal       (parm_set ramp)
  noise      fractalnoise  elementsize 0.35 -> 0.6 -> 0.3, oct 4
  thresh     remap         op threshold ("Threshold" label), threshold 0.44
  tiles      tilepattern   patterntype "Herringbone 3:2" (label), stackbond_div 24
  blocks     blend         mode multiply   bg=tiles fg=thresh
  soften     blur          size 0.002
  bldg_col   constant      signature f3, f3 (0.95,0.55,0.18)               (colour tuple)
  comp       blend         bg=bg_grad fg=bldg_col mask=soften
  grade      colorcorrect  master_contrast 1.15, master_gamma 1.1 -> 0.9
  title      font          text "HocusPocus", fontsize 0.14, t (0,-0.78)
  text_col   constant      signature f3, white
  overlay    blend         bg=grade fg=text_col mask=title   [display]
  out_png    rop_image     copoutput $HIP/img/citymap.$F4.png               (1024x1024 default)

/obj/citygrid           geo (bonus)
  ground     grid          200x200, 384x384
  uv         texture       Orthographic
  citymap    attribfrommap filename op:/img/citymap/overlay  -> point Cd
  extrude    attribwrangle P.y += ((Cd.r - Cd.b) > 0.45) * 6      [display]
```

There is no `threshold` node in Copernicus, so the threshold is a `remap` with `op: threshold`. The "composite over a gradient" is two `blend` nodes, each with a mask input: the city mask over the `ramp` gradient, then the `font` mask for the white title. The whole network was **one `node_create` call** (13 items, named inputs `bg`/`fg`/`mask`, menu tokens and tuples set inline), 1,575 B back, 6.7 s, every node `cooked` with no errors. The default COP resolution is already 1024×1024 (the `rop_image` `res` default). The written PNG is 1024×1024 8-bit RGB, 96,989 B.

---

## 2. Measurements

**Totals**

| | This run |
|---|---:|
| Calls | 82 |
| Text bytes | 81,804 |
| Pretty bytes | 114,204 |
| Args bytes | 6,767 |
| Errors | 7 (2 my own argument-name mistakes, 5 deliberate probes) |
| Seconds in tools | 26.7 (14.8 in `viewport_capture`, 7.0 in `node_create`) |
| Wall clock, first to last call | 6 min 02 s |
| Images returned | 6 (4 `render` thumbnails, 2 `/obj` captures) |
| `houdini_python` | 0 |
| `tools/list` (full) | 35 tools, 32,430 B |

**Timeline (from the first tool call, 22:22:15)**

| Milestone | Time |
|---|---:|
| Discovery done, copnet idiom found (`/img/citymap` created) | 1 min 20 s |
| Network built (one `node_create`) | 2 min 35 s |
| First COP image on disk **and returned through a tool** (`render` thumbnail) | **3 min 13 s** |
| Final look (third render) | 3 min 48 s |
| Bonus round trip captured (`viewport_capture` of the SOP city) | 5 min 11 s |
| `hip_save` + `quit` | 6 min 02 s |

**Per tool**

| Tool | Calls | Errors | Args B | Text B | Avg | Max | Secs |
|---|---:|---:|---:|---:|---:|---:|---:|
| `node_type_info` | 17 | 0 | 902 | 38,789 | 2,281 | **14,703** | 0.7 |
| `node_type_search` | 25 | 0 | 1,131 | 16,388 | 655 | 1,738 | 0.9 |
| `events` | 2 | 0 | 35 | 6,212 | 3,106 | 4,690 | 0.0 |
| `render` | 7 | 2 | 346 | 3,892 | 556 | 992 | 1.4 |
| `parm_get` | 2 | 0 | 207 | 2,544 | 1,272 | 2,177 | 0.0 |
| `node_create` | 3 | 0 | 2,644 | 2,349 | 783 | 1,575 | 7.0 |
| `parm_set` | 3 | 0 | 696 | 2,257 | 752 | 1,445 | 0.2 |
| `network_describe` | 3 | 0 | 127 | 2,079 | 693 | 1,407 | 0.1 |
| `houdini_status` | 2 | 0 | 4 | 1,388 | 694 | 1,214 | 0.0 |
| `cook` | 3 | 0 | 140 | 1,302 | 434 | 885 | 0.5 |
| `viewport_capture` | 4 | 2 | 95 | 1,230 | 307 | 404 | 14.8 |
| `node_info` | 2 | 1 | 57 | 969 | 484 | 594 | 0.0 |
| `geo_info` | 2 | 1 | 63 | 753 | 376 | 554 | 0.0 |
| `node_find` | 1 | 1 | 22 | 442 | 442 | 442 | 0.0 |
| `problems` | 2 | 0 | 46 | 436 | 218 | 218 | 0.0 |
| `geo_read` | 1 | 0 | 72 | 303 | 303 | 303 | 0.3 |
| `hip_save` | 1 | 0 | 150 | 236 | 236 | 236 | 0.0 |
| `undo` | 1 | 0 | 17 | 197 | 197 | 197 | 0.0 |
| `houdini_connect` | 1 | 0 | 13 | 38 | 38 | 38 | 0.6 |

- **Where the bytes went.** Discovery and type lookup were 41 calls and **51.7 KB, 63 % of all bytes**. Building, cooking, rendering and inspecting the image took about 12 KB. Copernicus is a new vocabulary (`remap` thresholds, `blend` composites, `font` is text, `signature` is the layer type), and every one of those facts cost a search or a type lookup.
- **One type was 38 % of `node_type_info`.** `Cop/tilepattern` compact is **14,703 B**, because it lists every per-pattern parm for all 16 patterns (`stackbond_div`, `headerbond_div`, … `crosshatch_tileheight`). `rop_image` compact is 4,306 B, and most of that is Scripts and Metadata parms a TD never sets from an agent.
- **Asked-for compact sizes:** `Cop/fractalnoise` 2,602 B, `Cop/rop_image` 4,306 B, `Cop/font` 1,335 B. Also `ramp` 1,087, `blend` 1,031, `remap` 1,327, `colorcorrect` 2,572, `constant` 767 (filtered `*`), `tilepattern` 14,703.
- **Images:** `render` added 0.1 to 0.3 s per 1024² frame and returned a 512×512 thumbnail every time. The COP render is far cheaper than a `viewport_capture` (4.1 s for an empty `/obj`, 10.7 s for the 147 k-point city).

### Errors

| # | Tool / argument | Message | Hint | Verdict |
|---|---|---|---|---|
| 25 | `node_find {depth: 1}` (my mistake) | `depth: unknown property (allowed: root, pattern, …)` | `node_find's inputSchema in tools/list is authoritative` | Yes |
| 30 | `node_info {path}` (my mistake) | `paths: required property is missing; path: unknown property; did you mean paths?` | as above | Yes |
| 48 | `geo_info {path: /img/citymap/overlay}` | `/img/citymap/overlay is a Cop node, not a SOP or OBJ.` | `Pass a SOP path such as /obj/geo1/OUT, or a geometry object such as /obj/geo1.` | **No.** True, but nothing inspects an image (P1-3). |
| 51 | `viewport_capture {lop_path: /img/citymap/overlay}` | `/img/citymap/overlay is a Cop node, not a LOP.` | `usd_stage reads LOP (Solaris) nodes, e.g. /stage/OUT.` | **No.** The hint names a different tool, and nothing captures a COP (P1-1). |
| 52 | `viewport_capture {camera: /img/citymap/overlay}` | `/img/citymap/overlay (blend) is not a camera.` | `This scene has no camera; omit camera to frame the scene automatically. …` | No (P1-1). |
| 64 | `render {rop_path: /img/citymap/thresh}` | `/img/citymap/thresh (remap) is not a render node.` | `Pass a ROP such as /out/karma1 or /out/opengl1.` | **No.** The right answer is a `Cop/rop_image` in this copnet (P1-2). |
| 65 | `render {rop_path: /img/citymap}` | `/img/citymap (copnet) is not a render node.` | same | No (P1-2). |

---

## 3. Friction log

1. **Discovery, `Cop` category (25 searches).** `noise` → 16 hits with `fractalnoise` 8th, after curl, bubble, phasor, worley and so on. That is acceptable for a broad word, because the exact name would rank first. `blur` and `color correct` are direct hits (`blur`, `colorcorrect`). The rest misled me:
   - `text` → `bakegeometrytextures::2.0` first, then `font`. Text is the `font` node, and the label "Font" never mentions text.
   - `composite` → `zcomp`, `dropshadow` (total 2). The general compositor is `blend` (mode `over`, `add`, `multiply`, …), and nothing points there.
   - `over` → `pyro_dissipate`, `adjacency_distort`. The `blend` mode "Over" is a menu label, and search does not cover menu labels.
   - `threshold` → **0 results**, with the hint `No match. Try a shorter word…`. The answer is `remap` with `op: threshold`.
   - `gradient` → **0 results**. The answer is `ramp`.
   - `file output` → `file`, `output`, `rop_image`. `rop` → `ropnet`, `rop_image`, then `crop` and `dropshadow` (substring hits on "rop").
   - **Legacy vs. new:** with `category: Cop2`, `noise` returns the old `noise`/`denoise`/`aidenoise`. With `Cop` it returns Copernicus. The tool keeps the two apart correctly, and the category enum lists both, but nothing says which one is current. `copnet` without a category returns 10 rows (`Sop`, `Lop`, `Dop`, `Top`, `Driver`, `Chop`, `Shop`, `CopNet` …) plus `cop2net` "COP Network - Old". `Object/copnet` exists but is **hidden** (`"hidden":true` from `node_type_info`), and `/img` (type `img`) is not a searchable Manager type. I found the idiom by trying `node_create {parent: /img, type: copnet}`, which worked. A SOP-level `copnet` is the other idiom, and the tools say nothing about either.
2. **Type lookup.** Compact type info is good for the small nodes and is the first place I learned that inputs are named (`size_ref`, `bg`/`fg`/`mask`, `source`). Problems: `tilepattern` is 14.7 KB. The `blend` mode labels come back with icon markup, `"![BUTTONS_blendmode_over]Over"`. `fractalnoise` `elementsizetype` reports `default_token: "BUTTONS_decompose_transforms"` with one item labelled "Per-Component Controls". The `signature` parm, which is the layer type (mono, RGB, RGBA …) on every Copernicus node, is reported as a plain `string` with default `auto`/`default`/`f3`, with no menu in `compact`, `full` or `parm_get include: menu`. I set `f3` from memory.
3. **Build.** One `node_create` built the graph with named inputs. That is the best part of the run: 13 COP nodes, 3 named-input blends, menus by token and tuples, in one undo step, with every node cooked.
4. **Cook.** `cook` on `out_png` and `overlay` returned `ok: true` with `cook_time_ms` 0.1 and 0.0 and wrote nothing. That is correct Houdini behaviour (cooking a ROP does not render it), but nothing says so. `cook profile: true` on `overlay` gave a sensible chain (overlay 20.6 ms, grade 9.2, comp 4.2, blur 3.6, total 40.2 ms).
5. **Getting pixels back.** `geo_info` refuses a Cop node. `viewport_capture {}` captured an empty `/obj` (4.1 s, grey frame) with **no note** that the scene's only content is a COP network. Compare the stage note in review 16: `The scene also has a stage …; pass lop_path`. `lop_path` and `camera` refuse the COP node. `render` on the `rop_image` **worked first time**: `outputs` with `$HIP` and `$F4` expanded, an inline 512×512 thumbnail, 0.17 s. A frame range with an EXR `output` override (`[1,3]`, `$HIP/img/seq/citymap_seq.$F4.exr`) wrote three 1.6 MB EXRs, returned the frame-3 EXR as the thumbnail, and restored `copoutput` afterwards (`raw: "$HIP/img/citymap.$F4.png"`). A `.tif` override wrote the file but returned `thumbnail_error: "UnidentifiedImageError: cannot identify image file '…/probe.0001.tif'"`. Every COP render carried the note `Scene has no lights; an OpenGL render relies on the ROP's headlight setting and other renderers may render black.`, which is wrong for an image network.
6. **Parm idioms.** These all worked:
   - The `ramp` item form with colour values: `{"basis":"linear","keys":[0,0.55,1],"values":[[r,g,b],…]}` on `bg_grad/ramp`. The result echoes `"is_color":true`.
   - Menus by label: `"Herringbone 3:2"` → `herringbone32`, `"Threshold"` → `threshold`, each with a note.
   - A colour tuple: `bldg_col/f3: [0.95,0.55,0.18]`.

   The ramp echo is float32 noise (`0.019999999552965164`, `0.550000011921`) and `"raw":"3"` (the key count as a string). `parm_get include: ramp` returns the ramp twice, as `value` and as `ramp`. `stackbond_div: 24` was accepted silently while `patterntype` was `herringbone32`, so it had no effect. There was no note that the parm is hidden by the current pattern. `signature: "RGB"` on a constant was accepted, cooked without error and left `problems` empty. I cannot tell from the tools whether Houdini understood it, and I undid it.
7. **Inspection.** `problems` on the copnet: 0 problems, 14 nodes scanned, 218 B. `network_describe format: outline`: 1,407 B for 13 nodes, with named-input wiring as ordered `inputs` and `"flags":["display"]` on `overlay`. That is a good outline. It does not carry the input names (`bg`/`fg`/`mask`), which matter more in COPs than in SOPs. `events`: 32 events after the build, **no duplicate `ChildCreated`** (N2 from review 16 did not reproduce under `/img`), all `origin: agent`. One ramp `parm_set` produced **10 events** (`ramp`, `ramp1pos`, `ramp1c`, `ramp1interp`, … `ramp3interp`). `hip_save` added two `/stage` events (`rendergallerysource` and one with no `detail`) with `origin: agent`, which are Houdini's save-time writes.
8. **Bonus round trip.** `attribfrommap` with `filename: "op:/img/citymap/overlay"` sampled the live COP with no file in between. `geo_read stats` showed Cd mean (0.80, 0.43, 0.11), which matches the orange city colour. The wrangle extruded the blocks to y = 6, and `viewport_capture` (10.7 s) shows the herringbone city with the "lakes" cut out and the title embossed at the far edge. The `op:` path is the best COP-to-SOP idiom, and it is not mentioned anywhere in the docs.

---

## 4. What worked

- **`render` on `Cop/rop_image` is a complete image loop.** `outputs` is correct, `$F4`/`$HIP` are expanded, the inline thumbnail is attached, the EXR thumbnail works, frame ranges work, the `output` override is restored, and each render takes 0.1 to 0.3 s. That is far faster than any Karma loop in reviews 13 and 16. The thumbnail made iterating on the look practical: three looks in 35 s.
- **`node_create` handles Copernicus without special cases**: named inputs, menu tokens, tuples and a full graph in one call and one undo step.
- **Menu-by-label matching** works on COP menus and says what it did.
- **The `ramp` item form** works on a colour ramp the first time.
- **`problems`, the outline, `cook profile` and `hip_save`/`quit`** all behave as documented, with small payloads.
- **Error messages are precise about what is wrong** (wrong category, not a ROP, not a LOP). Their hints are written for SOP/LOP users (see P1-1, P1-2).

---

## 5. Top 10 papercuts

No P0. An agent can get a COP image back, but only by building a `rop_image` and rendering it. Everything below is about making that the obvious path and making intermediate images visible.

### P1

**1. `viewport_capture` cannot show a COP node, and its errors point elsewhere.**
- Calls: `{lop_path: "/img/citymap/overlay"}` → `"/img/citymap/overlay is a Cop node, not a LOP."`, hint `"usd_stage reads LOP (Solaris) nodes, e.g. /stage/OUT."` `{camera: "/img/citymap/overlay"}` → `"… (blend) is not a camera."`, hint `"This scene has no camera; …"`. `{}` captures an empty `/obj` with no note about `/img/citymap`.
- **Proposed change (the answer to "how does an agent get a COP image back"):** add `cop_path` to `viewport_capture` (or accept any image-producing node in a generic `node` argument). The host would create a temporary `Cop/rop_image` in the node's copnet, with `coppath` pointing at that node (and `output` index for multi-output nodes such as `tilepattern` `id`/`uv`), and write a PNG to the captures dir. It would return the image like any capture plus `{resolution, signature, data_window}`, then delete the temporary node with no undo step or dirty flag. This costs about 0.2 s, against 4 to 10 s for an OpenGL capture. In the capture with no arguments, add the note `The scene also has a COP network (/img/citymap, display /img/citymap/overlay); pass cop_path to capture it.`, matching the stage note. Fix the `lop_path` hint so it names `viewport_capture cop_path`, not `usd_stage`.

**2. `render` refuses COP nodes, and its hint sends a compositor to Karma.**
- Calls: `{rop_path: "/img/citymap/thresh"}` → `"/img/citymap/thresh (remap) is not a render node."`, hint `"Pass a ROP such as /out/karma1 or /out/opengl1."`. The same happens for `/img/citymap`.
- **Proposed change:** when the node's category is `Cop` or `CopNet`, use the hint `"Render a Cop/rop_image inside /img/citymap (input or coppath = this node), or use viewport_capture cop_path for a look."` and list any existing `rop_image` nodes in that copnet as `candidates`. Optionally accept a Cop node directly: render it through a temporary `rop_image` to `output`, which must then be given.

**3. No image inspection: `geo_info` refuses COPs, and nothing reports resolution, layer type or pixel statistics.**
- Call: `geo_info {path: "/img/citymap/overlay"}` → `"/img/citymap/overlay is a Cop node, not a SOP or OBJ."`, hint `"Pass a SOP path …"`.
- **Proposed change:** let `geo_info` on a Cop node return an image summary (or add an `image_info` tool): per output, the layer `signature` (f1/f3/f4, or geometry/VDB for non-layer outputs), resolution, pixel scale, data window, border, and per-channel min/max/mean (cheap at 1024²). The same tool could read an image file on disk under `approved_roots`, so an agent can check `citymap.0001.png` without decoding it itself. This is the COP equivalent of `geo_info` + `geo_read stats` and would have answered my "is the mask actually 0/1?" question without a render.

**4. `signature` (layer type) has no menu anywhere, and invalid values are accepted silently.**
- `node_type_info {type: Cop/fractalnoise, detail: full, parms: "signature|…"}` → `{"name":"signature","label":"Signature","type":"string","default":"default"}`. There is no menu in `parm_get include: menu` either. `parm_set {path: /img/citymap/text_col/signature, value: "RGB"}` → no error, no note, `cook` ok, `problems` empty.
- **Proposed change:** report the menu of string parms that have one (`menu_items`/`menu_script`), evaluating script menus or marking them `menu: {dynamic: true}` (plan-1.3 known item). Apply the same label/token matching and the `invalid_value` check that menu parms get. `signature` is on every Copernicus node and decides mono vs. colour, so it is the parm an agent most needs.

**5. Discovery does not know the Copernicus vocabulary.**
- `{query: "threshold", category: "Cop"}` → `{"results":[],"total":0,"hint":"No match. Try a shorter word…"}`. `gradient` → 0. `composite` → `zcomp`, `dropshadow`. `over` → `pyro_dissipate`. `text` → `bakegeometrytextures::2.0` before `font`.
- **Proposed change:** (a) search the menu labels of a type's top-level mode menus. That finds `remap` (op "Threshold") and `blend` (mode "Over", "Multiply", …), which covers most compositing verbs. (b) Add a small synonym table for `Cop`: composite/over/merge/layer → `blend`; gradient → `ramp`; text/title → `font`; write/save/output → `rop_image`; threshold/step → `remap`. (c) When `category: Cop2` matches, add a note: `Cop2 is the legacy compositor (COP Network - Old); Houdini 22's Copernicus nodes are category Cop.`

**6. Where a COP network lives is undiscoverable.**
- `{query: "copnet"}` → 10 rows across Sop/Lop/Dop/Top/Driver/Chop/Shop/CopNet. `Object/copnet` is `"hidden":true`, and `{query: "img", category: "Manager"}` → 0. I found `/img` + `copnet` by trial.
- **Proposed change:** for container types, add `child_category` (`Cop`) and typical parents to the search row, e.g. `"created_in": ["/img", "a SOP network", "a LOP network"]`. Add a Copernicus paragraph to `hocuspocus://guide` and `docs/quickstart.md`: `/img/<copnet>` holds Cop nodes; the output is a `rop_image`; `render` returns the image; SOPs read a COP live with `op:/img/<net>/<node>`.

### P2

**7. `render` on a COP ROP warns about lights.** Every COP render returned `"notes":["Scene has no lights; an OpenGL render relies on the ROP's headlight setting and other renderers may render black."]`. **Change:** skip the light check for `Cop/rop_image` (and other image ROPs: `Driver/comp`, COP-sourced ROPs).

**8. `cook` on a ROP reports success and writes nothing, with no hint.** `cook {paths: ["/img/citymap/out_png"]}` → `ok: true, cook_time_ms: 0.1`, and no file. **Change:** for ROP nodes (`Driver`, `Cop/rop_*`, `Lop/usdrender_rop`), add `"hint":"Cooking a ROP does not write files; use render {rop_path: …}."`.

**9. Type info is bloated or leaks UI markup on COP types.**
- `node_type_info {type: Cop/tilepattern, detail: compact}` = **14,703 B** (the per-pattern parms of all 16 patterns).
- `blend` mode labels are `"![BUTTONS_blendmode_over]Over"`.
- `fractalnoise` `elementsizetype` has `default_token: "BUTTONS_decompose_transforms"`.

**Change:** strip a leading `![…]` icon reference from menu labels. In `compact`, collapse parm groups that differ only by a menu-selected prefix into one row plus a note (`stackbond_* … crosshatch_*: 16 variants by patterntype; pass parms "<pattern>_*"`), or page at about 4 KB with `folders` as the hint. Also, `parm_set` on a parm that is hidden or disabled by the current menu value (`stackbond_div` while `patterntype` is `herringbone32`) should add the note `stackbond_div is hidden for patterntype herringbone32; it has no effect.`.

**10. Ramp payloads and events are noisy.**
- `parm_set`/`parm_get` ramp values come back as float32 (`0.019999999552965164`, `0.550000011921`) with `"raw":"3"`.
- `parm_get include: ramp` repeats the ramp as `value` and as `ramp` (2,177 B for 4 parms).
- One ramp `parm_set` produces 10 `events` (`ramp`, `ramp1pos`, `ramp1c`, `ramp1interp` …).
- `hip_save` records Houdini's `/stage` save-time writes (`rendergallerysource`) as `origin: agent`.

**Change:** round ramp keys and values to 6 significant digits and drop `raw` for ramps. When `include: ramp` is given, return `ramp` only. Collapse a ramp's multiparm events into one `ParmTupleChanged {parm: "ramp", keys: 3}`. Extend the TOP save-write exclusion to `/stage`.

**Also seen (below the cut):**
- The `.tif` thumbnail fails with a raw `UnidentifiedImageError: cannot identify image file '…'`. Use the documented "an extension it cannot read" note instead, or decode TIFF through Houdini's `iconvert`.
- `network_describe` outline `inputs` are positional only. In COPs, `bg`/`fg`/`mask` names would make a blend readable at a glance.
- `cook profile` lists the top 10 of 12 nodes with `chain_total: 12`. That is fine, but `noise` and `title` are hidden, and in COPs the generators are often the slow nodes.

---

## 6. Verdict

**Copernicus is usable through HocusPocus 1.2.1 today, if the agent already knows Copernicus.** The build loop is excellent: the whole network in one `node_create`, menus by label, a colour ramp first try, and a full-resolution image back through `render` in 0.2 s with a thumbnail the model can see. The first image arrived 3 min 13 s after the first call. The bonus SOP round trip also worked first try through an `op:` path, with 0 `houdini_python` calls.

The weak half is **knowing and looking**. 63 % of the bytes went to discovery, and three of the compositing verbs I searched for (threshold, gradient, over/composite) returned nothing useful. The copnet idiom (`/img`) had to be guessed. Once the network existed, the only way to see any node was to wire it to a `rop_image` and render it; `viewport_capture`, `geo_info` and `render` on a non-ROP all refuse, and their hints point at SOP/LOP tools. For 1.3, the highest-value changes are P1-1 (`viewport_capture cop_path` through a temporary `rop_image`) and P1-3 (an image summary for Cop nodes). These two give an agent the COP versions of "look" and `geo_info`. After them, P1-4 to P1-6 (signature menu, vocabulary, idiom) would remove most of the discovery cost.
