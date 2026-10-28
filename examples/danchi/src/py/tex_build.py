# tex_build.py — tiling material maps in Copernicus (cop_lib helpers from the
# procedural-materials skill) and the decal atlas + sky with numpy. Writes into examples/danchi/tex.
exec(open((globals().get("DANCHI") or hou.text.expandString("$HIP/..")) + "/src/py/hlib.py", encoding="utf-8").read())
exec(open(SKILLS + "/procedural-materials/scripts/cop_lib.py", encoding="utf-8").read())
import numpy as np
OUTDIR = TEXDIR


def build_spray_tile(res=1024, tile_m=2.0):
    """Flattened spray-tile paint (押さえ吹付タイル): flat-topped mesas 8-24 mm in two size
    modes with crisp rims, troughs between, a small rounded grain, and an amplitude envelope
    so the relief is not stationary (thicker in patches, thinner/worn elsewhere)."""
    old = hou.node("/img/spray")
    if old:
        old.destroy()
    cn = net("/img", "spray", res)
    def mesa(name, size, cap):
        wn = mk(cn, "worleynoise", name, elementsize=size, jitter=0.9)
        r = mk(cn, "remap", name + "_r", inputmin=0.0, inputmax=0.5, outputmin=1.0, outputmax=0.0)
        w(r, 0, wn, "dist1")
        c = mk(cn, "clamp", name + "_flat", dolowerlimit=1, lowerlimit=0.0, doupperlimit=1, upperlimit=cap)
        w(c, 0, r)
        return c
    a = mesa("mesa_s", 0.011, 0.55)
    b = mesa("mesa_l", 0.024, 0.62)
    m = mk(cn, "blend", "mesas", mode="max")
    w(m, 0, a); w(m, 1, b)
    fine = mk(cn, "fractalnoise", "grain", elementsize=0.004, oct=3, amp=0.5, center=0.5)
    h1 = mk(cn, "blend", "h_grain", mode="add", mask=0.12)
    w(h1, 0, m); w(h1, 1, fine)
    env_n = mk(cn, "fractalnoise", "envelope_n", elementsize=0.45, oct=3, amp=0.5, center=0.5)
    env = mk(cn, "remap", "envelope", inputmin=0.3, inputmax=0.75, outputmin=0.25, outputmax=1.0)
    w(env, 0, env_n)
    env2 = mk(cn, "blend", "envelope_sq", mode="multiply")
    w(env2, 0, env); w(env2, 1, env)
    h2 = mk(cn, "blend", "h_env", mode="multiply")
    w(h2, 0, h1); w(h2, 1, env2)
    height = mk(cn, "equalize", "height", mode="stretch")
    w(height, 0, h2)
    nrm, ao, curv = _derived(cn, height, 0.003, tile_m, ao_radius=0.02)
    maps = {"height": height, "normal": nrm, "ao": ao}
    return _finish(cn, maps, {}, OUTDIR, "spray")


def build_concrete():
    old = hou.node("/img/concrete")
    if old:
        old.destroy()
    return build_concrete_panels("/img", "concrete", res=1024, out_dir=OUTDIR, tile_m=2.4)


# ---------------------------------------------------------------- decal atlas (numpy)
def _save_png(arr, path, mode="L"):
    """Write through Houdini's COP-free path: use PIL if present, else raw via hou."""
    from PIL import Image
    Image.fromarray(arr, mode).save(path)


def streak_atlas(path, cw=256, ch=1024, seed=7):
    """8 cells, each cw x ch, alpha only (white = full). v = 1 (top row) is the source.
    0 narrow run (notch, fixing)      1 sill-end fan (3-8 cm head fanning out)
    2 wide curtain from layered runs  3 fringe under a drip-less top (band + hair runs)
    4 rust run (narrow, teardrop end) 5 layered stain (3-6 runs, darker core)
    6 short partial drip              7 soft washed band (pale streak)"""
    rng = np.random.default_rng(seed)
    H, Wc = ch, cw
    y = np.linspace(0, 1, H)[:, None]          # 0 at the source (top), 1 at the far end
    x = np.linspace(-1, 1, Wc)[None, :]
    def noise1d(n, scale, rr):
        k = max(2, int(n / scale))
        v = rr.random(k + 3)
        xs = np.linspace(0, k, n)
        i = np.floor(xs).astype(int); f = xs - i; f = f * f * (3 - 2 * f)
        return v[i] * (1 - f) + v[i + 1] * f
    def run(cx, w0, w1, length, strength, rr, meander=0.05):
        # one run: head width w0 widening to w1, fading as 1 - t^0.5 to `length`
        t = np.clip(y / max(length, 1e-3), 0, 1)
        wiggle = (noise1d(H, 60, rr)[:, None] - 0.5) * meander * 2
        width = w0 + (w1 - w0) * t
        d = np.abs(x - cx - wiggle * t) / np.maximum(width, 1e-3)
        prof = np.clip(1 - d, 0, 1) ** 1.5
        fade = np.clip(1 - t ** 1.6, 0, 1) ** 0.7 * (y <= length)   # slow fade: runs stay visible down the face
        grain = 0.75 + 0.25 * noise1d(H, 9, rr)[:, None]
        return strength * prof * fade * grain
    cells = []
    # 0 narrow run
    c = run(0, 0.16, 0.26, 0.95, 1.0, rng, 0.04); cells.append(c)
    # 1 sill-end fan: dark head, fans 1.5-2x
    c = run(0, 0.22, 0.75, 1.0, 1.0, rng, 0.06) + 0.6 * run(0, 0.12, 0.3, 0.35, 1.0, rng)
    cells.append(c)
    # 2 wide curtain: 5 overlapping runs with lighter gaps
    c = np.zeros((H, Wc))
    for k in range(5):
        cx = -0.65 + 1.3 * k / 4 + rng.uniform(-0.1, 0.1)
        c = np.maximum(c, 0) + run(cx, rng.uniform(0.12, 0.25), rng.uniform(0.25, 0.4),
                                   rng.uniform(0.45, 1.0), rng.uniform(0.25, 0.6), rng, 0.05)
    cells.append(c)
    # 3 fringe: dark band in the top 8 %, then hair runs of power-law lengths
    c = np.clip(1 - y / 0.08, 0, 1) ** 0.8 * 0.8
    xs_ = np.sort(rng.uniform(-0.95, 0.95, 14))
    for cx in xs_:
        L = 0.08 + 0.9 * rng.random() ** 3
        c = c + run(cx, 0.025, 0.05, L, rng.uniform(0.3, 0.9), rng, 0.02)
    cells.append(c)
    # 4 rust run: narrow head, teardrop at the end
    c = run(0, 0.08, 0.14, 0.7, 1.0, rng, 0.03)
    td = np.exp(-(((x) / 0.18) ** 2 + ((y - 0.62) / 0.05) ** 2)) * 0.7
    cells.append(c + td)
    # 5 layered stain: 4 runs at 10-60 % plus a darker core where they overlap
    c = np.zeros((H, Wc))
    for k in range(4):
        c = c + run(rng.uniform(-0.35, 0.35), rng.uniform(0.25, 0.45), rng.uniform(0.4, 0.7),
                    rng.uniform(0.4, 0.95), rng.uniform(0.15, 0.5), rng, 0.08)
    cells.append(c)
    # 6 short partial drip
    c = run(0, 0.14, 0.2, 0.3, 0.9, rng, 0.03); cells.append(c)
    # 7 washed band: soft wide low-contrast
    c = run(0, 0.5, 0.8, 1.0, 0.7, rng, 0.08); cells.append(c)
    atlas = np.concatenate([np.clip(cc, 0, 1) for cc in cells], axis=1)
    # soft side margins so mips do not bleed between cells
    img = (atlas * 255).astype(np.uint8)
    _save_png(img, path)
    return path


def sky_latlong(path, w=1024, h=512):
    """Lat-long sky: pale haze at the horizon to a soft blue zenith, sRGB PNG. Round 7: zenith
    desaturated from (0.36, 0.55, 0.85) to match the reference photos (hazy pale blue, L* 75-85
    at the top of the frame in facade_01/04 and street_*)."""
    v = np.linspace(0, 1, h)[:, None]          # 0 top (zenith) .. 1 bottom (nadir)
    elev = (0.5 - v) * np.pi                    # radians, + above horizon
    t = np.clip(np.sin(np.clip(elev, 0, None)), 0, 1) ** 0.45
    horizon = np.array([0.84, 0.86, 0.88]); zenith = np.array([0.56, 0.66, 0.80])
    ground = np.array([0.42, 0.40, 0.37])
    col = horizon[None, None, :] * (1 - t[..., None]) + zenith[None, None, :] * t[..., None]
    col = np.where((elev < 0)[..., None], ground[None, None, :] * (0.85 + 0.15 * np.exp(elev * 6))[..., None]
                   + horizon * np.exp(elev * 12)[..., None] * 0.2, col)
    col = np.repeat(col, w, axis=1)
    img = (np.clip(col, 0, 1) * 255).astype(np.uint8)
    _save_png(img, path, "RGB")
    return path


def weather_maps():
    """Round 7: the weathering decal atlas and the macro-variation map (weather_atlas.py)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("weather_atlas", PY + "/weather_atlas.py")
    wa = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wa)
    return wa.build_all(OUTDIR)


def main():
    out = {}
    out["spray"] = build_spray_tile()
    out["concrete"] = build_concrete()
    out["atlas"] = streak_atlas(OUTDIR + "/streak_atlas.png")     # round 6, kept for 1.0
    out["weather"] = weather_maps()
    out["sky"] = sky_latlong(OUTDIR + "/sky.png")
    return out


if globals().get("ATLAS_ONLY"):
    RESULT = {"atlas": streak_atlas(OUTDIR + "/streak_atlas.png"), "weather": weather_maps()}
elif globals().get("SKY_ONLY"):
    RESULT = {"sky": sky_latlong(OUTDIR + "/sky.png")}
else:
    RESULT = main()
print(RESULT)
