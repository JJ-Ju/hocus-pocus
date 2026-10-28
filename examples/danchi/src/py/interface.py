# interface.py — the Weathering tab of the danchi asset (1.1): preset, building history, site,
# then one folder per detail layer, each "auto from the macro controls" unless its Override is on.
# build.py uses weather_folder() for a from-scratch build; upgrade_definition() swaps the tab into
# an existing asset definition (how 1.0 became 1.1).
import hou

PRESETS = {"new": (0, 1.0), "well_kept": (15, 0.85), "typical": (35, 0.5), "neglected": (45, 0.12)}

# the asset's texture folder: tex/ beside the library file the definition was loaded from
TEXDIR_EXPR = '__import__("os").path.dirname(hou.pwd().type().definition().libraryFilePath()).replace(chr(92), "/") + "/tex"'

PRESET_CB = ("n = kwargs['node']; v = " + repr(PRESETS) + ".get(n.parm('w_preset').evalAsString()); "
             "v and [n.parm('w_age').set(v[0]), n.parm('w_upkeep').set(v[1]), n.parm('repaint_auto').set(1)]")


def _f(name, label, parms, collapsed=True):
    fo = hou.FolderParmTemplate(name, label, folder_type=hou.folderType.Collapsible)
    for p in parms:
        fo.addParmTemplate(p)
    if collapsed:
        fo.setTags({"group_default": "0"})
    return fo


def weather_folder():
    R = hou.FloatParmTemplate
    I = hou.IntParmTemplate
    T = hou.ToggleParmTemplate
    M = hou.MenuParmTemplate
    S = hou.StringParmTemplate
    nc = '{ w_preset != "custom" }'

    def ovr(tag, label, help_):
        return T(f"ov_{tag}", f"Override {label}", default_value=False,
                 help=f"Off: {help_} comes from the macro controls (README, 'auto' column). On: use the values below.")

    def dis(tag):
        return "{ ov_%s == 0 }" % tag

    fo = hou.FolderParmTemplate("f_weather", "Weathering", folder_type=hou.folderType.Tabs)
    pr = M("w_preset", "Preset", ("new", "well_kept", "typical", "neglected", "custom"),
           ("New (0 years)", "Well Kept (15 years, high upkeep)", "Typical (35 years)",
            "Neglected (45 years, low upkeep)", "Custom (use the sliders)"), default_value=2,
           script_callback=PRESET_CB, script_callback_language=hou.scriptLanguage.Python,
           help="Sets Age and Upkeep (and an automatic repaint cycle). Custom uses the sliders below. "
                "Grime, exposure, wind and seed belong to the site and are never changed by a preset.")
    fo.addParmTemplate(pr)
    fo.addParmTemplate(_f("f_hist", "Building History", [
        R("w_age", "Age (years)", 1, (35.0,), min=0, max=60, min_is_strict=True, max_is_strict=True,
          disable_when=nc, help="Years since construction. Drives concrete damage, edge wear, efflorescence, rust depth."),
        R("w_upkeep", "Upkeep", 1, (0.5,), min=0, max=1, min_is_strict=True, max_is_strict=True, disable_when=nc,
          help="0 = never maintained, 1 = repainted every ~7 years and repaired. Shortens the repaint cycle, "
               "cleans, repairs chips; more upkeep also means more visible repaint patches."),
        T("repaint_auto", "Repaint Cycle from Age and Upkeep", default_value=True, disable_when=nc,
          help="Years since repaint = min(age, lerp(24, 7, upkeep)): the block sits mid-cycle."),
        R("age", "Years Since Repaint", 1, (15.5,), min=0, max=60, min_is_strict=True, max_is_strict=True,
          disable_when='{ w_preset != "custom" } { repaint_auto == 1 }',
          help="Surface soiling (streaks, soot, stain fields, growth) restarts at each repaint; older stains "
               "ghost through at 22 %."),
    ], collapsed=False))
    fo.addParmTemplate(_f("f_site", "Site", [
        R("w_grime", "Urban Grime", 1, (0.5,), min=0, max=1, min_is_strict=True, max_is_strict=True,
          help="Air pollution: soot, tyre and brake dust. Darkens and greys every exposed surface; feeds the stain fields."),
        R("w_exposure", "Weather Exposure", 1, (0.6,), min=0, max=1, min_is_strict=True, max_is_strict=True,
          help="0 = sheltered between buildings, 1 = open or coastal. Scales driven rain on the windward faces "
               "(longer, stronger streaks, washed corners) and dirt crust on the lee faces."),
        R("w_wind", "Prevailing Wind and Rain From", 1, (200.0,), min=0, max=360, min_is_strict=True, max_is_strict=True,
          help="Compass bearing in degrees the driving rain comes from (0 N, 90 E, 180 S, 270 W). "
               "The balconies face south (+Z), the corridors north."),
        I("w_seed", "Weathering Seed", 1, (1,), min=0, max=999,
          help="Reseeds causes, streaks, stains and patches without changing the building."),
    ], collapsed=False))
    fo.addParmTemplate(R("weather", "Auto Intensity", 1, (1.0,), min=0, max=2,
                         help="Scales every auto (not overridden) detail value. 1 = calibrated."))
    fo.addParmTemplate(T("decals", "Decal Meshes", default_value=True,
                         help="Streaks, stain fields, corner grime, splash band, growth, efflorescence, rust and "
                              "worn-edge runs as alpha-mapped mesh decals (one atlas, one material)."))
    fo.addParmTemplate(S("tex_dir", "Texture Folder", 1, ("",),
                         default_expression=(TEXDIR_EXPR,),
                         default_expression_language=(hou.scriptLanguage.Python,),
                         string_type=hou.stringParmType.FileReference, file_type=hou.fileType.Directory,
                         help="Folder with the shared textures. Default: tex/ next to the asset library (danchi.hdalc)."))
    fo.addParmTemplate(_f("f_dmg", "Edge Damage", [
        ovr("dmg", "Edge Damage", "edge damage"),
        R("dmg_amt", "Amount", 1, (0.56,), min=0, max=1, disable_when=dis("dmg"),
          help="Share of balcony fronts that are damaged (up to 85 %) and the density of nicks around each hotspot."),
        R("dmg_size", "Largest Size (m)", 1, (0.16,), min=0.02, max=0.4, disable_when=dis("dmg"),
          help="Length along the edge of the biggest break (spall) at a hotspot; satellites, runs and bites scale with it."),
        I("dmg_hot", "Hotspots per Damaged Front", 1, (2,), min=0, max=4, disable_when=dis("dmg"),
          help="Damage centres per damaged balcony front; damage radiates out from each, smaller and sparser."),
    ]))
    fo.addParmTemplate(_f("f_wear", "Edge Wear", [
        ovr("wear", "Edge Wear", "edge wear"),
        R("wear_amt", "Amount", 1, (0.6,), min=0, max=1, disable_when=dis("wear"),
          help="Worn arrises showing the lighter substrate under the grime: runs along exposed edges, halos round chips."),
    ]))
    fo.addParmTemplate(_f("f_streak", "Streaks", [
        ovr("streak", "Streaks", "streaking"),
        R("streak_amt", "Amount", 1, (0.72,), min=0, max=1, disable_when=dis("streak"),
          help="Master: how many sources run and how dark."),
        R("streak_density", "Density", 1, (1.0,), min=0, max=2, disable_when=dis("streak"),
          help="Multiplies the share of sources (rail posts, joints, low points, sills) that shed a run."),
        R("streak_len", "Length", 1, (1.25,), min=0.2, max=3, disable_when=dis("streak"),
          help="Multiplies the power-law lengths (median ~0.4 m)."),
        R("streak_tail", "Long-Run Share", 1, (0.11,), min=0, max=0.5, disable_when=dis("streak"),
          help="Share of runs from the long tail (2-3 m, past the next ledge on the gables)."),
        R("streak_width", "Width", 1, (1.0,), min=0.3, max=3, disable_when=dis("streak"),
          help="Multiplies widths; wide curtains still go where water collects."),
        R("streak_int", "Intensity", 1, (1.0,), min=0, max=2, disable_when=dis("streak"),
          help="Multiplies opacity."),
        R("streak_colvar", "Colour Variation", 1, (0.7,), min=0, max=1, disable_when=dis("streak"),
          help="0 = all soot grey-brown; 1 = green-black damp, rust and pale washed runs mixed in by cause."),
        R("streak_top", "Top-Floor Bias", 1, (0.9,), min=0, max=2, disable_when=dis("streak"),
          help="Extra strength and length at the top floors (driven rain): +bias x (floor/top)^1.5."),
    ]))
    fo.addParmTemplate(_f("f_stain", "Stain Fields", [
        ovr("stain", "Stain Fields", "facade staining"),
        R("stain_amt", "Amount", 1, (0.56,), min=0, max=1, disable_when=dis("stain"),
          help="Facade-scale mottled blotches built from 3-6 layered decals at 10-45 % each, by cause and physics."),
        R("stain_scale", "Blotch Size", 1, (1.0,), min=0.3, max=2.5, disable_when=dis("stain"),
          help="Multiplies blotch size (1 = 1.5-6 m)."),
    ]))
    fo.addParmTemplate(_f("f_grime", "Grime", [
        ovr("grime", "Grime", "grime"),
        R("grime_amt", "Soot Darkening", 1, (0.6,), min=0, max=1, disable_when=dis("grime"),
          help="Soot baked into the vertex colour: background greying, sheltered soffits and recesses, lee faces, "
               "the band under the roof edge, the base, neglected flat columns."),
        R("grime_corner", "Inside Corners", 1, (0.87,), min=0, max=1, disable_when=dis("grime"),
          help="Grime strips where walls meet floors, soffits and fins: the one place water and dust gather."),
    ]))
    fo.addParmTemplate(_f("f_rust", "Rust", [
        ovr("rust", "Rust", "rust"),
        R("rust_amt", "Amount", 1, (0.67,), min=0, max=1, disable_when=dis("rust"),
          help="Rust on rail post bases, top rails and fixings (vertex colour) and the runs and blooms below them (decals)."),
    ]))
    fo.addParmTemplate(_f("f_patch", "Repaint Patches", [
        ovr("patch", "Repaint Patches", "repaint patching"),
        I("patches", "Patches", 1, (2,), min=0, max=8,
          disable_when=dis("patch"), help="Rectangles of repainted bays x floors (long faces) or wall cells (gables)."),
        R("patch_contrast", "Contrast", 1, (0.85,), min=0, max=1, disable_when=dis("patch"),
          help="How much cleaner and off-tone the newer paint reads."),
    ]))
    fo.addParmTemplate(_f("f_efflo", "Efflorescence", [
        ovr("efflo", "Efflorescence", "efflorescence"),
        R("efflo_amt", "Amount", 1, (0.44,), min=0, max=1, disable_when=dis("efflo"),
          help="White salt drips and blooms under slab edges, between rail posts and at the gable base."),
    ]))
    fo.addParmTemplate(_f("f_bio", "Biological Growth", [
        ovr("bio", "Biological Growth", "growth"),
        R("bio_amt", "Amount", 1, (0.57,), min=0, max=1, disable_when=dis("bio"),
          help="Green-black algae and moss on the north side and the shaded base, at drip landings and damp causes."),
    ]))
    fo.addParmTemplate(_f("f_splash", "Base Splash Band", [
        ovr("splash", "Splash Band", "the splash band"),
        R("splash_amt", "Amount", 1, (0.84,), min=0, max=1, disable_when=dis("splash"),
          help="Rain-splashed dirt along the base of every ground-level wall."),
        R("splash_h", "Height (m)", 1, (0.54,), min=0.1, max=1.5, disable_when=dis("splash"),
          help="Mean height of the ragged top edge."),
    ]))
    return fo


def _folder_by_label(entries, label):
    for e in entries:
        if isinstance(e, hou.FolderParmTemplate):
            if e.label() == label and e.folderType() == hou.folderType.Tabs:
                return e
            r = _folder_by_label(e.parmTemplates(), label)
            if r is not None:
                return r
    return None


def upgrade_definition(node):
    """Replace the Weathering tab of node's asset definition, move Years Since Repaint into it,
    and relabel the damage toggle. Tab folders inside an asset get generated names (f_mass_4),
    so they are found by label and the new tab keeps the old name."""
    d = node.type().definition()
    g = d.parmTemplateGroup()
    old = _folder_by_label(g.entries(), "Weathering")
    if g.find("age") is not None and g.containingFolder("age").label() == "Style":
        g.remove("age")
    old = _folder_by_label(g.entries(), "Weathering")
    wf = weather_folder()
    wf.setName(old.name())
    g.replace(old.name(), wf)
    dm = g.find("damage")
    if dm is not None:
        dm.setLabel("Edge Damage Geometry")
        dm.setHelp("Balcony fronts use the damaged variants (Weathering > Edge Damage). Off: all fronts clean.")
        g.replace("damage", dm)
    d.setParmTemplateGroup(g)
    return [t.name() for t in wf.parmTemplates()]
