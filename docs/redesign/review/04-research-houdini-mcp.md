> **Status: historical.** Describes HocusPocus 0.9, archived at tag `v0.9-archive`. See [`../README.md`](../README.md).

# 04 - Research: Houdini 22 HOM, Houdini MCP prior art, MCP design practice

Status: research input for the HocusPocus redesign. Date: 2026-10-12.
Target: Houdini 22.0.466 (Indie licence on this machine), `hython` = Python 3.13.10.

Notation: **[verified]** = reproduced on this machine with
`"C:\Program Files\Side Effects Software\Houdini 22.0.466\bin\hython.exe"`
(probe scripts are in the session scratch dir and are not committed). **[doc]** = taken from
the linked SideFX or MCP documentation and not reproduced here. **[source]** = read from the
shipped Python source under `$HFS/houdini/python3.13libs`.

---

## Executive summary (design-relevant)

1. **Threading.** `hou` calls from a background thread can work because of the HOM lock, but
   UI, Qt and PythonPanel calls must run on the main thread. The supported way to marshal work
   is `hdefereval`, which is implemented on `hou.ui.addEventLoopCallback`. It has no timeout. It
   deadlocks if you call it from the main thread. It also discards the traceback. `hdefereval`
   **cannot be imported in hython** (`ImportError: hdefereval is only available in a graphical
   Houdini`), and `hou.ui` does not exist there. A server therefore needs its own
   main-thread executor, with a GUI backend (event-loop callback) and a headless backend (a
   queue pumped by the main thread). **[verified]**
2. **The official MCP Python SDK (`mcp==2.3.0`) runs inside Houdini 22's Python 3.13.** It
   installs with `hython -m pip install --target <dir>`, imports in about 0.4 s, and serves
   Streamable HTTP through uvicorn on a worker thread. Tool handlers marshal to the main thread
   through a future queue. **[verified]** The dependencies are pydantic 2.14, anyio, starlette,
   uvicorn, httpx2, cryptography and pywin32. pywin32 needs `site.addsitedir()` plus
   `os.add_dll_directory()` when vendored with `--target`. Several of these packages shadow
   older copies that Houdini ships (attrs 22.2, cryptography 45, click 8.1).
3. **`hwebserver` is not a viable MCP substrate in 22.0.466.** `apiFunction` works, but
   handlers run off the main thread. `registerASGIApp` returned an empty body and then
   **segfaulted hython** with both single-chunk and streaming responses. **[verified]**
   `hrpyc` is classic RPyC (`SlaveService`) with no authentication and no main-thread
   marshaling. **[source]**
4. **H22 has a native JSON graph serialization.** `node.asData()`,
   `childrenAsData(inputs=True, flags=True, position=True)`, `setChildrenFromData()` and the
   `hou.data` module round-trip nodes, wiring, flags and expressions. **[verified]** This is
   the natural basis for a declarative "describe/apply graph" tool.
5. **Headless visual feedback works.** The OpenGL ROP renders a PNG from hython in about 7 s
   on the first frame. Copernicus `CopNode.layer()` cooks headless (1024x1024 in 2.3 s).
   `SceneViewer.flipbook()` needs the GUI. **[verified]**
6. **MCP spec drift is large.** The 2026-07-28 revision makes MCP stateless: no `initialize`
   handshake, no `Mcp-Session-Id`, server-minted handles passed as tool arguments, tasks moved
   to an extension, and Logging/Sampling/Roots deprecated. SDK v2.3 serves 2025-11-25 and
   2026-07-28 at the same time. Design for **explicit handles in tool arguments** (scene
   generation, node `sessionId`), not transport sessions.
7. **Prior-art servers** (Part B) range from 16 mode-parameter tools to 296 tools. Every
   large one had to add profiles, progressive skill loading or meta-tools. All ship an
   `execute_python` escape hatch. Their recurring failures are:
   - main-thread deadlocks and freezes;
   - long renders inside request timeouts;
   - slow startup handshakes;
   - framing and version mismatches;
   - unauthenticated exec sockets.

   The most mature project (fxhoudinimcp) uses `hwebserver` plus `hdefereval` in the GUI. Its
   H22 issue #12 independently confirms hwebserver's per-thread state and the missing
   `python3.13libs/uiready.py` autostart.

---

## Part A - Houdini 22 HOM facts

### A1. Threading model

- **The HOM lock.** HOM calls from non-main threads are serialized by a global "HOM lock". The
  UI event loop releases the lock while it waits for events and reacquires it to handle one.
  Threads started from Houdini join the main thread's lock group
  ([HDK HOM_Module.h](https://www.sidefx.com/docs/hdk/_h_o_m___module_8h_source.html),
  [extending HOM in C++](https://www.sidefx.com/docs/houdini/hom/extendingwithcpp.html)).
  Qt/PySide widgets and `hou.PythonPanel` methods must be created and called on the main
  thread ([HOM Qt cookbook](https://www.sidefx.com/docs/houdini/hom/cb/qt),
  [PythonPanel](https://www.sidefx.com/docs/houdini/hom/hou/PythonPanel.html)).
  Practical rule: run **every** mutating or UI-touching call on the main thread. Read-only
  geometry access from a worker usually works, but it races with cooks.
- **`hou.ui.addEventLoopCallback(cb)`** runs `cb` "whenever Houdini's event loop is idle",
  roughly every 50 ms. **`hou.ui.postEventCallback(cb)`** runs it once on the next loop
  iteration ([hou.ui](https://www.sidefx.com/docs/houdini/hom/hou/ui.html)).
- **`hdefereval`** [source]:
  - It is built on `addEventLoopCallback`.
  - API: `executeDeferred` (fire and forget), `executeDeferredAfterWaiting(code, n)` (useful
    at startup before the UI is ready), and `executeInMainThreadWithResult` (blocking).
  - It has no timeout parameter. A modal dialog or a long cook stalls every waiting caller.
  - Calling it **from the main thread** blocks on a condition only the main thread can
    signal, which is a deadlock.
  - It re-raises only the exception value: "Right now we discard the traceback".
  - At import it does `if not hou.isUIAvailable(): raise ImportError(...)`.
  - The current HocusPocus `live/dispatcher.py` already uses it together with
    `hou.ui.postEventCallback`.
- **hython/hbatch** [verified]:
  - `hou.isUIAvailable()` is `False`. `hasattr(hou, "ui")` and `hasattr(hou, "qt")` are both
    `False`. `import hdefereval` raises `ImportError`.
  - There is no event loop, so a server must pump a `queue.Queue` from the main thread. This
    pattern served MCP tool calls with `on_main=True` in probe 10.
- **Recommended executor.** Use a `MainThreadExecutor` with two backends: `hou.ui`
  event-loop callback (GUI) and a queue pump (headless). It should have:
  - a per-call timeout that returns a "Houdini busy" tool error rather than hanging;
  - a check that runs the callable inline when already on the main thread;
  - the full traceback string captured inside the main-thread wrapper;
  - an `hou.isUIAvailable()` probe to pick the backend;
  - a cooperative interrupt path (`hou.InterruptableOperation`) for long cooks.

### A2. Transport substrates inside Houdini

| Substrate | Facts | Verdict |
|---|---|---|
| **`hwebserver`** ([docs](https://www.sidefx.com/docs/houdini/hwebserver/index.html)) | C++ multithreaded server with one instance per session. `run(port, debug, max_num_threads=4, in_background=None, ...)`; `in_background` defaults to True in the GUI and False in hython, where `run()` blocks [source]. The docstring says Python handlers "cannot usually run concurrently" (global lock and GIL), and of `apiFunction`: "There is no guarantee which thread the server will call the API function from". Supports `@urlHandler`, `@apiFunction`, `@webSocket`, `registerWSGIApp` and `registerASGIApp` on the `haio` event loop. | `apiFunction` worked: POST `/api` returned JSON, handler `main=False` [verified]. `registerASGIApp`: empty body and then **segfault** in hython for both one-chunk and two-chunk responses [verified, 22.0.466, not tested in GUI]. **Not recommended** for MCP Streamable HTTP. Plain `apiFunction` RPC plus `hdefereval` works in GUI sessions; fxhoudinimcp ships this way, with H22 caveats in Part B. |
| **stdlib `http.server` / uvicorn on a worker thread** | Full control. MCP SDK v2 `streamable_http_app()` is a Starlette app. | **Recommended.** Verified end to end in hython (probe 10): `initialize` with instructions, `tools/list` with annotations, `tools/call` executed on the main thread. |
| **`hrpyc`** ([docs](https://www.sidefx.com/docs/houdini/hom/rpc.html)) | `start_server(port=18811, use_thread=True)` runs an RPyC `ThreadedServer(SlaveService)`, so any remote caller can execute arbitrary code. "The RPC server does not do any authentication." Calls arrive on RPyC threads with no main-thread marshaling [source]. Proxy objects don't support operators, so `node1 == node2` fails. rpyc 4.1.0 is bundled [verified]. | Do not use for an agent. Chatty object proxies and no auth. |
| **`hou.session`** | A per-hip Python module editable in the Python Source Editor. API: `hou.sessionModuleSource()`, `setSessionModuleSource()` and `appendSessionModuleSource()` [verified]. | Do not use as transport. Its code is saved inside the hip file, which is a persistence and security consideration. |
| **Headless `hython` worker** | Full HOM without UI. `hython file.hip script.py`. | Good for render/validate jobs and CI. No `hou.ui`, no flipbook. |

**Launching and discovery from outside**
([command line](https://www.sidefx.com/docs/houdini/ref/commandline.html)):

- `houdini [-foreground] [-n] [-desktop name] file.hip script.py waitforui other.py`.
  `waitforui` defers the following files until the GUI is up. `-foreground` matters only on
  macOS/Linux.
- Startup scripts ([locations](https://www.sidefx.com/docs/houdini/hom/locations.html)):
  - `pythonrc.py` runs very early, before UI and HDAs.
  - `ready.py` runs after HDAs load (GUI and batch).
  - `uiready.py` runs in interactive sessions only.
  - `123.py` runs at FX startup without a scene; Core runs `houdinicore.py` instead.
  - `456.py` runs on every scene load.
- **Gotcha [verified].** hython puts the current directory (`$HIP`) first on `HOUDINI_PATH`,
  so a `scripts/python/pythonrc.py` in the cwd runs automatically. Running hython from the
  repo root executes the repo's own `pythonrc.py`; it printed `HOCUS998 ... invalid_install_root`.
  Test harnesses should launch hython from a neutral cwd.
- **Discovery.** HOM has no global "list running sessions" API. `hou.nodeBySessionId` and
  related functions are per-process node IDs, not process IDs. Use one of these:
  - a per-process registry file (pid, port, token, `hou.hipFile.path()`, start time) written
    at startup and removed at exit;
  - process enumeration of `houdini*.exe` / `hython*.exe` / `hbatch.exe`.

  HocusPocus's `hostInstanceId`/`hostGeneration` already follows the registry approach.

### A3. Hip-file lifecycle ([hou.hipFile](https://www.sidefx.com/docs/houdini/hom/hou/hipFile.html))

- **Members [verified]:** `load`, `save`, `saveAndIncrementFileName`, `saveAsBackup`,
  `saveAndBackup`, `clear`, `merge`, `collisionNodesIfMerged`, `hasUnsavedChanges`, `isNewFile`,
  `isLoadingHipFile`, `isShuttingDown`, `name`, `path`, `basename`, `setName`, `saveMode`,
  `setSaveMode`, `importFBX`, `addEventCallback`, `removeEventCallback`, `eventCallbacks`.
- **There is no `saveAs` and no `recentFiles`.** Save-as is `save(file_name=...)`. Its
  signature is `save(file_name=None, save_to_recent_files=True)`, and it creates intermediate
  directories [doc].
- **`load` and `clear`:** `load(file_name, suppress_save_prompt=False,
  ignore_load_warnings=False)` raises `OperationFailed` on load warnings unless they are
  ignored. Agents should pass `ignore_load_warnings=True` and report the warnings.
  `clear(suppress_save_prompt=True)` returns a bool [verified].
- **`merge`:** `merge(file_name, node_pattern="*", overwrite_on_conflict=False, ...)`. Preview
  conflicts first with `collisionNodesIfMerged` [doc].
- **Events [verified]:** `hou.hipFileEventType` has `BeforeClear/AfterClear`,
  `BeforeLoad/AfterLoad`, `BeforeMerge/AfterMerge`, `BeforeSave/AfterSave` and `BeforeQuit`
  (new in 22). Use these to bump a "scene generation" counter that invalidates agent-held
  handles.
- **Observed [verified]:**
  - `hasUnsavedChanges()` returned True immediately after `save()` in a hython session where
    nodes had been modified. Don't treat it as authoritative right after programmatic edits;
    re-check after `AfterSave`.
  - `saveAndIncrementFileName()` turned `probe.hip` into `probe1.hip`.
  - `hou.hipFile.name()` for a new session is `untitled.hip`, with `path()` in the cwd.
- **Time and variables [verified]:**
  - `hou.text.expandString("$HIP|$JOB|$F")` works. `hou.hscript("echo $HIP")` returns
    `(stdout, stderr)`.
  - `hou.playbar.frameRange()` works even in hython (`[1, 240]`), as do `hou.fps()`,
    `hou.setFrame()`, `hou.frame()`.
  - Some hscript commands return empty output in hython, for example `opinfo`.

### A4. Node and parm essentials and gotchas (all [verified] unless noted)

- **Creating nodes**
  - `createNode(type, name, run_init_scripts=True, load_contents=True, exact_type_name=False)`.
  - Type names resolve through `namespaceOrder()`. `copytopoints` resolves to
    `copytopoints::2.0` first.
  - `hou.nodeType(cat, name)`. Categories in 22: `Chop, ChopNet, Cop, Cop2, CopNet, Data,
    Director, Dop, Driver, Lop, Manager, Object, Shop, Sop, Top, TopNet, Vop, VopNet`. There
    are 1275 SOP types.
  - `NodeType.hidden()` and `deprecated()` exist; there is no `isHidden()`.
  - `embeddedHelp()` is empty for built-ins (help lives in `$HFS/houdini/help/*.zip`). Use
    `helpUrl()`/`defaultHelpUrl()`, e.g. `operator:Sop/box`.
- **Wiring**
  - `setInput(idx, node, output_idx=0)` raises `InvalidInput` for an out-of-range index.
  - `inputNames()` returns `('input1',)` and `inputLabels()` returns
    `('Transform geometry',)`. Use labels in descriptions and names or indices in calls.
  - `setNamedInput` exists. Use `setNextInput` for merge-like nodes.
- **Parm vs parmTuple**
  - `node.parm("t")` is `None`; use `parmTuple("t")` or `parm("tx")`. Agents hit this
    constantly, so a tool should accept either a tuple name or a component name.
- **Values, expressions, keys**
  - `setExpression("$F*0.1")`: `eval()` returns 1.0 at frame 10, and `rawValue()` and
    `expression()` both return `'$F*0.1'` (Hscript language).
  - **`set()` on an animated or expression parm does not remove the animation.**
    `set(3)` on an expression parm left `eval()==1.0` and added a key. On a keyed parm,
    `set(9)` at frame 10 inserted a third keyframe.
  - A "set value" tool must decide explicitly between `deleteAllKeyframes()` followed by
    `set()`, or setting a key, and report which it did.
  - `parm.set(other_parm)` creates a channel reference: `ch("../box1/sizex")`.
- **Menus**
  - `eval()` returns the index (0). `evalAsString()` returns the token ('srt').
  - `menuItems()` and `menuLabels()` give tokens and labels.
  - `set("trs")` by token works.
- **Strings**
  - `unexpandedString()` vs `evalAsString()`. Always return both for path-like parms.
- **Multiparms**
  - `parm("points").set(3)` gives 15 instance parms (`usept0, pt0x, ...`).
  - `isMultiParmParent()` exists. H22 adds `ParmTuple.insertMultiParmInstance/remove.../move...`.
- **Ramps**
  - Ramp parms are found via `parmTemplate().type() == hou.parmTemplateType.Ramp`.
  - `set(hou.Ramp(bases, keys, values))` then `eval().lookup(0.5)` returns 0.5.
- **Defaults and spare parms**
  - `parm.isAtDefault()` gives the non-default diff cheaply. On `transform1` only `tx` was
    non-default; this is ideal for compact node summaries.
  - `addSpareParmTuple(hou.FloatParmTemplate(...))` works.
  - H22 adds `Parm.rangeMin/rangeMax/setRange`.
- **Errors**
  - `cook(force=True)` on a broken wrangle **raises** `hou.OperationFailed` ("Error while
    cooking."). The useful text is only in `node.errors()` afterwards, e.g. "Syntax error,
    unexpected identifier, expecting ';' (1,9". Always catch, then collect `errors()`,
    `warnings()` and `messages()`.
  - Uncooked nodes return `()` for errors, so cook before checking.
- **Geometry**
  - `len(points())`, `len(prims())`, `intrinsicValue("pointcount")`, `boundingBox()`,
    `pointAttribs()`, `primAttribs()`, `globalAttribs()`, `pointFloatAttribValues("P")` (flat),
    `prims()[0].intrinsicNames()`.
  - Prefer intrinsics and bulk accessors to Python loops for size and performance.
  - H22 adds `primByName()` and `point/prim/vertex*ListAttribValues()`
    ([22 HOM changes](https://www.sidefx.com/docs/houdini/news/22/vex.html)).
- **Layout and flags**
  - `layoutChildren()` and `moveToGoodPosition()` both work headless.
  - `setDisplayFlag`, `setRenderFlag`, `isDisplayFlagSet`.
- **Undo**
  - `hou.undos.areEnabled()` is True even in hython.
  - `with hou.undos.group("label"):` produces one undo entry. `performUndo()` reverted a node
    creation. `undoLabels()` lists history.
  - Wrapping every mutating tool call in a named undo group gives agents and users a real
    "undo last agent action".
- **Serialization**
  - `asCode(brief=True)` returns about 5 KB of Python for one xform, which is too verbose for
    agent context.
  - `saveItemsToFile(items, path)` writes `.cpio` (a copy/paste clip).
  - **Native JSON (H20.5+; extended in 22):**
    `node.asData(children, inputs, position, flags, parms, default_parmvalues,
    evaluate_parmvalues, parmtemplates="spare_only", ...)` returns compact dicts, e.g.
    `{"type":"xform","parms":{"t":[2.0,0.0,0.0]}}` with non-default parms only.
  - `childrenAsData(inputs=True, flags=True, position=True)` →
    `setChildrenFromData(d)` round-tripped box→xform wiring, a `$F` expression and the
    display flag.
  - Related: `hou.data.itemsAsData/createItemsFromData`, `setParmsFromData`,
    `setInputsFromData`, `editablesAsData` (LOP).
  - These are strong candidates to replace or underpin a custom graph DSL.
- **Identity and metadata**
  - `node.sessionId()` / `hou.nodeBySessionId()` are stable while the process lives and
    survive renames. Paths do not survive renames.
  - `setUserData("hp:id", ...)` persists in the hip. `setCachedUserData` does not persist.
  - Combine them: a persistent agent ID in userData plus `sessionId` for fast lookup.
- **Events**
  - `node.addEventCallback` with `hou.nodeEventType.*` (ChildCreated, ParmTupleChanged,
    FlagChanged, InputRewired, NameChanged, BeingDeleted, ...) supports change journals.
- **HDAs**
  - `hou.hda.installFile/installFiles/uninstallFile/reloadFile/definitionsInFile/
    loadedFiles/reloadHDAModule/safeguardHDAs`.
  - `node.createDigitalAsset(...)` and `NodeType.hdaModule()` are [doc].
- **Removed in 22 [doc]:**
  - `hou.Node.copyNetworkBox`, `copyStickyNote`, `editableInputString(s)` and
    `setEditableInputString` were removed from `hou.Node`/`ApexNode` (they remain on
    `LopNode` [verified]).
  - `hou.ChannelEditorPane` was replaced by `hou.ChannelEditor`.

### A5. Visual feedback

- **OpenGL ROP**
  - Works headless [verified]: `/out` `opengl` node with `camera`, `trange=0` and
    `picture=.../gl.$F4.png`, then `render()`. It wrote a 24 KB PNG in 6.9 s on the first
    call (shader/GL init); later frames are faster.
  - Requires a GPU/GL context. It worked on this Windows desktop from a non-GUI process.
    Headless Linux servers may need a virtual display.
  - **This is the best "screenshot" primitive for an agent.** It is deterministic, controlled
    by camera and resolution, and works in both GUI and hython.
- **Flipbook (GUI only)**
  - `hou.ui.paneTabOfType(hou.paneTabType.SceneViewer)` → `sv.flipbook(viewport=None,
    settings=None, open_dialog=False)`.
  - `settings = sv.flipbookSettings().stash()` with `output("x$F4.png")`,
    `frameRange((f,f))`, `resolution((w,h))`, `useResolution(True)`, `outputToMPlay(False)`
    ([SceneViewer](https://www.sidefx.com/docs/houdini/hom/hou/SceneViewer.html),
    [FlipbookSettings](https://www.sidefx.com/docs/houdini/hom/hou/FlipbookSettings.html)).
  - This captures what the user sees, including handles and guides.
  - There is no public `saveViewportImage`. `GeometryViewport` has only a private
    `_captureFramebuffer` [verified dir()], plus `frameAll/homeAll/frameSelected/saveViewToCamera`.
- **Karma**
  - The `karma` ROP exists in `/out` [verified]. For quick renders, use low samples and
    resolution, with XPU/CPU selected by parm. It is too slow for routine feedback, so
    reserve it for explicit "render preview".
- **Copernicus (COP)**
  - `CopNode.layer()` returns `hou.ImageLayer` (1024x1024 noise cooked in 2.33 s headless)
    [verified]. This allows image previews without a viewport.
- **Return format**
  - Return MCP `image` content (PNG/JPEG base64) downscaled to about 768-1024 px. Claude Code
    counts image bytes toward `MAX_MCP_OUTPUT_TOKENS` (25k default) and saves originals to
    disk ([Claude Code MCP](https://code.claude.com/docs/en/mcp)).

### A6. Other contexts (all [verified] unless noted)

- **LOPs**
  - `lop.stage()` returns a `pxr.Usd.Stage`; traversal gives `['/HoudiniLayerInfo', '/cube1']`.
  - `editableStage()` returns `None` outside a Python LOP cook.
  - `activeLayer`, `editableLayer`, `sourceLayer`, `layersAboveLayerBreak`, `selectedItems`
    are available. H22 adds `LopNetwork.selectionPaths()` and `LopNode.inEditLayerBlock()`.
- **TOPs/PDG**
  - Methods: `cookWorkItems(block=True)`, `cookOutputWorkItems`, `cookAllOutputWorkItems`,
    `executeGraph`, `generateStaticWorkItems`, `dirtyAllWorkItems`, `getPDGNode()`,
    `workItemStates`.
  - A `genericgenerator` with 3 items cooked synchronously and `getPDGNode().workItems` had
    length 3.
  - Long PDG cooks are the archetypal "task" operation: use `block=False` plus
    `pdg.EventHandler` ([TOP events](https://www.sidefx.com/docs/houdini/tops/events.html)).
- **COPs**
  - `Cop` is Copernicus (383 node types) and `Cop2` is legacy. `copnet` children have the
    `Cop` category.
  - The type name `noise` does not exist; use `fractalnoise`, `cellularnoise`, etc.
  - Cooking `fractalnoise` printed `Warning: error binding handle sidefx_transform2d` to
    stdout headless. Treat stdout noise as non-fatal.
  - H22 adds `CopNode.cable()/attrib()/pairedNode()` and `hou.CopCable`.
- **Materials**
  - `/mat` is a `Vop` network. 239 `mtlx*` VOP types are present, and the
    `materiallibrary` LOP exists.
  - MaterialX is the H22 default authoring path for Karma [doc,
    [22 Karma](https://www.sidefx.com/docs/houdini/news/22/karma.html)].
- **APEX**
  - `hou.ApexNode` and the new `hou.UniNode*` classes (H22) [doc] are a separate graph
    family. Treat them as out of scope for v1.

### A7. Houdini 22 vs 21 for this project

- **Python.** H22 ships **Python 3.13.10** as the default build (VFX Reference Platform
  CY2026). Python 3.11 builds remain available
  ([Thinkbox forum](https://forums.thinkboxsoftware.com/t/houdini-22-0-python-3-13/34036),
  [CG Channel](https://www.cgchannel.com/2026/07/sidefx-just-released-houdini-22/)).
- **Library directories [verified].** This install has only `houdini/python3.13libs`. Houdini
  auto-adds `$HOUDINI_PATH/pythonX.Ylibs` for the **running** version, so it scans
  `python3.13libs`. `$HFS/python311/` and `python310/` contain only `dlls/`.
- **HocusPocus impact.** The repo ships its code in `python3.11libs/` and reaches `sys.path`
  only through the package's explicit `PYTHONPATH` prepend in `package/hocuspocus.json`. It
  works, but the directory name is misleading. The default H22 build will never auto-scan
  it, and a 3.11 build would load it a second time. Rename to `python3.13libs` (or a
  version-neutral `python/` with explicit PYTHONPATH) in the redesign.
- **Bundled packages [verified].** numpy 2.3.2, PySide6 6.8.3 (no PySide2), aiohttp 3.13,
  `pxr`, `pdg`, rpyc. pydantic, anyio, httpx, starlette, uvicorn and mcp are **not**
  bundled.
- **HOM additions and removals.** Listed in A4 and A6; see
  [22 HOM changes](https://www.sidefx.com/docs/houdini/news/22/vex.html). Also new: the
  `hou.data` `parmfilter` key, `hou.OpenCLDevice`, and `hou.Camera/CameraPrim`.

---

## Part B - Prior art

There is no official SideFX general-purpose Houdini MCP server. The only SideFX MCP work is an
APEX-script documentation and validator MCP shown with H22
([JPR](https://www.jonpeddie.com/news/sidefx-and-nvidia-bring-mcp-powered-ai-agents-to-houdini-22s-rigging-workflow-at-siggraph-2026/)).
`ryanlamb/houdini-mcp` does not exist (404), and there is no `houdini-mcp` PyPI package; the
only Houdini package on PyPI is `fxhoudinimcp`. Star counts are approximate as of October 2026.
Details come from READMEs, server source and issue trackers.

### B1. Houdini servers

| Project | Transport | Main-thread marshaling | Tools | Generic exec | Screenshots / hip | Notable issues |
|---|---|---|---|---|---|---|
| [capoomgit/houdini-mcp](https://github.com/capoomgit/houdini-mcp) (~305★, the original) | stdio bridge (uv) → TCP :9876, 4-byte length-prefixed JSON. Timeouts 15 s, or 300 s for renders. | `QTimer` polls a non-blocking socket every 100 ms on the UI thread. Single client. | 25 (`get_scene_info, create_node, connect_nodes, set_parameters, get_parameter_schema, find_error_nodes, cook_node, create_wrangle, get_geometry_info, render_single_view/quad_views/specific_camera`, plus 6 paid-API `opus_*` tools) | `execute_houdini_code` (`exec` with stdout capture) | OpenGL/Karma from a temporary camera; returns a file path. No hip tools. Every mutation is wrapped in `hou.undos.group("MCP: ...")`. | #14 multiple clients starve; #13 package/`HOUDINI_PATH` separator; #4 `pydantic_core` import on Windows; Mac unsupported. |
| [healkeiser/fxhoudinimcp](https://github.com/healkeiser/fxhoudinimcp) (~329★, PyPI 2.25, most mature) | stdio MCP → HTTP/JSON to **`hwebserver`** :8100+ (one port per instance). Loopback; rejects Origin/DNS rebinding. | `hdefereval.executeInMainThreadWithResult` for every `hou` call. | **215** tools, 8 resources, 9 prompts. Has `open_hip/save_hip`, `viewport_capture`, `build_network` (batch), PDG, LOP, HDA and session (headless or GUI launch). | `execute_python`, `execute_hscript`. README: a connection is a shell; no auth. | `viewport_capture`, contact sheets. Path-only image results (#38). One undo step per call. `PROJECT_ROOT` confines file operations. | [#9/#10](https://github.com/healkeiser/fxhoudinimcp/issues/9) health check deadlocked against a busy main thread. [#12](https://github.com/healkeiser/fxhoudinimcp/issues/12) on **H22.0.368**: no `python3.13libs/uiready.py`, so no autostart; hwebserver state is `threading.local` (register and run on the same thread); `setSettingsForPort` args reversed. [#40](https://github.com/healkeiser/fxhoudinimcp/issues/40) a 10-min Karma render blew the 60 s HTTP timeout; fixed with a detached hython plus PID polling. [#129](https://github.com/healkeiser/fxhoudinimcp/issues/129) port scan before `initialize` exceeded Cline's 3 s limit. |
| [kleer001/houdini-mcp](https://github.com/kleer001/houdini-mcp) (~25★) | TCP :9876, raw JSON (retries `json.loads`). Auto-launches headless hython if nothing is listening. | `QTimer` 100 ms. | **166** in 23 categories (`save_scene/load_scene`, `render_flipbook`, `capture_screenshot`, `lop_stage_info`, `validate_vex`, ...). | `execute_houdini_code` with a substring blocklist (`subprocess`, `os.remove`, `__import__`...). The blocklist is trivially bypassed. | One-frame `viewer.flipbook()` (code notes `GeometryViewport.saveAsImage` was removed in H21). Offline BM25 search over 30k docs. | none filed |
| [oculairmedia/houdini-mcp](https://github.com/oculairmedia/houdini-mcp) (~78★) | FastMCP gateway → **hrpyc/RPyC :18811**. Loopback unless a trusted-network flag or shared secret is set. Backoff reconnect. | Not documented (RPyC thread). | 43, including `serialize_scene`, `capture_pane_screenshot`, `render_node_network`, `summarize_response`, `estimate_tokens`. | `execute_code`, `execute_hscript`. | Pane screenshots; `save_scene/load_scene/new_scene`. | 26 closed issues on performance and recovery. |
| [JTCHE/houdini-mcp](https://github.com/JTCHE/houdini-mcp) (~8★, active) | TCP :9877, length-prefixed. | n/v | **16 broad tools that take a mode argument** (`scene_overview, node_inspect, geometry_inspect, stage_inspect, node_edit, parm_set, connect, batch, cook, render, pdg, playbar, scene_file, execute, capture, docs, session`). | `execute` runs Python, HScript, expressions or VEX. | `capture` (view, camera, quad, ffmpeg flipbook). | - |
| [tmdag/houdini-mcp](https://github.com/tmdag/houdini-mcp) | Versioned "HMC1" frames over TCP; QTimer. Warns other clients instead of letting them take over. | QTimer. | ~191, exposed through **profiles** (`stage` default 82, `sop`, `all`). | yes | Screenshots taken from outside the process with OS tools. H22 notes: start from `uiready.py`, avoid desktop/viewport UI calls. | - |
| [dcc-mcp/dcc-mcp-houdini](https://github.com/dcc-mcp/dcc-mcp-houdini) | Streamable HTTP embedded in Houdini; OS-assigned ports plus a gateway on :9765. | n/v | 296 tools in 43 **skills loaded progressively** (discover, load, unload). Only scripting and scene load by default. | yes | Supports hython. | - |
| Others | [bharathadolf](https://github.com/bharathadolf/houdini-mcp) (TCP, `hdefereval`, 30+ tools); [eliiik](https://github.com/eliiik/houdini-mcp) (RPyC, 35 tools); [easyhoudini_mcp](https://github.com/rozhabrev/easyhoudini_mcp) (few tools with modes, enforced naming like `OUT_` nulls, **autosave before heavy operations**, timelapse journal) | | | | | |

### B2. Comparables

- **[ahujasid/blender-mcp](https://github.com/ahujasid/blender-mcp)** (~30.5k★)
  - Socket thread → `queue`, drained on the main thread by `bpy.app.timers` about every 50 ms.
  - About 14-17 tools: `get_scene_info`, **`execute_blender_code`**, consolidated
    `search_assets`/`import_asset` across providers, and `viewport_capture` returning base64
    `ImageContent` via `GPUOffScreen`.
  - Issues are dominated by **timeouts** (#50 "-32001 Request timed out", #219 incomplete
    JSON, #279 ~5-min stall per call), framing/version mismatch (#311), tool-schema bloat
    (#347: 5,462 → 6,928 tokens), telemetry concerns (#360) and an arbitrary file write
    (#257).
- **Epic's official Unreal MCP (UE 5.8, experimental)**
  ([docs](https://dev.epicgames.com/documentation/unreal-engine/unreal-mcp-in-unreal-editor?lang=en-US))
  - In-editor Streamable HTTP/SSE on `127.0.0.1:8000/mcp`, no auth.
  - **Three meta-tools: `list_toolsets`, `describe_toolset`, `call_tool`.** These keep
    `tools/list` tiny.
  - Calls execute **serially on the game thread**.
- **[chongdashu/unreal-mcp](https://github.com/chongdashu/unreal-mcp)** (~2.1k★)
  - C++ TCP plugin with `AsyncTask` to the game thread. Typed actor and Blueprint tools.
    **No exec tool.** Issues are mostly engine-version build breaks.
- **Maya**
  - [PatrickPalmer/MayaMCP](https://github.com/PatrickPalmer/MayaMCP) uses `commandPort`.
    Users asked for execute_python/MEL (#10).
  - [dcc-mcp-maya](https://github.com/dcc-mcp/dcc-mcp-maya) uses a Rust sidecar,
    `executeDeferred`, a readiness probe `/v1/readyz`, auto-dismissed modal dialogs, SQLite
    job persistence and `DISABLE_EXECUTE_PYTHON`.
- **[kleer001/nuke-mcp](https://github.com/kleer001/nuke-mcp)**
  - `nuke.executeInMainThreadWithResult`. **Delete, load-script and execute-python require
    confirmation enforced in code.**

### B3. Patterns that work (and failure modes to design out)

1. **Keep network I/O off the UI thread and run every `hou` call serially on the main
   thread**, with bounded timeouts. Failure modes:
   - a worker calling `hou` while the main thread waits on it deadlocks (fxhoudinimcp #9/#10);
   - QTimer polling adds latency and freezes behind modal dialogs.
2. **Answer MCP `initialize` immediately; find and connect to Houdini lazily**
   (fxhoudinimcp #129). Supporting practices:
   - a stdio broker outside Houdini survives restarts;
   - version the wire framing (HMC1, length prefix) and do a handshake (Blender #311 shows
     the failure).
3. **Long operations become detached jobs** (PID or job ID, then poll). Never block a request
   on a render or sim (fxhoudinimcp #40; the Blender timeout family).
4. **Batching beats chattiness.** fxhoudinimcp measured about 50 ms per call, so 10
   creations took about 800 ms, while one `build_network` took about 66 ms. A declarative
   graph-apply tool (e.g. on top of `setChildrenFromData`) is the biggest ergonomic and
   performance win.
5. **Control tool count** with profiles, progressive skills, meta-tools or mode-parameter
   tools. Servers with 166-296 tools all had to add one of these. Blender consolidated
   per-provider tools.
6. **Everyone ships a generic exec tool, and it is a shell.** What works:
   - loopback binding with Origin and rebinding checks plus a token;
   - an off switch;
   - confirmation enforced in code for destructive operations;
   - a `PROJECT_ROOT` sandbox for file paths;
   - one undo group per call.

   Substring blocklists are security theatre.
7. **One undo group per tool call** is universal and valued. Add autosave or backup before
   destructive or heavy operations, and auto-dismiss or detect modal dialogs.
8. **Visual feedback:**
   - Prefer ROP or flipbook capture from an explicit camera over raw viewport grabs, which are
     unstable on H21/H22.
   - Return a **file path or resource_link by default**, with optional inline downscaled
     base64 for clients without file access.
9. **H22 startup gotchas** (independently reported):
   - autostart from `uiready.py` in `python3.13libs`;
   - hwebserver per-thread state;
   - reversed `setSettingsForPort` args;
   - LOP nodes lack `setRenderFlag`.

---

## Part C - MCP design practice for agent ergonomics

### C1. Spec landscape (what to target)

- **2025-06-18**
  ([spec](https://modelcontextprotocol.io/specification/2025-06-18)): structured tool output
  (`outputSchema` + `structuredContent`), elicitation (form) and `resource_link` content.
- **2025-11-25**
  ([changelog](https://modelcontextprotocol.io/specification/2025-11-25/changelog)):
  - tool-name guidance: 1-128 chars, `[A-Za-z0-9_.-]`, case-sensitive;
  - JSON Schema 2020-12 as the default dialect;
  - icons, URL-mode elicitation and experimental **tasks**;
  - "input validation errors should be returned as Tool Execution Errors" (`isError: true`)
    so the model can self-correct (SEP-1303).
- **2026-07-28**
  ([changelog](https://modelcontextprotocol.io/specification/2026-07-28/changelog)):
  - **Stateless.** No `initialize`; per-request `_meta` carries version and capabilities;
    `server/discover` is added. Protocol sessions and `Mcp-Session-Id` are removed, and
    servers needing cross-call state "use explicit, server-minted handles passed as ordinary
    tool arguments".
  - `subscriptions/listen` replaces the GET stream and `resources/subscribe`.
  - Tasks moved to the `io.modelcontextprotocol/tasks` extension (no `tasks/result`, no
    `tasks/list`; poll `tasks/get`).
  - Multi-round-trip requests (`resultType: "input_required"`) replace server-initiated
    elicitation and sampling.
  - Logging, Sampling and Roots are **deprecated**: log to stderr or OpenTelemetry instead.
  - `tools/list` SHOULD be deterministic in order (prompt-cache hits), and list results
    carry `ttlMs`.
- **Implication.** Expose session-like state (scene generation, transaction IDs, job IDs) as
  **tool arguments and results**, never as transport state. This also helps the existing
  durable stdio broker design: Houdini restarts become a visible `scene_generation` change
  rather than a broken session.

### C2. Tools: count, naming, schemas, outputs

- **Count and consolidation.** Anthropic's guidance
  ([Writing tools for agents](https://www.anthropic.com/engineering/writing-tools-for-agents)):
  - don't wrap every API; consolidate into workflow-level tools;
  - namespace by service and resource;
  - return semantic identifiers (node paths, names), not opaque IDs;
  - offer a `response_format` (`concise`/`detailed`) enum;
  - paginate and truncate with sensible defaults;
  - make error messages instructive.

  Claude Code now uses **tool search** by default on Claude 4.5+ models, so large tool lists
  cost less up front, but a smaller, sharper surface still improves selection.
- **Code-execution trade-off.**
  [Code execution with MCP](https://www.anthropic.com/engineering/code-execution-with-mcp)
  reports up to 98.7% token savings by letting agents run code against an API instead of
  round-tripping intermediates. It also warns that this "requires a secure execution
  environment". For Houdini, an `execute_python` tool is the equivalent, and in prior art it
  is the most-used and the riskiest tool (Part B). Recommendation:
  - keep it, but make it opt-in or gated;
  - wrap it in an undo group, timeout and output cap;
  - return structured stdout, result and errors;
  - add read-only "describe/query" tools that let agents filter in Houdini rather than
    paging raw data.
- **Naming.** Use the `houdini.node.create` or `node_create` style (dots allowed per the
  2025-11-25 guidance). Keep verbs consistent: `get/list/find/create/set/delete/cook/render`.
- **Input schemas.**
  - Use flat, typed parameters with enums for closed sets (context categories, parm-set
    modes), defaults stated in descriptions, and `additionalProperties: false`.
  - Accept tolerant identifiers: a path, or a userData ID. Resolve `t` vs `tx` server-side
    rather than failing.
  - Note: **MCP SDK v2 no longer validates arguments against `input_schema` before calling
    the handler** ([what's new](https://py.sdk.modelcontextprotocol.io/whats-new/)), so the
    server must validate and return `isError` tool results.
- **Structured output.**
  - Declare `outputSchema` and return `structuredContent` plus a serialized TextContent for
    backward compatibility ([tools spec](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)).
  - Verified in SDK v2.3: a pydantic `BaseModel` or `TypedDict` return annotation produces an
    `outputSchema` and `structured_content`. **A bare `-> dict` produces neither**; it yields
    text only.
- **Errors.** Use `isError: true` with actionable text (which node, which parm, valid menu
  tokens, nearest type names). Reserve protocol errors for unknown tools and malformed
  requests.
- **Annotations.**
  - `readOnlyHint` (default false), `destructiveHint` (default true, meaningful only when not
    read-only), `idempotentHint` (default false) and `openWorldHint` (default true; set false
    for a local DCC).
  - Clients "MUST consider tool annotations to be untrusted unless they come from trusted
    servers", and use them for permission UX.
  - Mark query tools read-only, `node_delete`/`hip_clear`/`execute_python` destructive, and
    `parm_set` idempotent.
- **Output size.**
  - Claude Code limits: `MAX_MCP_OUTPUT_TOKENS` defaults to 25,000 (warning at 10,000).
    Text results over 50,000 characters are spilled to a file unless the tool declares
    `_meta["anthropic/maxResultSizeChars"]` (max 500,000)
    ([Claude Code MCP docs](https://code.claude.com/docs/en/mcp)).
  - Design every list or describe tool with `limit`/`cursor` and a summary-first default.

### C3. Resources, templates, prompts

- **Resources** are "application-driven" (the host decides inclusion); tools are
  model-controlled ([resources spec](https://modelcontextprotocol.io/specification/2025-11-25/server/resources)).
- **Good fits:**
  - `houdini://scene/summary`;
  - templates (RFC 6570) such as `houdini://node/{path}`,
    `houdini://nodetype/{category}/{name}` (parm templates and help URL) and
    `houdini://geometry/{path}{?attribs,limit}`;
  - render outputs referenced via `resource_link` from a render tool.
- **Client support.** Claude Code exposes resources via `@` mentions and prompts as slash
  commands. Many agents never read resources on their own, so **duplicate critical reads as
  tools** and use resources for user-attachable context.
- **Prompts** suit canned workflows such as "build a procedural asset" or "debug this
  node's errors".

### C4. Long-running operations, progress, cancellation

- **Progress.** `notifications/progress` with `progressToken` (from request `_meta`),
  monotonically increasing `progress`, optional `total` and `message`. Clients MAY reset
  timeouts on progress but SHOULD enforce a maximum
  ([lifecycle](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle)).
- **Tasks (2025-11-25, experimental).** `execution.taskSupport` per tool; `tasks/get`,
  `tasks/result`, `tasks/cancel`; statuses `working / input_required / completed / failed /
  cancelled`; `ttl` and `pollInterval`
  ([tasks](https://modelcontextprotocol.io/specification/2025-11-25/basic/utilities/tasks)).
  In 2026-07-28 this moved to an extension, and SDK v2 removed its experimental tasks API.
- **Recommendation.** Implement long jobs (renders, PDG cooks, sims, big cooks) as
  **application-level job tools** (`job_start` → `{job_id}`, `job_status`, `job_result`,
  `job_cancel`). These are portable across spec versions and clients, and mirror the task
  semantics. Emit progress notifications when a token is supplied.
- **Timeouts.** Claude Code: `MCP_TOOL_TIMEOUT`; idle timeout defaults to 5 min for HTTP and
  30 min for stdio (`CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT`) [Claude Code docs]. Main-thread work
  inside a tool must stay well below these, or become a job.

### C5. Elicitation, logging, instructions

- **Elicitation.**
  - Form mode is limited to flat primitive and enum schemas and MUST NOT request secrets.
    Actions are accept, decline and cancel
    ([elicitation](https://modelcontextprotocol.io/specification/2025-11-25/client/elicitation)).
  - Useful for "the scene has unsaved changes - save, discard, or cancel?" before
    `hip_load` or `hip_clear`.
  - In 2026-07-28 it becomes an `input_required` result. Don't make correctness depend on it;
    provide an explicit `on_unsaved: "fail"|"save"|"discard"` argument as well.
- **Logging.** Use stderr (stdio) or OpenTelemetry; MCP logging is deprecated in 2026-07-28.
  SDK v2 includes OpenTelemetry spans.
- **Server instructions.** `InitializeResult.instructions` (and `server/discover` in 2026)
  is where to put the operating manual. It should cover:
  - the main-thread and undo model;
  - the identifier conventions;
  - "cook then read errors";
  - the job pattern;
  - when to use `execute_python`.

  Verified: SDK v2 `MCPServer("x", instructions=...)` surfaces them in `initialize`.

### C6. Python MCP SDK inside Houdini, and stdio↔HTTP proxying

- **Package.** `mcp` 2.3.0 (2026-10-02), `requires_python >=3.10`
  ([PyPI](https://pypi.org/project/mcp/), [docs](https://py.sdk.modelcontextprotocol.io/)).
  - v2 renamed `FastMCP` to **`MCPServer`** (`from mcp.server import MCPServer`).
  - Host and port moved to `run()`. `streamable_http_app(stateless_http=..., json_response=...)`
    returns a Starlette app.
  - Sync handlers run on worker threads.
  - WebSocket transport was removed; httpx was replaced by httpx2.
  - Serves 2025-11-25 and 2026-07-28 together.
  - The standalone **FastMCP** project is at 4.1.0.
- **Inside hython [verified].**
  - Command: `hython -m pip install --target <scratch>/vendor mcp==2.3.0`.
  - Installed: anyio 4.15, pydantic 2.14/pydantic-core 2.50 (cp313 wheels), starlette 1.7,
    uvicorn 0.54, sse-starlette 3.5, httpx2, cryptography 50, pywin32 312, jsonschema,
    opentelemetry-api.
  - Loading needed `sys.path.insert(0, vendor); site.addsitedir(vendor);
    os.add_dll_directory(vendor/pywin32_system32)`, because `mcp.os.win32` imports
    `pywintypes`.
  - The probe ran uvicorn on a daemon thread at 127.0.0.1:37906 and pumped a job queue on
    the main thread. `initialize` returned protocol `2025-11-25` with instructions;
    `tools/list` showed `readOnlyHint`; both an `async` handler (awaiting a
    `concurrent.futures.Future` via `asyncio.wrap_future`) and a sync handler (`.result(10)`)
    executed `hou` on the main thread.
  - **Risk.** Vendored deps can shadow Houdini's own site-packages (attrs 22.2, cryptography
    45, click 8.1.6, typing_extensions), which may break SideFX tools that import them.
    Mitigations: run the MCP SDK **out of process** (stdio broker under a standalone Python),
    or load the vendor dir only inside a dedicated server thread with an isolated `sys.path`
    (fragile). The out-of-process option is preferred.
- **Recommended topology** (it matches HocusPocus's current durable design):

  ```
  Agent ──stdio MCP──► broker (standalone CPython + mcp SDK; owns MCP protocol, schemas,
                                   validation, jobs, reconnection)
                         │  authenticated localhost HTTP/JSON (small, versioned RPC)
                         ▼
                Houdini host (stdlib http.server thread → MainThreadExecutor → hou)
  ```

  - The in-Houdini side stays dependency-free (stdlib only), which removes the shadowing
    risk.
  - The broker can use the latest SDK and spec without touching Houdini.
  - A Houdini restart is a host-generation change.
- **Proxying stdio to HTTP.**
  - One option is a thin forwarder that relays JSON-RPC lines from stdin to the host's
    Streamable HTTP endpoint (SDK `Client`/`streamable_http_client` on one side, a stdio
    server on the other; FastMCP offers `FastMCP.as_proxy()`).
  - The broker approach above is richer: it terminates MCP itself and calls a private RPC.
    That is what makes reconnect, offline errors and spec upgrades tractable.
- **Security** ([2025-11-25 transports](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)):
  bind to 127.0.0.1, validate `Origin` (respond 403 on invalid), and require a bearer token
  for the private host channel. Never expose `hrpyc` or a bare exec socket.
