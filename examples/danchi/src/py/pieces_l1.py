# pieces_l1.py — LOD1 stand-ins for the heavy kit pieces (same pivots and footprints).
exec(open((globals().get("DANCHI") or hou.text.expandString("$HIP/..")) + "/src/py/pieces.py", encoding="utf-8").read().replace("ERRS = main()", "ERRS = {}"))
L1 = {}
L1["bal_front_l1"] = r'''
float sa = -W * 0.5 + rail_w(W);
boxm(0, set(sa, -0.15, 0), set(W * 0.5, 0, 1.2), "paint_ext", "wall");
boxm(0, set(sa, 0, 1.05), set(W * 0.5, 0.95, 1.2), "paint_ext", "wall");
boxm(0, set(-W * 0.5, -0.15, 0), set(sa, 0.1, 1.2), "paint_ext", "wall");
'''
L1["cor_front_l1"] = r'''
boxm(0, set(-W * 0.5, -0.15, 0), set(W * 0.5, 0, 1.4), "paint_ext", "wall");
boxm(0, set(-W * 0.5, 0, 1.25), set(W * 0.5, 1.1, 1.4), "paint_ext", "wall");
'''
L1["bal_open_l1"] = r'''
float xa = -W * 0.5 + 0.05, xb = -W * 0.5 + rail_w(W) - 0.05, z = 1.125;
boxm(0, set(xa - 0.02, 1.12, z - 0.032), set(xb + 0.02, 1.165, z + 0.032), "steel", "rail");
boxm(0, set(xa, 0.1, z - 0.02), set(xa + 0.04, 1.12, z + 0.02), "steel", "rail");
boxm(0, set(xb - 0.04, 0.1, z - 0.02), set(xb, 1.12, z + 0.02), "steel", "rail");
for (float x = xa + 0.25; x < xb - 0.1; x += 0.25)
    boxm(0, set(x - 0.012, 0.1, z - 0.012), set(x + 0.012, 1.12, z + 0.012), "steel", "rail");
'''
L1["bal_hw_l1"] = r'''
float sa = -W * 0.5 + rail_w(W), rz = 1.125;
boxm(0, set(sa + 0.02, 1.12, rz - 0.032), set(W * 0.5 - 0.06, 1.165, rz + 0.032), "steel", "rail");
boxm(0, set(sa + 0.3, 0.93, rz - 0.016), set(sa + 0.33, 1.12, rz + 0.016), "steel", "rail");
boxm(0, set(W * 0.5 - 0.33, 0.93, rz - 0.016), set(W * 0.5 - 0.3, 1.12, rz + 0.016), "steel", "rail");
boxm(0, set(W * 0.5 - 0.15, 0, 0.91), set(W * 0.5 - 0.09, H - 0.15, 0.97), "plastic", "pipe");
'''
SASH_L1 = r'''
float x0 = -ow * 0.5, x1 = ow * 0.5;
boxm(0, set(x0, 0, -0.13), set(x1, oh, -0.05), "alu", "frame");
quadm(0, set(x0 + 0.05, oh - 0.05, -0.135), set(x1 - 0.05, oh - 0.05, -0.135), set(x1 - 0.05, 0.08, -0.135), set(x0 + 0.05, 0.08, -0.135), "glass", "own");
'''
L1["sash_l1"] = "float ow = min(3.4, W - 2.6), oh = 2.0;\n" + SASH_L1.replace('boxm(0, set(x0, 0, -0.13), set(x1, oh, -0.05), "alu", "frame");', 'boxm(0, set(x0, 0, -0.06), set(x1, 0.04, -0.04), "alu", "frame"); boxm(0, set(-0.025, 0, -0.1), set(0.025, oh, -0.07), "alu", "frame");')
L1["window_l1"] = "float dx0, dx1, wx0, wx1; bal_openings(W, dx0, dx1, wx0, wx1);\nfloat ow = wx1 - wx0, oh = 1.1;\n" + SASH_L1.replace('boxm(0, set(x0, 0, -0.13), set(x1, oh, -0.05), "alu", "frame");', 'boxm(0, set(x0, -0.02, -0.06), set(x1, 0.0, 0.04), "steel", "frame"); boxm(0, set(-0.025, 0, -0.1), set(0.025, oh, -0.07), "alu", "frame");')
L1["kitchen_win_l1"] = r'''
quadm(0, set(-0.6, 0.9, -0.07), set(0.6, 0.9, -0.07), set(0.6, 0, -0.07), set(-0.6, 0, -0.07), "plastic", "own");
boxm(0, set(-0.65, -0.04, 0.02), set(0.65, 0.0, 0.09), "alu", "frame");
boxm(0, set(-0.65, 0.9, 0.02), set(0.65, 0.94, 0.09), "alu", "frame");
for (float x = -0.6; x <= 0.61; x += 0.3) boxm(0, set(x - 0.01, 0, 0.07), set(x + 0.01, 0.9, 0.09), "alu", "frame");
'''
L1["meter_door_l1"] = r'''
boxm(0, set(-0.39, 0.0, -0.07), set(0.39, 1.8, -0.04), "steel", "door2");
'''
L1["cor_hw_l1"] = r'''
float dx = -W * 0.5 + 0.75;
boxc(0, set(dx + 1.42, 1.15, 0.0), set(dx + 1.78, 1.72, 0.17), "plastic", {0.70, 0.70, 0.68});
'''
SRC.update(L1)
errs = {}
for k in L1:
    e = build_piece(k, [k])
    if e: errs[k] = e
print("l1 errors", errs)
