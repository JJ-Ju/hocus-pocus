# 16 — Solaris lookdev rerun on 1.2: the review-13 workload, papercut by papercut

**Seat:** an AI agent working as a lookdev TD, repeating review 13's workload. I used only the MCP tool surface, `docs/tools.md` (with its new `notes` sections), the `hocuspocus://guide` resource, the CHANGELOG and review 13. I did not read the server source.
**Build:** `release/1.2`, host loaded from `deb3ec9` plus the working tree of that moment, installed editable into a fresh scratch venv (`uv venv`, `uv pip install -e`). Other agents committed docs during the run (`bb3410f` bridge instructions, `efd69f6`, `52a19f3`, `caf84a2`). None of them touched host code. `hocuspocus version` still prints `1.1.0` (new papercut N5).
**Host:** Houdini 22.0.466 hython, headless, pid **45904**, started with `hocuspocus launch --headless --hip <scratch>/city/city_v01.hip` (the same 1.0 city hip as review 13). `HOCUSPOCUS_STATE_DIR` and `HOUDINI_USER_PREF_DIR=<scratch>/c16/prefs/houdini__HVER__` were isolated. `profile = "full"` was set in `<scratch>/c16/prefs/houdini22.0/hocuspocus.toml` and in `HOCUSPOCUS_PROFILE`. `houdini_status` reported `"profile": "full"`. I closed the host at the end with `houdini_connect {quit: true}`. That returned `{"quit":true,"pid":45904,"exited":true}`, `houdini_status` then showed `connected: null, instances: []`, and the process was gone, so I did not have to kill anything.
**Client:** review 13's one-shot `mcp.Client` (`hp16.py`, the same as `hp13.py` plus a timestamp). Each call started a fresh `hocuspocus-mcp`. Every call was logged with tool, args bytes, text bytes, pretty bytes, isError, image count and elapsed time.
**Date:** 2026-10-12, 21:13:28 to 21:18:37 local time (5 min 09 s wall clock, 49.4 s of it inside tool calls, 28.9 s of that in `viewport_capture`).
**Result:** the same lit, shaded city in `/stage`, rendered by Karma CPU at 640×360 in 5.1–6.7 s per frame. `/stage` has 0 problems. I used **0 `houdini_python` calls**. The hip is saved as `<scratch>/c16/lookdev/city_lookdev.hip` (754,404 B, `dirty: false`). **The first Karma image came back through `render` 1 min 22 s after the first call.** In review 13 that never happened. **`viewport_capture` of the stage did not work.** All 5 attempts, with `lop_path`, a LOP camera node, a camera prim and different resolutions, failed with `internal`: `The render process exited with code 139.` (new papercut N1). `docs/redesign/evidence/city-destruction/31_lookdev_capture_1.2.png` (512×288, 186 KB) is therefore the **thumbnail that `render` returned inline** for the final look. It is not a viewport capture.

---

## 1. What I built (same graph as review 13)

```
/stage
  city       sopimport            soppath /obj/city_gen/OUT_CITY, pathprefix /city  -> 192 Mesh + 1 Xform
  matlib     materiallibrary
     concrete  mtlxstandard_surface  base_color (0.52,..) -> (0.38,0.37,0.35) after the look pass
     asphalt   mtlxstandard_surface  base_color (0.035,0.035,0.04)
  assign     assignmaterial       /city/bldg_* -> /materials/concrete, /city/ground -> /materials/asphalt
  key        distantlight::2.0    inputs:intensity 3.0 -> 1.8, rx -38, ry keyed -60@1 -> -20@48
  fill       domelight::3.0       inputs:intensity 0.6, inputs:color (0.7,0.8,1.0)
  cam_main   camera               t (310,230,310) -> (430,300,430), look-at (0,15,0), 35 -> 32 mm
  rset       karmarendersettings  camera /cameras/cam_main, resolutionx 640, 4/16 samples,
                                  picture <scratch>/c16/lookdev/render/city_lookdev.$F4.exr  (display)
  karma_rop  usdrender_rop        renderer BRAY_HdKarma; outputimage left EMPTY on purpose
```

I took the same steps with the same argument files as review 13, with three differences. The light parms were set with the USD names (`inputs:intensity`, `inputs:color`). `outputimage` was left empty, to test discovery through the RenderProduct. I did not build the `/out` ROP. I knew review 13's answers in advance, so I skipped its dead ends: `node_type_search` for render settings and the `pathattr` investigation. **I did not skip any lookup that 1.2 was meant to make unnecessary.** I made no `node_type_info` call for either light, because the USD names now work, and 4 paged `usd_stage` calls became 1 `summary` call. I also repeated the `resolution: [640, 360]` mistake on purpose to check papercut 4.

---

## 2. Measurements, side by side

**Totals**

| | 1.1 (review 13) | 1.2 (this run) |
|---|---:|---:|
| Calls | 66 | **43** |
| Text bytes | 72,732 | **50,373** (28,213 without the 5 identical capture crashes) |
| Pretty bytes | 99,133 | 59,377 |
| Args bytes | 7,803 | 6,060 |
| Errors | 7 (2 deliberate probes, 1 my own mistake) | 11 (5 deliberate probes, 1 repeat of review 13's mistake, 1 my own mistake, **5 capture crashes**) |
| Seconds in tools | 34.5 | 49.4 (28.9 of it in `viewport_capture`) |
| Wall clock | 6 min 20 s | 5 min 09 s |
| Images returned | 1 (a `viewport_capture` of `/obj`) | **4** (2 `render` thumbnails, 1 in `job result`, 1 `/obj` capture) |
| `houdini_python` | 0 | 0 |
| `tools/list` (full) | 35 tools, 36,578 B | 35 tools, **32,431 B** |

**Time to first image (from the first tool call)**

| | 1.1 | 1.2 |
|---|---:|---:|
| First Karma frame on disk | 3 min 01 s | **1 min 22 s** |
| First Karma image returned **through the tool** | never | **1 min 22 s** (`render`, 512×288, `attached: true`) |
| First image of any kind returned | 4 min 19 s (`/obj` capture) | **1 min 22 s** |
| Stage image through `viewport_capture` | never (rejected the LOP camera) | **never** (exit 139, N1) |

**Per tool**

| Tool | 1.1 calls | 1.1 text B | 1.1 avg | 1.2 calls | 1.2 errors | 1.2 text B | 1.2 avg | 1.2 max | 1.2 secs |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `usd_stage` | 17 | 24,222 | 1,424 | 12 | 3 | 5,890 | 491 | 1,674 | 0.2 |
| `node_type_info` | 12 | 23,701 | 1,975 | 2 | 0 | 3,461 | 1,730 | 2,778 | 0.1 |
| `events` | 2 | 7,037 | 3,518 | 1 | 0 | 5,039 | 5,039 | 5,039 | 0.0 |
| `parm_get` | 4 | 2,516 | 629 | 2 | 0 | 923 | 462 | 552 | 0.0 |
| `node_create` | 5 | 2,380 | 476 | 4 | 1 | 2,080 | 520 | 803 | 0.5 |
| `node_type_search` | 3 | 2,331 | 777 | 0 | – | – | – | – | – |
| `houdini_status` | 2 | 2,261 | 1,130 | 2 | 0 | 1,211 | 606 | 1,037 | 0.0 |
| `parm_set` | 4 | 2,211 | 552 | 1 | 0 | 1,109 | 1,109 | 1,109 | 0.1 |
| `render` | 6 | 1,513 | 252 | 5 | 1 | 3,380 | 676 | 1,828 | 18.5 |
| `network_describe` | 2 | 1,472 | 736 | 2 | 0 | 2,264 | 1,132 | 1,154 | 0.0 |
| `geo_info` | 1 | 822 | 822 | 1 | 0 | 822 | 822 | 822 | 0.5 |
| `job` | 3 | 738 | 246 | 1 | 0 | 688 | 688 | 688 | 0.0 |
| `viewport_capture` | 2 | 582 | 291 | 7 | 6 | **23,011** | 3,287 | 4,432 | 28.9 |
| `geo_read` | 1 | 551 | 551 | 0 | – | – | – | – | – |
| `hip_save` | 1 | 250 | 250 | 1 | 0 | 250 | 250 | 250 | 0.1 |
| `problems` | 1 | 145 | 145 | 1 | 0 | 206 | 206 | 206 | 0.1 |
| `houdini_connect` | 0 | – | – | 1 | 0 | 39 | 39 | 39 | 0.4 |

- **Where the bytes went.** Lookup and inspection were two thirds of review 13's bytes (`node_type_info` plus `usd_stage`, 47.9 KB). In 1.2 they are 9.4 KB. The stage summary, the attribute filter, `inputs_count` and the USD parm names each removed a whole category of calls. The single largest item in 1.2 is the **5 × 4,432 B crash payload** from `viewport_capture` (22.2 KB, 44 % of all bytes), which is a stack-dump tail with no usable content.
- **`render` grew per call** (252 → 676 B) because it now returns `outputs` and `thumbnail` with real paths. That is the point of the change. The 1,828 B call is the deliberate husk failure with `detail.log_tail`.
- **`network_describe` grew** (736 → 1,132 B avg) because outline rows now carry `inputs` and `flags`. That is worth it in LOPs.

### Errors

| # | Tool / argument | Message (abridged) | Hint | Verdict |
|---|---|---|---|---|
| 14 | `node_create` item 3 `parms.resolution: [640,360]` (repeat of review 13 #25) | `locked`: `/stage/rset/resolution: resolutiony is locked and computed by the expression 'pythonexprf("__import__('loputils').computeResolutionParameter(True, True)")' (now 720).` | `Set resolutionx only (a locked component that already holds the value is skipped), or change what computes resolutiony, such as a mode menu on the node. Last resort: houdini_python …` | **Yes.** Fixed in one retry, with no `parm_get`. |
| 16 | `usd_stage prim: "/lights\|/cameras"` (my mistake) | `No prim at '/lights\|/cameras' on this stage.` | nearby prims, including `/lights` and `/cameras` | Good enough, but see N3. |
| 25 | `render output: ".../probe.0001.xyz/x.$F4.png"` (probe) | `cook_failed`: `… Could not create directory …` | `husk failed; detail.log_tail has the end of its log.` | **Yes.** `log_tail` names the real cause: `Unable to create output directory`. |
| 29–33 | `viewport_capture` with `lop_path: /stage/rset` (×2), `camera: /stage/cam_main`, `lop_path + camera: /cameras/cam_main`, `lop_path: /stage/city` at 480×270 | `internal`: `The render process exited with code 139.` | `See detail.log for the render process output.` | **No.** `detail.log` is the last ~4 KB of a crash dump, containing only idle `OTHER THREAD` stacks (N1). |
| 34 | `viewport_capture camera: /stage/key` (probe) | `/stage/key (distantlight::2.0) is not a camera.` | `Cameras here: /obj/cam_overview, /obj/cam_street, /stage/cam_main. A LOP camera node, or a camera prim with lop_path, captures the stage.` | **Yes.** It lists the LOP camera. |
| 36 | `usd_stage lop_path: /stage/karma_rop` (probe) | `/stage/karma_rop (usdrender_rop) has no output stage; read its input /stage/rset.` | `Pass lop_path /stage/rset.` with `candidates` | **Yes.** |
| 37 | `usd_stage prim: /city/bldg_999` (probe) | `No prim at '/city/bldg_999' on this stage.` | five nearby prims | Yes, the same as 1.1. |

---

## 3. The ten papercuts from review 13

| # | Papercut (review 13) | Verdict | What 1.2 shows now |
|---|---|---|---|
| 1 | `render` on USD ROPs reports no output and no thumbnail | **Fixed** | `outputimage` was empty, and the output came from the RenderProduct: `"outputs":[".../city_lookdev.0001.exr"]`, `"thumbnail":{"path":".../city_lookdev.0001.exr","width":512,"height":288,"image":{"mime_type":"image/png",…,"attached":true}}`. The EXR thumbnail works. `job result` after `wait_s: 0` carries the same outputs and the image. No `missing: [__render__.usd]`. |
| 2 | `render output:` overrides `lopoutput` | **Fixed** | `output: ".../city_ov.$F4.png"` wrote `city_ov.0001.png` and returned it as `outputs` and as the thumbnail. Afterwards `outputimage` was back to `""` and `lopoutput` to `__render__.usd`. A husk failure now carries `detail.log_tail: ["[21:15:42] Access error: …/x.0001.png - Unable to create output directory …"]` and the hint `husk failed; detail.log_tail has the end of its log.` |
| 3 | `viewport_capture` shows `/obj`, rejects LOP cameras | **Improved in contract, still blocked in practice** | Without arguments it still captures `/obj`, but now says so: `"scene":"obj"`, notes `The scene also has a stage (/stage/rset is displayed in /stage); pass lop_path (or a LOP camera) to capture it.` LOP cameras are accepted, and a light is refused with the scene's camera list. **But every stage capture crashed the render process** (exit 139, N1), so I still got no image of the stage from this tool. |
| 4 | Locked tuple component fails the batch; hint sends you to `houdini_python` | **Improved** | The message names the component, the expression and its current value (`resolutiony … (now 720)`). The hint leads with `Set resolutionx only`, and `houdini_python` is now the "Last resort". The batch is still rolled back as a whole, and the hint says "a mode menu" where it could name `res_mode: manual`. |
| 5 | `usd_stage` cannot count or bound the stage | **Fixed** | `summary: true` returned `{"total_prims":193,"counts_by_type":{"Mesh":192,"Xform":1},"bbox_world":{"min":[-214,0,-214],"max":[214,93.05,214],"size":[428,93.05,428]}}` in **200 B**, instead of 4 calls and 14.4 KB. `total` is on every page (`"total":193,"next_cursor":"5"`). Children still come back in reverse name order. |
| 6 | `include: attributes` has no filter | **Fixed** | `attribs: "inputs:*"` on `/lights`: 1,291 B, against 2,409 B unfiltered in 1.1. Camera with `attribs: "focalLength\|*Aperture\|clippingRange"` plus `xform`: **512 B**, against 1,854 B. `world` is dropped when it equals `local`, and `clippingRange` (2 elements) is listed in full. I saw no per-attribute `time_sampled` flag; it is not documented either. |
| 7 | Encoded USD parm names cost a type lookup per light | **Fixed** | `node_create parms: {"inputs:intensity": 3.0, "inputs:color": [...]}` worked first try. `parm_set /stage/key/inputs:intensity` returned the resolved `"path":"/stage/key/xn__inputsintensity_i0a"`, and `parm_get` reads `inputs:*` the same way. 0 `node_type_info` calls for lights, against 2 calls and 4.2 KB. |
| 8 | `node_type_info` returns full inputs and folders when filtered | **Fixed** | `{type: "Vop/mtlxstandard_surface", parms: "base*\|specular_roughness\|specular"}` returned **683 B** (`"inputs_count":42`), against 3,299 B. |
| 9 | `events` is mostly noise | **Improved** | `events since 0` after the build: **34 events, 5,039 B** (1.1: 54 events, 6,451 B for 50). Fixed: the rolled-back batch (#14) recorded nothing, `render`'s set and restore recorded nothing, and the shaders created inside `matlib` now have their `ChildCreated`. Still there: **9 of 34** are callback writes with `origin: "agent"` (`xn__houdiniguidescale_s3a` ×3, `*Converted` ×5, `resolution` on rset). The `ry` keyframe plus the `rx` set show as one `{"parm":"r","count":3}` with no keyed marker. **New:** every top-level `ChildCreated` is reported twice (N2), which is 8 of the 34. That leaves 17 of 34 meaningful events. |
| 10 | `usd_stage` on a ROP LOP contradicts itself; the outline has no display LOP | **Fixed** (one leftover) | `/stage/karma_rop (usdrender_rop) has no output stage; read its input /stage/rset.` with `candidates: ["/stage/rset"]`. The outline rows now carry `inputs` (the whole chain is readable) and `"flags":["display"]` on `rset`. Leftover: `matlib` still reports `"display":"/stage/matlib/concrete"`, which means nothing in a VOP network. |

**Honourable mentions from review 13:**
- `parm_set` and `parm_get` still return `raw` as a string equal to `value` (`"value":1.8,"raw":"1.8"`), and on tuples (`"raw":["430","300","430"]`). **Unchanged**, and the `parm_set` notes now claim "raw is left out when it equals value".
- `doctor` still does not warn about a literal `houdini__HVER__` directory next to the resolved one. **Unchanged.** I tested this with both directories present, which is a weaker test than review 13's.
- I did not retest the anonymous layer ids in `include: layers`.

---

## 4. New papercuts

### P0

**N1. Every stage `viewport_capture` crashes the render process, and the error carries 4.4 KB of useless crash dump.**
- **Calls:** `{lop_path: "/stage/rset"}`, `{lop_path: "/stage/rset", resolution: [960,540]}`, `{camera: "/stage/cam_main", resolution: [960,540]}`, `{lop_path: "/stage/rset", camera: "/cameras/cam_main", source: "opengl_rop", resolution: [640,360]}`, and `{lop_path: "/stage/city", resolution: [480,270]}`, which is a stage with only the SOP import (no lights or materials).
- **Exact message:** `{"code":"internal","message":"The render process exited with code 139.","hint":"See detail.log for the render process output.","hou_exception":"render process exit 139","detail":{"log":"STEM32\\ntdll.dll\nOTHER THREAD 60040\n+0x7ffce3800e44 [NtWaitForSingleObject] …-- TRACEBACK END --\n"}}`. Each one is 4,432 B. The `log` is the last 4 KB of a crash report, made of idle `IlmThread`/`QThread` stacks. The crashing thread and the signal are cut off.
- **Context:** a `/obj` capture through the same `opengl_rop` source, in the same session, 15 s earlier, worked (7.7 s, 1024×768). No other hython or husk was running. An unrelated GUI Houdini (pid 59436, another session) was open. The host stayed up and answered every later call; the Karma renders before the captures were fine. I cannot tell from the tool surface whether this is the HocusPocus stage path or Houdini's OpenGL/Storm in a headless child on this machine. **The tool should not leave that question to the caller.**
- **Proposed change:** (a) put the head of the crash report (the crashing thread and the exception) into `detail.log`, not the tail, and cap it at about 1 KB. (b) Map exit 139 or `0xC0000005` to a specific `code` (`render_crashed`) with a hint: `the OpenGL ROP crashed rendering the stage; render the stage with render on a Karma ROP for a look, or retry with source viewer in a GUI session`. (c) Add a headless stage-capture smoke test, with a sopimport-only stage like the last call above, to the hython suite so the CHANGELOG claim "Stage captures work both headless and in the GUI" is checked on the release machine.

### P1

**N2. `events` reports every top-level `ChildCreated` twice.**
- `{"seq":1,…,"kind":"ChildCreated","path":"/stage/city",…}` and `{"seq":2,…}` are identical, with the same timestamp. The same is true for `matlib`, `assign`, `key`, `fill`, `cam_main`, `rset` and `karma_rop` (16 events for 8 nodes). The nested shaders (`/stage/matlib/concrete`, `asphalt`) appear once. This looks like the new nested-node path and the old `/stage` child callback both firing. **Proposed change:** deduplicate by `(kind, path, call)` before the held events are released.

### P2

**N3. `usd_stage prim` does not take `a|b` alternation, unlike `attribs` and `node_type_info parms`.** `prim: "/lights|/cameras"` fails as "No prim at '/lights|/cameras'". The hint does list both prims, so it costs one retry. `prim: "/city/bldg_00*|/city/ground"` is worse: it returns `{"prims":[],"total":0}` with no error and no note. Either support `|` the way the other globs do, or reject it with a hint.

**N4. `render` with an output it cannot thumbnail says nothing.** `output: ".../probe.$F4.xyz"` returned `outputs: [.../probe.0001.xyz]`, `state: done`, and no `thumbnail`, `thumbnail_error` or note. A `thumbnail_error: "unsupported format .xyz"` would close the gap.

**N5. The version strings still say 1.1.0** on `release/1.2`, whose CHANGELOG says `1.2.0`: `hocuspocus version` → `hocuspocus 1.1.0`, `houdini_status` → `bridge_version` / `host_version` `"1.1.0"`. An agent cannot tell from the session which contract it is talking to.

**N6. `hocuspocus launch --hip X` says "$HIP of the untitled scene is <cwd>".** I launched with `--hip city_v01.hip`, and the scene was not untitled: `houdini_status` showed the hip loaded and `HIP` = the city directory. The line comes from the new `--work-dir` behaviour and should be suppressed, or reworded, when `--hip` is given.

**N7. The husk failure repeats its message three times.** The same text appears in `message`, in `detail.errors[0]`, and in parts of `detail.errors[1..2]`, before `log_tail` (1,828 B in total). Keep `message` and `log_tail`, and drop the duplicate `errors` entries.

---

## 5. Verdict

**1.2 fixes the Solaris lookdev loop, apart from the viewport.** Seven of the ten papercuts are fixed (1, 2, 5, 6, 7, 8, 10). Two improved (4, 9). One (3) is fixed in contract but blocked in practice by a new crash. The workload took 43 calls instead of 66 and 50 KB instead of 73 KB (28 KB without the crash payloads). Inspection bytes fell by 80 % (47.9 KB → 9.4 KB), and the Karma image comes back through `render` 1 min 22 s after the first call, where 1.1 never returned it. Every probe that had a mediocre answer in 1.1 now has a precise one, and I needed no `houdini_python` and no manual parm work-arounds. `houdini_connect {quit: true}` closed the host cleanly.

**What blocks "done" for Solaris:** N1. A stage capture is the quick look that the `render` notes point to ("viewport_capture is the quick look"). Headless, on this machine, it crashed 5 times out of 5, and the error gave a model nothing to act on. Until a headless stage capture is proven on the release machine, `render` on a Karma ROP is the only working way to see the stage. It costs about 5 s per frame and is reliable. Second priority is N2, the duplicate `ChildCreated` events, which undoes part of the `events` noise work. N3 to N7 are polish.

Evidence: `docs/redesign/evidence/city-destruction/31_lookdev_capture_1.2.png` (512×288, 186 KB) is the inline `render` thumbnail of the final look (Karma, `city_ov.0001.png`), **not** a `viewport_capture`, because no stage capture succeeded.
