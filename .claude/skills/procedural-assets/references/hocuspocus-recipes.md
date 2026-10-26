# HocusPocus recipes for generator work

Concrete tool calls for each phase, and the traps earlier agents hit building the neo_tower
and mini_tower generators (docs/redesign/review/26 and 28). Argument shapes are HocusPocus
2.1; when unsure, read `inspect {what: "tool", target: "<tool>"}` before guessing.

## Session

- `houdini_status`, then `houdini_connect {launch: {mode: "headless"}}` unless the user has a
  GUI session to share. Pin your own instance if several are listed; never drive the user's.
- `hip_save {path: "<project>/work/<name>_v001.hiplc"}` early and often. A launched Houdini
  usually dies with the MCP server. The licence decides the extension: `.hiplc`/`.hdalc` on
  Indie, `.hipnc`/`.hdanc` on Apprentice, `.hip`/`.hda` on Commercial.
- Keep code (VEX, Python) in files under the project, not only in parms: they diff, survive a
  crash and feed `value_file`.

## Plan and network building with `edit`

One `edit` call can build a whole stage. Later ops refer to earlier ones as `$id`.

```json
{"ops": [
  {"op": "create", "id": "geo", "parent": "/obj", "type": "geo", "name": "tower"},
  {"op": "create", "id": "plan", "parent": "$geo", "type": "attribwrangle", "name": "plan_bays",
   "parms": {"class": "detail"}},
  {"op": "set", "path": "$plan/snippet", "value_file": "$HIP/vex/plan_bays.vfl"},
  {"op": "create", "id": "kit", "parent": "$geo", "type": "null", "name": "KIT_IN"},
  {"op": "create", "id": "cp", "parent": "$geo", "type": "copytopoints::2.0", "name": "place_modules",
   "inputs": [{"index": 0, "from": "$kit"}, {"index": 1, "from": "$plan"}],
   "parms": {"useidattrib": 1, "idattrib": "name", "pack": 1}},
  {"op": "set", "path": "$cp/targetattribs", "multiparm_count": 1},
  {"op": "set", "path": "$cp/applyattribs1", "value": "Cd grime lit variant id"},
  {"op": "create", "parent": "$geo", "type": "null", "name": "OUT", "inputs": [{"index": 0, "from": "$cp"}],
   "flags": {"display": true, "render": true}}
], "dry_run": true}
```

- **Copy to Points 2.0 made by script copies no plan attributes.** Its "Attributes from
  Target" multiparm (`targetattribs`) starts with zero entries (the tab-menu tool adds one).
  Set the count and list the attributes the pieces need (`applyattribs1`), as above, or the
  copies come out without colour, grime or variant data.
- Run big builds with `dry_run: true` first. Ops are checked in order against what earlier ops
  left, so a dry run agrees with the real run.
- `partial: "stop"` keeps the ops before a failure; resend the rest with `$id`s replaced from
  the result's `ids`. Without it, one bad menu token rolls back the whole call.
- Parm names differ from labels and between node versions. When a parm is unknown, read
  `inspect {what: "type", target: "Sop/<type>", parms: "<glob>"}` and follow the error's
  candidates.
- `edit` cooks touched nodes after the change; a cook past 10 s becomes a job and rows say
  `cook_state: "cooking"`. Read the job before assuming the network is good.

## Long code

- Set a snippet from a file: `{"op": "set", "path": ".../snippet", "value_file": "$HIP/vex/facade.vfl"}`.
- Change a few lines in place: `{"op": "set", "path": ".../snippet", "patch": [{"find": "float h = 3.2;", "replace": "float h = ch(\"floor_h\");"}]}`.
  Each `find` must occur exactly once; the error shows the nearest lines when it does not.
- Read it back whole: `inspect {what: "parms", target: ".../snippet", full_strings: true}`.
- VEX compile errors come back in the node row with line and column.
- VEX traps when writing blind:
  - overloads are ambiguous when the return type is not obvious: `point(0, "P", i)` inside
    another call, `array(set(...), ...)`, `rand()` in a `lerp`. Assign to a typed local
    first (`vector p = point(0, "P", i);`);
  - `foreach` over an inline `array(...)` can be ambiguous; declare the typed array first;
  - there is `smooth()`, not `smoothstep()`;
  - no `<<` or `>>` shift operators: index corners with `/` and `%`;
  - vector literals hold constants only (`{1, 2, 3}`); with variables use `set(x, h, 1)`;
  - define functions before any statement in the snippet;
  - a wrangle reads its input, not points it has just added: compute new positions instead of
    reading them back.
- Keep shared helpers in one `lib.vfl` and prepend it to each piece's snippet when you
  assemble the file for `value_file` (a wrangle's `#include` only finds files on
  `HOUDINI_VEX_PATH`). One helper library across many small wrangles beats one huge wrangle.
- **A build script is a fair choice for a big generator.** With dozens of wrangles, a
  `build.py` run through `houdini_python` that creates the network and reads each snippet
  from its `.vfl` file is reproducible and keeps the source diffable. Write the script with
  the client's file tool, not a shell heredoc, whose quoting breaks on VEX. Iterate on one
  wrangle with `edit` (`value_file`, `patch`) rather than rerunning the whole script. The
  HDA stores the snippets, so the asset does not depend on the files.

## Kit pieces as separate networks

Author each kit piece (wall_mid, window_bay, corner_out, cornice, …) as its own small SOP
chain ending in a named null, with the shared pivot convention and a prim `name` attribute
holding the piece name (`wall_mid_01`). Merge them into one kit stream feeding Copy to
Points' first input. The plan's points carry a `name` attribute choosing the piece, plus
`orient` (or `N` and `up`) and `pscale`/`scale`; Copy to Points' Piece Attribute
(`useidattrib`, `idattrib: "name"`) matches the two, and Pack and Instance (`pack`) keeps
copies as instances. Then a piece can be looked at, LOD'd and varied alone.

## Interface and asset

- Spare parms with folders and conditions, on the subnet before it becomes an asset:

```json
{"ops": [{"op": "node", "path": "/obj/tower/gen", "spare_parms": {"add": [
  {"name": "floors", "type": "int", "label": "Floors", "default": 24, "min": 1, "max": 120, "folder": "Massing"},
  {"name": "floor_h", "type": "float", "label": "Floor Height", "default": 3.5, "min": 2.8, "max": 6, "folder": "Massing"},
  {"name": "style", "type": "menu", "label": "Style", "menu_items": [{"token": "tokyo3", "label": "Tokyo-3"}, {"token": "neotokyo", "label": "Neo-Tokyo"}], "folder": "Style"},
  {"name": "interior", "type": "toggle", "label": "Interior", "default": false, "folder": "Interior"},
  {"name": "partitions", "type": "int", "label": "Partitions", "default": 4, "folder": "Interior", "disable_when": "{ interior == 0 }"},
  {"name": "seed", "type": "int", "label": "Seed", "default": 1, "folder": "Variation"}
]}}]}
```

  Toggle defaults are `true`/`false`, not 1/0. Folder entries take `folder_type` (tabs,
  collapsible, simple, radio).
- Make the asset: `hda {action: "create", path: "/obj/tower/gen", name: "studio::tower_gen::1.0", library_path: "$HIP/../tower_gen.hdalc"}`.
- Save changes and relock: `hda {action: "save", path: "/obj/tower/tower_gen1", help: "= Tower generator =\n...", lock: true}`.
- New version when output changes: `hda {action: "version", path: ..., version: "1.1", switch: "path"}`.
- Read it: `hda {action: "info", path: ...}` (interface, conditionals, instances, lock state).
- Editing inside a locked asset fails with `locked`; `hda {action: "unlock"}` first.

## Looking at the work

- Draft, often: `look {target: "/obj/tower/gen/place_modules", quality: "draft"}` shows that
  SOP alone, even inside an asset.
- Lit check with the scene's lights: `look {quality: "lit", camera: "/obj/cam_hero"}`.
- Final evidence to a file: `look {quality: "final", camera: "/obj/cam_hero", resolution: [1600, 900], output: "$HIP/../evidence/hero.jpg", jpeg_quality: 85, wait_s: 120}`.
  A look past `wait_s` returns a job; `job {action: "result", job_id}` gets the image.
- Rendering a Karma ROP: `render {rop_path: "/out/karma_hero", frames: [1, 1], output: "...", wait_s: 0}`
  then poll `job`. Headless Karma ROP renders run in a child process, so Houdini stays free.
- Look at evidence images yourself (read the file) before calling a phase done.
- Save every gate image with `look {output}` when you make it: the capture folder keeps only
  the newest 50 looks, so an early gate image is gone by the end of a long session.
- Cameras: aim with the camera's Look At parm (`lookatpath` to a null at the target) instead
  of computing rotations. A dedicated contact-sheet camera beats the automatic look framing
  when instances sit in rows.

## Lighting for checks and evidence (Karma)

- Karma light intensities are not the values a Flipbook "lit" look expects; a sun near 1–1.5
  plus a sky dome near 0.5 is a neutral daylight start. Judge exposure on a grey card or a
  known material, not by eye on a white wall.
- An environment light is invisible to the camera by default; turn on
  `light_contribprimary` to see the sky, or the background renders black.
- A vertical gradient made in Copernicus and written to a lat-long image makes a cheap,
  controllable sky.
- Glass: an opaque standard surface hides everything behind it, including modelled rooms and
  lit interiors. Use thin-walled transmissive glass (or an interior-mapping material) and
  test windows at night early, because a dark facade at night is the first sign.

## Measuring

- Per-role QA in one call: `inspect {what: "geo", target: ".../OUT", group_by: "surface", attribs: "Cd"}`
  gives prims, points, triangles, area and bbox per value. Use it for budgets and for "every
  polygon has a role".
- Cost of a toggle: `cook {paths: [".../OUT"], profile: true}` times only what a normal cook
  runs and lists the rest in `inactive`, which proves a switched-off branch costs nothing.
  It treats a locked asset as one node and already-cooked nodes as cached, so to prove a
  branch inside an asset, compare the internal nodes' cook counts before and after a cook
  (`inspect {what: "node", paths, recurse_locked: true}` shows `cook_state`), with the
  asset unlocked or on the master copy.
- A node outside the display chain can hold stale geometry; `cook {force: true}` it before
  reading its numbers.
- Stale upstream state (a material SOP that cooked before its materials existed, a File COP
  serving an old image): `cook {paths: [...], force: "chain"}`.
- Everything wrong in a network: `inspect {what: "problems", target: "/obj/tower"}`.

## Materials (Karma, MaterialX)

- Make a material as a VOP subnet in `/mat` with the `material` flag set
  (`{"op": "node", "path": "/mat/m_panel", "flags": {"material": true}}`) containing an
  `mtlxstandard_surface` wired to a `subnetconnector` named `surface`. Without the flag a
  Material Library LOP imports nothing.
- MaterialX `signature` parms accept every signature the node defines (`color3`, `float`,
  …), even though Houdini's menu lists only `default`.
- Assign by attribute in SOPs (`shop_materialpath` per prim, or Material SOP groups), and
  check it landed: `inspect {what: "geo", target, group_by: "shop_materialpath"}`.
- SOP `Cd` reaches USD as the primvar `displayColor`. A `geompropvalue` reading `"Cd"`
  returns black in Karma; read `"displayColor"`.
- Copy to Points' attribute-apply menus (`applyto1` …) take tokens (`prims`, `points`,
  `verts`). Set by index, 1 is vertices: a `shop_materialpath` copied there assigns
  nothing, and no warning says so.

## Textures in Copernicus

- Build the trim sheet, tiling materials and mask layers in a COP network, look at each with
  `look {target: "/img/..."}`, and write files with a ROP or `look {output}`.
- After overwriting a file another node reads, `cook {force: true}` on the reader reloads it,
  and `look` notes a reader whose file is newer than its cooked image.

## Exports

- FBX per LOD through an FBX ROP (`render {rop_path}`), collision meshes named
  `UCX_<mesh>_00`…
- USD through a USD ROP, with an LOD variant set and material bindings; check bindings with
  `inspect {what: "stage", target: "/stage/...", attribs: "material:binding*"}`.
- Prove it: `hip_new`, re-import, render with only the exported textures, and compare
  triangle counts and material slots.

## What is installed

Check before planning around a node: `search {kind: "types", query: "<name>"}`. SideFX Labs
(LOD Create, Impostor Baker, Trim Texture, Texel Density, Physical AO) is often not
installed; core PolyReduce, Convex Decomposition, Copernicus and the Bake Geometry Textures
COP are. The Font SOP's `file` parm takes a font *name*; Houdini ships "SideFX WenQuanYi Zen
Hei" for Japanese and Chinese text. Its `lod` parm sets the curve sampling: 0.35 instead
of 1.0 cut a building number from 11.4k to 4.2k triangles with no visible change at 10 m.
`valign` takes the token `middle`.

## Traps seen in practice

- A monolithic VEX generator (one 350-line wrangle) is fast to start and slow to improve.
  Split plan, pieces and placement.
- Window lighting randomised per window reads as noise; light floors or zones together.
- A Material SOP that cooked before `/mat` existed keeps its warning silently; force the chain.
- Karma final looks on big scenes take longer than 10 s; pass `wait_s` or poll the job.
- `@ptnum`-based randomness reshuffles when topology changes; hash a stable `id`.
- Judging only at 1,000–1,600 px hides small defects; add close-up and distance views.
- Some faults show only in the exported file: a wire from the wrong output, LOD0 detail in
  LOD1. Re-import every export and count triangles and named parts per LOD.
