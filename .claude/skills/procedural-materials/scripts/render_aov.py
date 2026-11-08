#!/usr/bin/env hython
"""render_aov.py - render cameras of an existing /obj scene with Karma AOVs for build_anime_post.

Loads a hip read-only (it never saves it), imports /obj into /stage, and renders each camera
to one multi-part EXR with beauty C, albedo, depth (hitPz) and N (hitN). Round C used the
danchi v3 hip (cam_hero, cam_facade): 1280x720, 32 samples, Karma CPU, about 1 and 4 minutes.

  hython render_aov.py <scene.hip> cam_hero,cam_facade <out_dir> [samples]

Traps (Houdini 22.0.466, all hit in round C):
- sceneimport::2.0 `objects` is empty in a fresh node created from Python, so nothing is
  imported; set it to "*".
- karmarendersettings `resolutiony` is locked while `res_mode` is autoheight; setting it raises
  hou.PermissionError. Leave it: the height follows the camera aspect.
- The AOV toggles are `albedo`, `hitPz` (label "Depth (Camera Space)"), `hitN` and `primid`.
  They add RenderVars under /Render/<node name>/Vars; the EXR is multi-part, one part per
  AOV, named C, albedo, depth, N, primid. OpenImageIO's ImageInput spec shows only part 0.
- `primid` is per primitive (per triangle here), so it is no material mask, and husk logs
  "Pixel filter 'minmax' - Mode idcover requires PrimId channel". Use karmacryptomatte
  (material) or a primvar AOV for masks.
- With the dome light visible to camera, C alpha is 1 everywhere. Sky is depth == 0.
"""
import os
import sys
import time

import hou


def main():
    hip, cams, outdir = sys.argv[1], sys.argv[2].split(","), sys.argv[3]
    spp = int(sys.argv[4]) if len(sys.argv) > 4 else 32
    try:
        hou.hipFile.load(hip, suppress_save_prompt=True, ignore_load_warnings=True)
    except hou.LoadWarning as e:
        print("load warning:", str(e)[:300])
    st = hou.node("/stage")
    si = st.createNode("sceneimport::2.0", "imp")
    si.parm("objects").set("*")
    si.cook(force=True)
    campaths = [str(p.GetPath()) for p in si.stage().Traverse() if p.GetTypeName() == "Camera"]
    krs = st.createNode("karmarendersettings", "krs")
    krs.setInput(0, si)
    for k, v in dict(engine="cpu", pathtracedsamples=spp, samplesperpixel=spp, beauty=1,
                     albedo=1, hitPz=1, hitN=1).items():
        krs.parm(k).set(v)
    rop = st.createNode("usdrender_rop", "rop")
    rop.setInput(0, krs)
    os.makedirs(outdir, exist_ok=True)
    for cam in cams:
        cp = [c for c in campaths if c.endswith("/" + cam)]
        if not cp:
            print("no camera", cam, "in", campaths[:20])
            continue
        krs.parm("camera").set(cp[0])
        pic = "%s/%s_aov.exr" % (outdir, cam)
        krs.parm("picture").set(pic)
        t0 = time.time()
        rop.parm("execute").pressButton()
        print("rendered", cam, pic, os.path.exists(pic), "%.0fs" % (time.time() - t0),
              rop.errors() or "")


if __name__ == "__main__":
    main()
