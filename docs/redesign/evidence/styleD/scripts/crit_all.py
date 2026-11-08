"""crit_all.py - round D: frame_critique.py (unchanged) on every picker image, both profiles,
plus a compact table of the tests that matter for the painterly layers.

  python -I crit_all.py <picker_dir> <crit_dir>
Run with a Python that has numpy and Pillow (not Houdini's python313, whose PIL fails).
"""
import glob
import json
import os
import subprocess
import sys

FC = r"C:/Users/jujun/DEV/hocus-pocus/.claude/skills/procedural-assets/scripts/frame_critique.py"
KEYS = ("value_grouping", "painted_key", "micro_uniformity", "saturation_budget", "detail_density",
        "value_range", "palette")


def tests(d, out):
    if isinstance(d, dict):
        if "test" in d and "status" in d:
            out[d["test"]] = d
        for v in d.values():
            tests(v, out)
    elif isinstance(d, list):
        for v in d:
            tests(v, out)
    return out


def main():
    pdir, cdir = sys.argv[1], sys.argv[2]
    os.makedirs(cdir, exist_ok=True)
    rows = []
    for f in sorted(glob.glob(os.path.join(pdir, "*.jpg"))):
        b = os.path.splitext(os.path.basename(f))[0]
        if "z_" in b.split("_")[0] + "_" or "_piece_" in b:
            continue  # crops and the bake check are not frames
        row = {"image": b}
        for prof in ("realistic", "painterly"):
            js = os.path.join(cdir, "%s_%s.json" % (b, prof))
            if not os.path.exists(js):
                with open(os.path.join(cdir, "%s_%s.txt" % (b, prof)), "w") as fh:
                    subprocess.run([sys.executable, "-I", FC, f, "--profile", prof, "--json", js],
                                   stdout=fh, stderr=subprocess.STDOUT, cwd=cdir)
            t = tests(json.load(open(js)), {})
            for k in KEYS:
                if k in t:
                    row["%s.%s" % (prof[0], k)] = (t[k]["status"], t[k].get("value"))
            if prof == "painterly" and "painted_key" in t:
                m = t["painted_key"].get("metrics", {})
                row["pk_metrics"] = {k: m[k] for k in list(m)[:8]}
            if prof == "painterly" and "micro_uniformity" in t:
                row["micro_mean_local_std"] = t["micro_uniformity"]["metrics"].get("mean_local_std")
            if prof == "painterly" and "palette" in t:
                row["palette_explain"] = t["palette"].get("explain")
        rows.append(row)
    json.dump(rows, open(os.path.join(cdir, "summary.json"), "w"), indent=1)
    for r in rows:
        print(r["image"], "|", r.get("p.value_grouping"), "|", r.get("p.painted_key"), "|",
              r.get("pk_metrics"), "| micro", r.get("micro_mean_local_std"), "|", r.get("p.saturation_budget"),
              "|", r.get("p.detail_density"), "|", r.get("palette_explain"))


if __name__ == "__main__":
    main()
