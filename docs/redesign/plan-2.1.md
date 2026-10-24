# HocusPocus 2.1 plan

2026-10-24. Branch `release/2.1` from `v2.0.0`. The bible (`docs/BIBLE.md`) stays the
authority; this plan names what 2.1 changes and how it is judged.

## 1. Why 2.1

2.0 shipped with four promises and one unmet target (spec-2.0 §7, CHANGELOG 2.0.0):

1. remove `compat_1x` and the `v2` alias (D39, migration-2.0 §8);
2. close the scorecard bytes margin (18 % measured against the 20 % predicted);
3. stub modal `hou.ui` calls during a call in a GUI session (parity G5);
4. qualify Linux and macOS.

2.1 also adds the hardest evaluation so far: an agent builds a **game-ready procedural
skyscraper generator** through the MCP tools only. The earlier workloads (city, FX,
lookdev, PDG, Vellum) asked an agent to make a scene. This one asks it to make a tool
another artist would use: an HDA with a designed parameter interface, UVs, materials,
baked textures, LODs, interiors and an export path. It is the dogfood for 2.1, and its
friction log decides the rest of 2.1's scope.

## 2. The dogfood workload: `neo_tower`

**Brief.** A SOP HDA `hp::neo_tower::1.0` that generates futuristic skyscrapers in the
look of 1980s and 1990s science-fiction anime: Tokyo-3 in *Neon Genesis Evangelion*
(retractable armoured towers, setback tiers, panel seams, warning stripes, dusk orange and
NERV purple) and Neo-Tokyo in *Akira* (dense vertical slabs, ribbon windows, rooftop
signage, red neon, haze). The result must be usable in a game engine.

**Required outputs.**

| Area | Requirement |
|---|---|
| Massing | Footprint (rect, chamfered, stepped, round), floors and floor height, setback tiers, crown (antenna mast, helipad, spire, armour cap), seed |
| Facade | Floor-aligned modules: ribbon windows, panel grid, louvers, mullions, panel seams, greebles (vents, pipes, AC units, lights), signage slots |
| Interiors | Per floor: slab, ceiling, core with lift shafts and stair, corridor and partition walls, door openings, glazing with frames; finished surfaces, no furniture |
| Game readiness | UVs at a stated texel density, material ids per surface type, PBR texture set (base colour, normal, roughness/metal, emissive for windows), LOD0–LOD2, a collision proxy, a poly budget, export to FBX and USD |
| Look | Karma renders at dusk and night, a block of 6+ variations from seeds, a cut-away showing interiors |

**What is measured.** Calls per tool, text bytes, every `houdini_python` call with the
reason no tool fitted, every error and whether its `hint` led to the fix, wall time per
phase, and a capability verdict per area: *native* (tools express it), *escape hatch*
(only through `houdini_python`), *blocked*.

**Phases.** P1 massing, facade and interiors; P2 UVs, materials, textures, LODs, collision
and export; P3 lookdev, a variation block and the evidence set. Each phase saves a hip and
the HDA, and appends to `review/26-neo-tower-dogfood.md`, so another agent can continue
from the saved state. Evidence goes in `evidence/neo-tower/`; the HDA and its build notes
go in `examples/neo_tower/` (exports and caches are not committed).

## 3. Engineering streams

| Stream | Scope | Exit |
|---|---|---|
| A. compat removal | Delete the `compat_1x` profile, its 18 tool specs, 1.4 resources and prompts, and the `v2` alias. A removed tool name still answers `invalid_argument` with the 2.0 replacement in `hint`. | Goldens regenerated; budget caps reset for the 2.0 profiles only; every tier green |
| B. modal stub and portability | G5: during a call in a GUI session, modal `hou.ui` entry points raise `ui_required` naming the call; a GUI test with a user dialog closed by a timer pins the executor. Portability audit of paths, process launch, signals and pref dirs for Linux and macOS, with the unit tier run on them in CI. | G5 marked done in parity.md; audit in `review/27-portability.md` |
| C. bytes margin | Guide resource and session tool results, measured by the workloads tier | `scorecard_twelve` ≥ 20 % fewer bytes than 1.4 |
| D. dogfood fixes | The tool changes the neo_tower friction log asks for, ranked by calls saved and escapes removed | Re-run of P1–P3 on the fixed build uses fewer calls and fewer `houdini_python` escapes |

Hython and GUI qualification on Linux and macOS needs a licensed Houdini on those systems.
This machine has only Windows, so 2.1 qualifies the unit tier there and records the
Houdini tiers as not run.

## 4. Release rule

2.1.0 ships when streams A–D meet their exits, the dogfood re-run is written up, all tiers
are green on Windows, and CHANGELOG, migration notes and the bible's decision log carry
the changes.
