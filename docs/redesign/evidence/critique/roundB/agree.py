"""Agreement of each frame_critique test with the user's round-B picks (review 33, round R).

python docs/redesign/evidence/critique/roundB/agree.py [--refs DIR] [--no-refs] [--cache DIR]

From the repo root. Results are cached in ./crit, keyed by image, view and reference set, and
recomputed when the tool version changes.

Each pick group is run with its view (--view) and, when the reference photos are present, with
--ref set to the photos of the matching category. The photos come from
docs/redesign/evidence/refs/fetch_refs.py; the default DIR is docs/redesign/evidence/refs/img/.
Without photos, reference_match reports na.

These numbers are in-sample. The thresholds were fitted to these same 23 decisive pairs and one
viewer's taste, so they overstate how the critique will do on new renders.
"""
import argparse
import glob
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", "..", "..", ".."))
EV = os.path.join(REPO, "docs", "redesign", "evidence")
DIRS = {"v1": "danchi", "v2": "danchi-v2", "v3": "danchi-v3", "v4": "danchi-v4", "v5": "danchi-v5"}
SCRIPT = os.path.join(REPO, ".claude", "skills", "procedural-assets", "scripts", "frame_critique.py")
OUT = os.path.join(HERE, "crit")
RANK = {"pass": 2, "warn": 1, "fail": 0}
# pick group -> (--view, reference photo categories)
GROUPS = {"bay": ("close", ["bay"]), "close": ("close", ["bay", "weathering"]),
          "corr": ("corridor", ["bay"]), "end": ("wide", ["end"]), "facade": ("wide", ["facade"]),
          "seeds": ("sheet", ["estate"]), "street": ("street", ["street"])}

ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
ap.add_argument("--refs", default=os.path.join(EV, "refs", "img"),
                help="folder with the reference photos (file names start with the category)")
ap.add_argument("--no-refs", action="store_true", help="run without --ref")
ap.add_argument("--cache", default=OUT, help="folder for the per-image JSON results (default ./crit)")
a = ap.parse_args()
OUT = a.cache
os.makedirs(OUT, exist_ok=True)


def tool_version():
    with open(SCRIPT, encoding="utf-8") as f:
        for line in f:
            if line.startswith("VERSION"):
                return line.split("=", 1)[1].strip().strip('"')
    return "?"


VERSION = tool_version()
photos = {} if a.no_refs else {
    os.path.basename(p): p for p in sorted(glob.glob(os.path.join(a.refs, "*.jpg")))}


def refs_for(cats):
    return [p for n, p in photos.items() if n.split("_")[0] in cats]


picks = json.load(open(os.path.join(HERE, "picks.json"), encoding="utf-8"))
decisive = [p for p in picks if p["choice"] != "same"]


def crit(key, group):
    view, cats = GROUPS[group]
    refs = refs_for(cats)
    v, n = key.split("/")
    tag = "%s_%s_%s" % (key.replace("/", "_"), view, "+".join(cats) if refs else "noref")
    out = os.path.join(OUT, tag + ".json")
    if os.path.exists(out):
        with open(out, encoding="utf-8") as f:
            j = json.load(f)
        if j.get("tool_version") == VERSION:
            return j
    cmd = [sys.executable, "-I", SCRIPT, os.path.join(EV, DIRS[v], n + ".jpg"), "--view", view,
           "--json", out]
    if refs:
        cmd += ["--ref"] + refs
    subprocess.run(cmd, capture_output=True, text=True)
    with open(out, encoding="utf-8") as f:
        return json.load(f)


def group(p):
    return p["pair"].split("-")[0]


def loser(p):
    return p["right"] if p["winner"] == p["left"] else p["left"]


res = {}
for p in picks:
    for k in (p["left"], p["right"]):
        res[(k, group(p))] = crit(k, group(p))

print("tool %s; reference photos: %d in %s" % (VERSION, len(photos),
                                                a.refs if photos else "(none)"))
names = sorted(next(iter(res.values()))["tests"])
rows = {}
for name in names:
    ag = d = t = 0
    for p in decisive:
        g = group(p)
        sw = RANK.get(res[(p["winner"], g)]["tests"][name]["status"])
        sl = RANK.get(res[(loser(p), g)]["tests"][name]["status"])
        if sw is None or sl is None or sw == sl:
            t += 1
        elif sw > sl:
            ag += 1
        else:
            d += 1
    rate = "%3.0f%%" % (100.0 * ag / (ag + d)) if ag + d else "   -"
    print("%-18s agree %2d  disagree %2d  tie %2d  %s" % (name, ag, d, t, rate))


def score(k, g):
    s = res[(k, g)]["summary"]
    return 2 * len(s["fail"]) + len(s["warn"])


ag = sum(score(p["winner"], group(p)) < score(loser(p), group(p)) for p in decisive)
d = sum(score(p["winner"], group(p)) > score(loser(p), group(p)) for p in decisive)
print("overall (2 x fails + warns): agree %d  disagree %d  tie %d" % (ag, d, len(decisive) - ag - d))
print("(in-sample: fitted to these picks)")
