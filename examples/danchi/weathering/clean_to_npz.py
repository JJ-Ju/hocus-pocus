"""hython: convert the clean run-7 elevation captures (albedo, class, depth, P, N) to npz."""
import json, os, sys
import numpy as np
import OpenImageIO as oiio
SRC, OUT = sys.argv[1], sys.argv[2]
os.makedirs(OUT, exist_ok=True)
def rd(path):
    inp = oiio.ImageInput.open(path)
    a = inp.read_image(oiio.FLOAT)
    spec = inp.spec()
    inp.close()
    return np.asarray(a), spec
for cfg in ("clean", "clean_dressed"):
    for view in ("S", "W", "N"):
        d = os.path.join(SRC, cfg)
        if not os.path.exists(os.path.join(d, view + "_albedo.exr")):
            continue
        arr = {}
        for k in ("albedo", "depth", "P", "N", "albedo_vcol"):
            f = os.path.join(d, "%s_%s.exr" % (view, k))
            if os.path.exists(f):
                a, spec = rd(f)
                arr[k] = a.astype(np.float32)
                print(cfg, view, k, a.shape, spec.nchannels, [spec.channel_name(i) for i in range(spec.nchannels)])
        c, spec = rd(os.path.join(d, view + "_class.png"))
        print(cfg, view, "class", c.shape, c.dtype, float(c.max()))
        code = np.rint(c[..., 0] * (65535.0 if c.max() <= 1.0 else 1.0)).astype(np.int64)
        arr["class_raw"] = code.astype(np.int32)
        np.savez(os.path.join(OUT, "%s_%s.npz" % (cfg, view)), **arr)
print("done")
