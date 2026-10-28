# pieces.py — every kit piece except the golden bal_front, each its own SOP subnet
# (kit_<piece>) with one detail wrangle (VEX below, lib.vfl prepended), a name SOP per variant
# and an output. Pivot: bay bottom-centre on the outer wall plane, +Z out (README contract).
exec(open((globals().get("DANCHI") or hou.text.expandString("$HIP/..")) + "/src/py/hlib.py", encoding="utf-8").read())
import vexpressionmenu

GEO = hou.node("/obj/danchi/build")
HDR = 'float W = ch("../../../bay_w"); float H = ch("../../../floor_h"); int VAR = chi("variant");\n'

SRC = {}

SRC["bal_wall"] = r'''
float dx0, dx1, wx0, wx1; bal_openings(W, dx0, dx1, wx0, wx1);
float t = WALL_T;
boxm(0, set(-W * 0.5, 0, -t), set(dx0, H, 0), "paint_ext", "wall");
boxm(0, set(dx1, 0, -t), set(wx0, H, 0), "paint_ext", "wall");
boxm(0, set(wx1, 0, -t), set(W * 0.5, H, 0), "paint_ext", "wall");
boxm(0, set(dx0, 2.0, -t), set(dx1, H, 0), "paint_ext", "wall");
boxm(0, set(wx0, 2.0, -t), set(wx1, H, 0), "paint_ext", "wall");
boxm(0, set(wx0, 0, -t), set(wx1, 0.9, 0), "paint_ext", "wall");
'''

# sliding sash: 2 panels on two tracks; VAR = state 0 closed, 1 part open, 2 open
SASH = r'''
float f = 0.045, fz0 = -0.13, fz1 = -0.05;
float x0 = -ow * 0.5, x1 = ow * 0.5;
boxm(0, set(x0, 0, fz0), set(x1, 0.035, fz1 + 0.01), "alu", "frame");
boxm(0, set(x0, oh - f, fz0), set(x1, oh, fz1), "alu", "frame");
boxm(0, set(x0, 0, fz0), set(x0 + f, oh, fz1), "alu", "frame");
boxm(0, set(x1 - f, 0, fz0), set(x1, oh, fz1), "alu", "frame");
float iw = ow - 2 * f, ih = oh - f - 0.035;
float pw = iw * 0.5 + 0.025;
float open = VAR == 0 ? 0.0 : VAR == 1 ? 0.35 * iw / 3.3 + 0.15 : pw - 0.08;
for (int k = 0; k < 2; k++) {
    float zb = k == 0 ? -0.118 : -0.088;          // back track (left panel), front track (right)
    float zf = zb + 0.026;
    float px0 = k == 0 ? x0 + f : x1 - f - pw;
    if (k == 1) px0 -= open;
    float px1 = px0 + pw, py0 = 0.035, py1 = 0.035 + ih;
    float s = 0.04, r = 0.05;
    boxm(0, set(px0, py0, zb), set(px0 + s, py1, zf), "alu", "frame");
    boxm(0, set(px1 - s, py0, zb), set(px1, py1, zf), "alu", "frame");
    boxm(0, set(px0 + s, py0, zb), set(px1 - s, py0 + r, zf), "alu", "frame");
    boxm(0, set(px0 + s, py1 - s, zb), set(px1 - s, py1, zf), "alu", "frame");
    float gz = (zb + zf) * 0.5;
    int g = quadm(0, set(px0 + s, py1 - s, gz), set(px1 - s, py1 - s, gz), set(px1 - s, py0 + r, gz), set(px0 + s, py0 + r, gz), "glass", "own");
    setprimattrib(0, "pane", g, k);
}
'''
SRC["sash_door"] = "float ow = min(3.4, W - 2.6), oh = 2.0;\n" + SASH
SRC["bal_window"] = "float dx0, dx1, wx0, wx1; bal_openings(W, dx0, dx1, wx0, wx1);\nfloat ow = wx1 - wx0, oh = 1.1;\n" + SASH + r'''
// window sill (steel, painted) projecting 4 cm with drip edge
boxm(0, set(x0 - 0.03, -0.02, -0.06), set(x1 + 0.03, 0.0, 0.04), "steel", "frame");
'''

SRC["partition"] = r'''
float top = H - 0.15, z0 = 0.02, z1 = 1.04, f = 0.035;
boxm(0, set(-0.02, 0, z0), set(0.02, top, z0 + f), "alu", "frame");
boxm(0, set(-0.02, 0, z1 - f), set(0.02, top, z1), "alu", "frame");
boxm(0, set(-0.02, top - f, z0), set(0.02, top, z1), "alu", "frame");
boxm(0, set(-0.02, 0.06, z0), set(0.02, 0.06 + f, z1), "alu", "frame");
boxm(0, set(-0.005, 0.06 + f, z0 + f), set(0.005, top - f, z1 - f), "board", "board");
// the escape notice, a small dark label at eye height on the board's outer half
int lb = boxc(0, set(-0.007, 1.35, 0.55), set(0.007, 1.5, 0.85), "sign", {0.18, 0.2, 0.22});
'''

SRC["balustrade"] = r'''
// white steel vertical-bar rail over the open section at the left of the bay (on a 10 cm upstand)
float xa = -W * 0.5 + 0.05, xb = -W * 0.5 + rail_w(W) - 0.05, z = 1.125;
int np = max(2, int(ceil((xb - xa) / 1.3)) + 1);
for (int i = 0; i < np; i++) {
    float x = lerp(xa, xb, float(i) / (np - 1));
    boxm(0, set(x - 0.022, 0.1, z - 0.022), set(x + 0.022, 1.12, z + 0.022), "steel", "rail");
}
boxm(0, set(xa - 0.02, 1.12, z - 0.032), set(xb + 0.02, 1.165, z + 0.032), "steel", "rail");
boxm(0, set(xa, 0.16, z - 0.015), set(xb, 0.19, z + 0.015), "steel", "rail");
for (float x = xa + 0.11; x < xb - 0.05; x += 0.11)
    boxm(0, set(x - 0.008, 0.19, z - 0.008), set(x + 0.008, 1.12, z + 0.008), "steel", "rail");
'''

SRC["bal_fin"] = r'''
boxm(0, set(-0.09, -0.15, 0), set(0.09, H - 0.15, 1.2), "paint_ext", "wall");
'''

SRC["bal_hw"] = r'''
// handrail on posts over the parapet top, drain pipe at the right end, laundry hangers
float rz = 1.125;
float sa = -W * 0.5 + rail_w(W);
int np = max(2, int(floor((W * 0.5 - sa - 0.5) / 1.6)) + 1);
for (int i = 0; i < np; i++) {
    float px = sa + 0.3 + i * (W * 0.5 - sa - 0.6) / (np - 1);
    boxm(0, set(px - 0.016, 0.93, rz - 0.016), set(px + 0.016, 1.12, rz + 0.016), "steel", "rail");
    int bp = boxm(0, set(px - 0.045, 0.938, rz - 0.045), set(px + 0.045, 0.952, rz + 0.045), "steel", "rail");
    for (int f = 0; f < 6; f++) setprimattrib(0, "rustsrc", bp + f, 1);
}
boxm(0, set(sa + 0.02, 1.12, rz - 0.032), set(W * 0.5 - 0.06, 1.165, rz + 0.032), "steel", "rail");
// PVC drain pipe from this balcony floor to the slab above, with two clamps
vector pc = set(W * 0.5 - 0.12, 0, 0.94);
cylm(0, pc, pc + set(0, H - 0.15, 0), 0.03, 8, "plastic", "pipe");
for (int k = 1; k < 3; k++) {
    vector c = pc + set(0, k * (H - 0.15) / 3.0, 0);
    cylm(0, c - {0, 0.02, 0}, c + {0, 0.02, 0}, 0.036, 8, "steel", "rail");
}
// laundry-pole hangers under the slab above
for (int s = -1; s <= 1; s += 2) {
    float hx = s * (W * 0.5 - 1.0);
    boxm(0, set(hx - 0.012, H - 0.15 - 0.28, 0.83), set(hx + 0.012, H - 0.15, 0.86), "steel", "frame");
    boxm(0, set(hx - 0.012, H - 0.15 - 0.30, 0.78), set(hx + 0.012, H - 0.15 - 0.27, 0.92), "steel", "frame");
}
'''

# interior card set behind the glass; VAR = persona (0 tidy 1 family 2 gardener 3 elderly 4 vacant)
SRC["room"] = r'''
float dx0, dx1, wx0, wx1; bal_openings(W, dx0, dx1, wx0, wx1);
float d = 3.6, h = 2.4, xa = -W * 0.5 + 0.1, xb = W * 0.5 - 0.1, zf = -0.19;
// inward-facing shell: back wall, floor, ceiling, sides
quadm(0, set(xa, h, -d), set(xb, h, -d), set(xb, 0, -d), set(xa, 0, -d), "room", "room_wall");
quadm(0, set(xa, 0.01, zf), set(xb, 0.01, zf), set(xb, 0.01, -d), set(xa, 0.01, -d), "room", "room_floor");
quadm(0, set(xa, h, -d), set(xb, h, -d), set(xb, h, zf), set(xa, h, zf), "room", "room_ceil");
quadm(0, set(xa, h, zf), set(xa, h, -d), set(xa, 0, -d), set(xa, 0, zf), "room", "room_wall");
quadm(0, set(xb, h, -d), set(xb, h, zf), set(xb, 0, zf), set(xb, 0, -d), "room", "room_wall");
if (VAR != 4) {
    // furniture masses
    boxm(0, set(xa + 0.3, 0, -d + 0.05), set(xa + 1.6, 1.1, -d + 0.5), "room", "furn");
    boxm(0, set(xb - 1.9, 0, -2.2), set(xb - 0.5, 0.42, -1.4), "room", "furn2");
    // curtains: lace (light) and drapes (colour by unit), closure by persona
    float close_[] = array(0.2, 0.35, 0.5, 0.75, 0.0);
    float c = close_[VAR];
    float zl = -0.17, zd = -0.18;
    float opens[] = array(dx0, wx0);
    foreach (float ox0; opens) {
        float ox1 = ox0 == dx0 ? dx1 : wx1;
        float oy0 = ox0 == dx0 ? 0.05 : 0.95, oy1 = ox0 == dx0 ? 2.02 : 2.02;
        float ow = ox1 - ox0;
        if (VAR != 2) quadm(0, set(ox0, oy1, zl), set(ox1, oy1, zl), set(ox1, oy0, zl), set(ox0, oy0, zl), "fabric", "lace");
        float wl = ow * (0.12 + c * 0.38), wr = ow * (0.12 + c * 0.3);
        // two drapes with folds (6 strips, alternating depth)
        for (int sdd = 0; sdd < 2; sdd++) {
            float a0 = sdd == 0 ? ox0 - 0.06 : ox1 - wr;
            float a1 = sdd == 0 ? ox0 + wl : ox1 + 0.06;
            int ns = 6;
            for (int k = 0; k < ns; k++) {
                float u0 = lerp(a0, a1, float(k) / ns), u1 = lerp(a0, a1, float(k + 1) / ns);
                float z0 = zd - 0.03 * (k % 2), z1 = zd - 0.03 * ((k + 1) % 2);
                quadm(0, set(u0, oy1 + 0.04, z0), set(u1, oy1 + 0.04, z1), set(u1, oy0, z1), set(u0, oy0, z0), "fabric", "drape");
            }
        }
    }
}
'''

# LOD1 stand-in for the interior: one dark card behind the openings
SRC["room_card"] = r'''
quadm(0, set(-W * 0.5 + 0.2, 2.1, -0.4), set(W * 0.5 - 0.2, 2.1, -0.4), set(W * 0.5 - 0.2, 0, -0.4), set(-W * 0.5 + 0.2, 0, -0.4), "room", "room_wall");
'''

# outdoor AC unit; VAR = generation 0 (old, beige) 1 (ivory) 2 (newer, grey-white)
SRC["ac_unit"] = r'''
float w_[] = array(0.75, 0.80, 0.78), h_[] = array(0.58, 0.55, 0.62), d_[] = array(0.26, 0.28, 0.29);
vector c_[] = array({0.52, 0.50, 0.45}, {0.70, 0.69, 0.66}, {0.66, 0.67, 0.67});
float w = w_[VAR], h = h_[VAR], d = d_[VAR];
vector col = c_[VAR];
boxc(0, set(-w * 0.5, 0.06, 0), set(w * 0.5, 0.06 + h, d), "plastic", col);
// feet
boxc(0, set(-w * 0.5 + 0.05, 0, 0.02), set(-w * 0.5 + 0.12, 0.06, d - 0.02), "metal", {0.3, 0.3, 0.3});
boxc(0, set(w * 0.5 - 0.12, 0, 0.02), set(w * 0.5 - 0.05, 0.06, d - 0.02), "metal", {0.3, 0.3, 0.3});
// fan grille: dark recess + ring, offset to the left; valve cover on the right
float gx = -w * 0.5 + 0.06 + h * 0.42, gy = 0.06 + h * 0.5, gr = h * 0.38;
cylm(0, set(gx, gy, d - 0.004), set(gx, gy, d + 0.002), gr, 16, "plastic", "own");
int g = cylm(0, set(gx, gy, d + 0.002), set(gx, gy, d + 0.008), gr * 0.92, 16, "metal", "own");
for (int i = g; i < g + 18; i++) setprimattrib(0, "Cd", i, {0.05, 0.05, 0.05});
for (int i = g - 18; i < g; i++) setprimattrib(0, "Cd", i, col * 0.8);
boxc(0, set(w * 0.5 - 0.17, 0.08, d), set(w * 0.5 - 0.02, 0.06 + h * 0.7, d + 0.01), "plastic", col * 0.92);
// refrigerant lines in a white duct cover, from the wall down to the unit's back
boxc(0, set(w * 0.5 - 0.1, 0.3, -0.05), set(w * 0.5 - 0.02, 1.9, 0.0), "plastic", {0.72, 0.72, 0.70});
'''

# laundry on a pole under the slab above; VAR = arrangement 0..3
SRC["laundry"] = r'''
// laundry under the slab above. VAR = 0 a few towels, 1 one clustered group, 2 a full pole
// with a sock-ring hanger, 3 two poles' worth. Items: towels folded over the pole, shirts on
// hangers (lower), sock rings (角ハンガー) with many small items; widths, lengths, gaps and
// rotation vary; clustered with empty stretches.
float py = H - 0.15 - 0.30, pz = 0.85;
float xa = -W * 0.5 + 0.5, xb = W * 0.5 - 0.5;
cylm(0, set(xa, py, pz), set(xb, py, pz), 0.016, 6, "metal", "own");
int n = VAR == 0 ? 2 : VAR == 1 ? 4 : VAR == 2 ? 7 : 10;
float cur = lerp(xa + 0.1, xb - 2.5, rand(VAR * 3.3 + 0.1));
if (VAR >= 2) cur = xa + 0.1;
for (int i = 0; i < n && cur < xb - 0.3; i++) {
    float r = rand(i * 3.1 + VAR * 7.7);
    int kind = r < 0.45 ? 0 : (r < 0.8 ? 1 : 2);     // 0 towel, 1 shirt on a hanger, 2 sock ring
    float w = kind == 0 ? lerp(0.28, 0.6, rand(i * 1.9 + VAR)) : (kind == 1 ? lerp(0.42, 0.55, rand(i * 2.2)) : 0.36);
    float h = kind == 0 ? lerp(0.3, 0.55, rand(i * 4.1 + VAR)) : (kind == 1 ? lerp(0.55, 0.75, rand(i * 4.7)) : 0.38);
    float drop = kind == 1 ? 0.12 : (kind == 2 ? 0.18 : 0.0);   // hangers hang lower
    float rot = radians((rand(i * 5.3 + VAR) - 0.5) * 30);
    float cx = cur + w * 0.5;
    vector4 q = quaternion(rot, {0, 1, 0});
    if (kind == 2) {
        // sock ring: a square frame with 8-12 small items on clips
        vector c0 = set(cx, py - drop, pz);
        boxm(0, c0 + set(-0.18, -0.01, -0.18), c0 + set(0.18, 0.01, 0.18), "plastic", "own");
        cylm(0, c0, set(cx, py, pz), 0.004, 3, "plastic", "own");
        int ns = 8 + int(rand(i + VAR) * 4);
        for (int s = 0; s < ns; s++) {
            float t = float(s) / ns * 4.0;
            vector e = t < 1 ? set(-0.18 + t * 0.36, 0, -0.18) : t < 2 ? set(0.18, 0, -0.18 + (t - 1) * 0.36) : t < 3 ? set(0.18 - (t - 2) * 0.36, 0, 0.18) : set(-0.18, 0, 0.18 - (t - 3) * 0.36);
            float sh = lerp(0.12, 0.3, rand(s * 7.1 + i));
            int bx = boxm(0, c0 + e + set(-0.035, -sh, -0.004), c0 + e + set(0.035, -0.01, 0.004), "fabric", "laundry");
            for (int f = 0; f < 6; f++) setprimattrib(0, "lidx", bx + f, i * 20 + s);
        }
        cur += 0.45 + rand(i * 9.1 + VAR) * 0.3;
        continue;
    }
    int nx = 6, ny = 4;
    for (int layer = 0; layer < 2; layer++) {
        int pts[];
        for (int j = 0; j <= ny; j++) for (int k = 0; k <= nx; k++) {
            float u = float(k) / nx, v = float(j) / ny;
            float x = (u - 0.5) * w * (kind == 1 && v > 0.15 ? 0.86 : 1.0);
            float y = -v * h - 0.02 - drop;
            float z = 0.012 * sin(u * PI * (3 + VAR)) * v + 0.008 * v * v + (layer == 0 ? 0.004 : -0.004);
            if (kind == 0 && layer == 1) z -= 0.012;          // towel: two layers over the pole
            vector p = qrotate(q, set(x, y, z)) + set(cx, py, pz);
            append(pts, addpoint(0, p));
        }
        for (int j = 0; j < ny; j++) for (int k = 0; k < nx; k++) {
            int a = j * (nx + 1) + k;
            int pr = layer == 0 ? addprim(0, "poly", pts[a], pts[a + 1], pts[a + nx + 2], pts[a + nx + 1])
                                : addprim(0, "poly", pts[a], pts[a + nx + 1], pts[a + nx + 2], pts[a + 1]);
            setprimattrib(0, "mat", pr, "fabric");
            setprimattrib(0, "cdkey", pr, "laundry");
            setprimattrib(0, "lidx", pr, i);
        }
    }
    if (kind == 1) {
        // hanger hook and sleeves
        cylm(0, set(cx, py, pz), set(cx, py - drop, pz), 0.003, 3, "plastic", "own");
        float sides[] = array(-1.0, 1.0);
        foreach (float sx; sides) {
            vector a = qrotate(q, set(sx * w * 0.45, -0.04 - drop, 0)) + set(cx, py, pz);
            int b2 = boxm(0, a + set(-0.07, -0.2, -0.008), a + set(0.07, 0, 0.008), "fabric", "laundry");
            for (int f = 0; f < 6; f++) setprimattrib(0, "lidx", b2 + f, i);
        }
    }
    // clustered: mostly small gaps, sometimes a long empty stretch
    float gap = rand(i * 9.1 + VAR) < 0.8 ? lerp(0.02, 0.15, rand(i * 3.7)) : lerp(0.5, 1.4, rand(i * 6.1));
    cur += w + gap;
}
'''

SRC["futon"] = r'''
// a futon folded over the handrail: outer leaf hanging outside, inner leaf inside, clips
float w = 0.95, t = 0.07;
int pts = 0;
int a = boxm(0, set(-w * 0.5, 0.42, 1.2), set(w * 0.5, 1.17, 1.2 + t), "fabric", "futon");
int b = boxm(0, set(-w * 0.5, 1.165, 1.06), set(w * 0.5, 1.165 + t, 1.2 + t), "fabric", "futon");
int c = boxm(0, set(-w * 0.5, 0.55, 1.06 - t), set(w * 0.5, 1.17, 1.06), "fabric", "futon");
for (int k = -1; k <= 1; k += 2)
    boxc(0, set(k * 0.3 - 0.025, 1.1, 1.18 + t), set(k * 0.3 + 0.025, 1.25, 1.21 + t), "plastic", {0.65, 0.65, 0.62});
'''

SRC["plants"] = r'''
// pots along the parapet's inner face and two on the parapet top; leaf cards
for (int i = 0; i < 6; i++) {
    float x = -W * 0.5 + 0.5 + i * (W - 1.0) / 5.0 + (rand(i * 1.7) - 0.5) * 0.3;
    int top = i % 3 == 1;
    float y = top ? 0.95 : 0.0, z = top ? 1.12 : 0.9;
    float r = top ? 0.09 : 0.14 + rand(i) * 0.06, h = top ? 0.14 : 0.25 + rand(i * 2.3) * 0.15;
    vector pc = rand(i * 5.1) < 0.5 ? set(0.45, 0.22, 0.12) : set(0.32, 0.32, 0.31);
    int p = cylm(0, set(x, y, z), set(x, y + h, z), r, 10, "plastic", "own");
    for (int k = p; k < p + 12; k++) setprimattrib(0, "Cd", k, pc);
    int nl = top ? 10 : 22;
    for (int l = 0; l < nl; l++) {
        vector o = set(rand(l * 1.3 + i) - 0.5, rand(l * 2.9 + i), rand(l * 4.1 + i) - 0.5) * set(r * 3, h * 2.2 + 0.2, r * 2.4);
        vector c = set(x, y + h, z) + o;
        float s = 0.06 + rand(l * 7.7 + i) * 0.06;
        vector u = normalize(set(rand(l + 0.1) - 0.5, rand(l + 0.2) * 0.6, rand(l + 0.3) - 0.5));
        vector v = normalize(cross(u, set(0.2, 1, 0.1)));
        int q = quadm(0, c - u * s - v * s * 0.4, c - u * s + v * s * 0.4, c + u * s + v * s * 0.4, c + u * s - v * s * 0.4, "fabric", "leaf");
        setprimattrib(0, "lidx", q, l);
    }
}
'''

SRC["cor_wall"] = r'''
float t = WALL_T;
float d0 = -W * 0.5 + 0.325, d1 = d0 + 0.85, m0 = -W * 0.5 + 1.35, m1 = m0 + 0.8;
float k0 = W * 0.5 - 1.9, k1 = W * 0.5 - 0.7;
boxm(0, set(-W * 0.5, 0, -t), set(d0, H, 0), "paint_ext", "wall");
boxm(0, set(d1, 0, -t), set(m0, H, 0), "paint_ext", "wall");
boxm(0, set(m1, 0, -t), set(k0, H, 0), "paint_ext", "wall");
boxm(0, set(k1, 0, -t), set(W * 0.5, H, 0), "paint_ext", "wall");
boxm(0, set(d0, 2.0, -t), set(d1, H, 0), "paint_ext", "wall");
boxm(0, set(m0, 1.9, -t), set(m1, H, 0), "paint_ext", "wall");
boxm(0, set(m0, 0, -t), set(m1, 0.1, 0), "paint_ext", "wall");
boxm(0, set(k0, 1.9, -t), set(k1, H, 0), "paint_ext", "wall");
boxm(0, set(k0, 0, -t), set(k1, 1.0, 0), "paint_ext", "wall");
'''

SRC["steel_door"] = r'''
// steel unit door: frame, leaf recessed 6 cm, lever, number plate, mail slot, peephole
float w = 0.85, h = 2.0, f = 0.04;
boxm(0, set(-w * 0.5, 0, -0.1), set(-w * 0.5 + f, h, -0.02), "steel", "door");
boxm(0, set(w * 0.5 - f, 0, -0.1), set(w * 0.5, h, -0.02), "steel", "door");
boxm(0, set(-w * 0.5, h - f, -0.1), set(w * 0.5, h, -0.02), "steel", "door");
boxm(0, set(-w * 0.5 + f, 0.01, -0.1), set(w * 0.5 - f, h - f, -0.06), "steel", "door");
boxc(0, set(0.24, 0.98, -0.06), set(0.36, 1.0, -0.02), "metal", {0.6, 0.6, 0.58});
boxc(0, set(0.27, 0.95, -0.06), set(0.29, 1.03, -0.045), "metal", {0.6, 0.6, 0.58});
boxc(0, set(-0.12, 1.45, -0.06), set(0.12, 1.53, -0.052), "sign", {0.75, 0.74, 0.70});
boxc(0, set(-0.15, 0.85, -0.06), set(0.15, 0.89, -0.055), "metal", {0.12, 0.12, 0.12});
'''

SRC["meter_door"] = r'''
// pipe-shaft / meter box: two flush steel leaves with louvres
float w = 0.8, h = 1.8;
for (int k = 0; k < 2; k++) {
    float x0 = -w * 0.5 + k * w * 0.5 + 0.01, x1 = x0 + w * 0.5 - 0.02;
    boxm(0, set(x0, 0.0, -0.07), set(x1, h, -0.04), "steel", "door2");
    for (int l = 0; l < 6; l++) {
        float y = 1.35 + l * 0.05;
        boxm(0, set(x0 + 0.05, y, -0.04), set(x1 - 0.05, y + 0.02, -0.025), "steel", "door2");
    }
}
'''

SRC["kitchen_win"] = r'''
// frosted kitchen window with an aluminium grille (面格子) and a sill
float w = 1.2, h = 0.9, f = 0.04;
boxm(0, set(-w * 0.5, 0, -0.1), set(w * 0.5, f, -0.03), "alu", "frame");
boxm(0, set(-w * 0.5, h - f, -0.1), set(w * 0.5, h, -0.03), "alu", "frame");
boxm(0, set(-w * 0.5, 0, -0.1), set(-w * 0.5 + f, h, -0.03), "alu", "frame");
boxm(0, set(w * 0.5 - f, 0, -0.1), set(w * 0.5, h, -0.03), "alu", "frame");
boxm(0, set(-0.01, f, -0.09), set(0.01, h - f, -0.05), "alu", "frame");
boxc(0, set(-w * 0.5 + f, f, -0.075), set(w * 0.5 - f, h - f, -0.065), "plastic", {0.48, 0.52, 0.52});
// grille: frame + vertical bars 10 cm apart, 8 cm proud of the wall
float gz0 = 0.02, gz1 = 0.09;
boxm(0, set(-w * 0.5 - 0.05, -0.04, gz0), set(w * 0.5 + 0.05, -0.01, gz1), "alu", "frame");
boxm(0, set(-w * 0.5 - 0.05, h + 0.01, gz0), set(w * 0.5 + 0.05, h + 0.04, gz1), "alu", "frame");
for (float x = -w * 0.5; x <= w * 0.5 + 1e-4; x += 0.1)
    boxm(0, set(x - 0.008, -0.01, gz1 - 0.02), set(x + 0.008, h + 0.01, gz1), "alu", "frame");
for (int s = -1; s <= 1; s += 2)
    boxm(0, set(s * (w * 0.5 + 0.03) - 0.01, -0.04, 0.0), set(s * (w * 0.5 + 0.03) + 0.01, h + 0.04, gz1), "alu", "frame");
boxm(0, set(-w * 0.5 - 0.06, -0.06, -0.03), set(w * 0.5 + 0.06, -0.04, 0.05), "steel", "frame");
'''

SRC["cor_hw"] = r'''
// corridor hardware: ceiling lamp over the door, gas water heater beside it
float dx = -W * 0.5 + 0.75;
int l = boxc(0, set(dx - 0.14, H - 0.15 - 0.09, 0.55), set(dx + 0.14, H - 0.15, 0.75), "plastic", {0.75, 0.75, 0.72});
for (int f = 0; f < 6; f++) setprimattrib(0, "lamp", l + f, 1);
boxc(0, set(dx + 1.42, 1.15, 0.0), set(dx + 1.78, 1.72, 0.17), "plastic", {0.70, 0.70, 0.68});
cylm(0, set(dx + 1.5, 0.9, 0.05), set(dx + 1.5, 1.15, 0.05), 0.012, 6, "metal", "pipe");
cylm(0, set(dx + 1.7, 0.9, 0.05), set(dx + 1.7, 1.15, 0.05), 0.012, 6, "metal", "pipe");
'''

SRC["core_wall"] = r'''
// balcony-side wall of a core bay; stair cores get a small window at each half landing
float Wc = VAR == 1 ? 5.5 : 3.0;
float t = WALL_T;
if (VAR == 0) {
    float x0 = -0.45, x1 = 0.45, y0 = 1.85, y1 = 2.55;
    boxm(0, set(-Wc * 0.5, 0, -t), set(x0, H, 0), "paint_ext", "wall");
    boxm(0, set(x1, 0, -t), set(Wc * 0.5, H, 0), "paint_ext", "wall");
    boxm(0, set(x0, 0, -t), set(x1, y0, 0), "paint_ext", "wall");
    boxm(0, set(x0, y1, -t), set(x1, H, 0), "paint_ext", "wall");
    boxm(0, set(x0, y0, -0.12), set(x1, y0 + 0.03, -0.06), "alu", "frame");
    boxm(0, set(x0, y1 - 0.03, -0.12), set(x1, y1, -0.06), "alu", "frame");
    boxc(0, set(x0, y0 + 0.03, -0.1), set(x1, y1 - 0.03, -0.09), "plastic", {0.42, 0.45, 0.45});
} else {
    boxm(0, set(-Wc * 0.5, 0, -t), set(Wc * 0.5, H, 0), "paint_ext", "wall");
}
'''

SRC["cor_landing"] = r'''
float Wc = VAR == 1 ? 5.5 : 3.0;
boxm(0, set(-Wc * 0.5, -0.18, 0), set(Wc * 0.5, 0, COR_W), "paint_ext", "wall");
int b = boxm(0, set(-Wc * 0.5, -0.181, 0), set(Wc * 0.5, -0.18, COR_W), "soffit", "soffit");
'''

# pieces and their variant names
PIECES = {
    "bal_wall": ["bal_wall"],
    "sash_door": ["sash_door_s0", "sash_door_s1", "sash_door_s2"],
    "bal_window": ["bal_window_s0", "bal_window_s1", "bal_window_s2"],
    "partition": ["partition"],
    "bal_fin": ["bal_fin"],
    "bal_hw": ["bal_hw"],
    "room": [f"room_p{i}" for i in range(5)],
    "room_card": ["room_card"],
    "ac_unit": ["ac_g0", "ac_g1", "ac_g2"],
    "laundry": [f"laundry_v{i}" for i in range(4)],
    "futon": ["futon"],
    "plants": ["plants"],
    "cor_wall": ["cor_wall"],
    "steel_door": ["steel_door"],
    "meter_door": ["meter_door"],
    "kitchen_win": ["kitchen_win"],
    "cor_hw": ["cor_hw"],
    "core_wall": ["core_wall_3", "core_wall_55"],
    "cor_landing": ["cor_landing_3", "cor_landing_55"],
}


def build_piece(key, names):
    old = GEO.node("kit_" + key)
    if old:
        old.destroy()
    sn = GEO.createNode("subnet", "kit_" + key)
    lib = open(f"{VEX}/lib.vfl", encoding="utf-8").read()
    outs = []
    for v, nm in enumerate(names):
        w = wrangle(sn, f"build_{v}", lib + "\n" + HDR + SRC[key], cls="detail")
        g = w.parmTemplateGroup()
        g.append(hou.IntParmTemplate("variant", "Variant", 1, (v,)))
        w.setParmTemplateGroup(g)
        n = node(sn, "name", f"name_{v}", [w])
        n.parm("name1").set(nm)
        outs.append(n)
    mg = node(sn, "merge", "variants", outs)
    nrm = node(sn, "normal", "normal", [mg])
    nrm.parm("cuspangle").set(40)
    node(sn, "output", "output0", [nrm])
    sn.layoutChildren()
    sn.setUserData("covers", " ".join(names))
    errs = [(c.name(), c.errors()) for c in sn.children() if c.errors()]
    return errs


def bal_cor_front():
    """kit_cor_front: the golden profile reused at corridor depth (1.4) and a 1.1 m parapet."""
    old = GEO.node("kit_cor_front")
    if old:
        old.destroy()
    sn = GEO.createNode("subnet", "kit_cor_front")
    pr = wrangle(sn, "profile", vex("bal_front_profile", lib=False), cls="detail")
    vexpressionmenu.createSpareParmsFromChCalls(pr, "snippet")
    pr.setParms({"chamfer": 0.012, "joint": 0.01, "depth": 1.4, "ptop": 1.1})
    tag = wrangle(sn, "tag", open(f"{PY}/piece_bal_front.py", encoding="utf-8").read().split("TAG = r'''")[1].split("'''")[0], [pr], cls="prim")
    nrm = node(sn, "normal", "normal", [tag])
    nrm.parm("cuspangle").set(25)
    n = node(sn, "name", "name", [nrm])
    n.parm("name1").set("cor_front")
    node(sn, "output", "output0", [n])
    sn.layoutChildren()
    sn.setUserData("covers", "cor_front")


def bal_open():
    old = GEO.node("kit_bal_open")
    if old:
        old.destroy()
    sn = GEO.createNode("subnet", "kit_bal_open")
    pr = wrangle(sn, "profile", vex("bal_front_profile", lib=False), cls="detail")
    vexpressionmenu.createSpareParmsFromChCalls(pr, "snippet")
    pr.setParms({"chamfer": 0.012, "joint": 0.01, "depth": 1.2, "ptop": 0.1, "rail_part": 1})
    tag = wrangle(sn, "tag", open(f"{PY}/piece_bal_front.py", encoding="utf-8").read().split("TAG = r'''")[1].split("'''")[0], [pr], cls="prim")
    lib = open(f"{VEX}/lib.vfl", encoding="utf-8").read()
    bal = wrangle(sn, "balustrade", lib + chr(10) + HDR + SRC["balustrade"], cls="detail")
    g = bal.parmTemplateGroup(); g.append(hou.IntParmTemplate("variant", "Variant", 1, (0,))); bal.setParmTemplateGroup(g)
    mg = node(sn, "merge", "merge", [tag, bal])
    nrm = node(sn, "normal", "normal", [mg])
    nrm.parm("cuspangle").set(30)
    n = node(sn, "name", "name", [nrm])
    n.parm("name1").set("bal_open")
    node(sn, "output", "output0", [n])
    sn.layoutChildren()
    sn.setUserData("covers", "bal_open")


def main():
    errs = {}
    bal_open()
    for k, names in PIECES.items():
        e = build_piece(k, names)
        if e:
            errs[k] = e
    bal_cor_front()
    return errs


ERRS = main()
print("errors:", ERRS)
