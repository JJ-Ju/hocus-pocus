"""Agreement of each frame_critique test with the user's round-B picks (review 33).

python docs/redesign/evidence/critique/roundB/agree.py   (from the repo root; caches into ./crit)
"""
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
os.makedirs(OUT, exist_ok=True)
RANK = {"pass": 2, "warn": 1, "fail": 0}

picks = json.load(open(os.path.join(HERE, "picks.json"), encoding="utf-8"))
decisive = [p for p in picks if p["choice"] != "same"]


def crit(key):
    v, n = key.split("/")
    out = os.path.join(OUT, key.replace("/", "_") + ".json")
    if not os.path.exists(out):
        subprocess.run([sys.executable, SCRIPT, os.path.join(EV, DIRS[v], n + ".jpg"), "--json", out],
                       capture_output=True, text=True)
    return json.load(open(out, encoding="utf-8"))


res = {k: crit(k) for k in {p["left"] for p in picks} | {p["right"] for p in picks}}


def loser(p):
    return p["right"] if p["winner"] == p["left"] else p["left"]


for name in sorted(next(iter(res.values()))["tests"]):
    a = d = t = 0
    for p in decisive:
        sw = RANK.get(res[p["winner"]]["tests"][name]["status"])
        sl = RANK.get(res[loser(p)]["tests"][name]["status"])
        if sw is None or sl is None or sw == sl:
            t += 1
        elif sw > sl:
            a += 1
        else:
            d += 1
    rate = "%3.0f%%" % (100.0 * a / (a + d)) if a + d else "   -"
    print("%-18s agree %2d  disagree %2d  tie %2d  %s" % (name, a, d, t, rate))


def score(k):
    s = res[k]["summary"]
    return 2 * len(s["fail"]) + len(s["warn"])


a = sum(score(p["winner"]) < score(loser(p)) for p in decisive)
d = sum(score(p["winner"]) > score(loser(p)) for p in decisive)
print("overall (2 x fails + warns): agree %d  disagree %d  tie %d" % (a, d, len(decisive) - a - d))
