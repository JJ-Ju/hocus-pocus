"""run_critique.py — frame_critique.py over the showcase, with --view and the matching --ref photos.

    python -I run_critique.py <repo> [jobs]

Bay-camera images: --view close --ref bay_*; facade and sweep cameras: --view wide --ref
facade_* end_* (a facade with its end wall, 20-60 m). Writes showcase/critique.json: per image
the binding tests' status and value, and a summary of fails and warns.
"""
import glob
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

repo = sys.argv[1]
jobs = int(sys.argv[2]) if len(sys.argv) > 2 else 6
sd = os.path.join(repo, "examples", "danchi", "showcase")
fc = os.path.join(repo, ".claude", "skills", "procedural-assets", "scripts", "frame_critique.py")
refs = os.path.join(repo, "docs", "redesign", "evidence", "refs", "img")
man = json.load(open(os.path.join(sd, "manifest.json")))
tmp = os.path.join(sd, "raw", "critique")
os.makedirs(tmp, exist_ok=True)


def run(img):
    f = img["file"]
    if img["camera"] == "bay":
        view, ref = "close", sorted(glob.glob(os.path.join(refs, "bay_*.jpg")))
    else:
        view, ref = "wide", sorted(glob.glob(os.path.join(refs, "facade_*.jpg")) + glob.glob(os.path.join(refs, "end_*.jpg")))
    js = os.path.join(tmp, f.replace(".jpg", ".json"))
    img_path = os.path.join(sd, f)
    # reuse a result newer than its image (a re-run after adding shots only critiques the new ones)
    if not (os.path.exists(js) and os.path.getmtime(js) > os.path.getmtime(img_path)):
        cmd = [sys.executable, "-I", fc, img_path, "--view", view, "--json", js, "--ref"] + ref
        subprocess.run(cmd, capture_output=True, text=True)
    d = json.load(open(js))
    tests = d.get("tests", d.get("results", []))
    if isinstance(tests, dict):
        tests = [dict(name=k, **v) if isinstance(v, dict) else {"name": k} for k, v in tests.items()]
    out = {}
    for t in tests:
        out[t.get("name") or t.get("test")] = {"status": t.get("status"), "value": t.get("value")}
    return f, view, out


with ThreadPoolExecutor(jobs) as ex:
    res = list(ex.map(run, man["images"]))
summary = {"fails": {}, "warns": {}}
per = {}
for f, view, out in res:
    per[f] = {"view": view, "tests": out}
    for k, v in out.items():
        if v["status"] in ("fail", "FAIL"):
            summary["fails"].setdefault(k, []).append(f)
        if v["status"] in ("warn", "WARN"):
            summary["warns"].setdefault(k, []).append(f)
json.dump({"summary": summary, "images": per}, open(os.path.join(sd, "critique.json"), "w"), indent=1)
print(json.dumps(summary, indent=1))
for f, view, out in res:
    vr = out.get("value_range", {})
    rm = out.get("reference_match", {})
    print(f, view, "value_range", vr.get("status"), vr.get("value"), "reference_match", rm.get("status"), rm.get("value"))
