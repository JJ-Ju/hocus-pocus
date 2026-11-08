"""Round-G pipeline: the presets, then the six control sweeps at Typical's solved gains, then the
series rules over the accepted steps and the page spec. Every build is gated as it finishes.

    python -I pipeline_g.py <tag> [N] [--sweeps-only]

Writes real/<tag>_spec.json for build_pickG.py and real/<tag>_pipeline.txt (a line per build)."""
import json
import os
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import batch  # noqa: E402

PY = sys.executable
VALS = ["0", "0.25", "0.5", "0.75", "1.0"]
SWEEPS = [("streaks", "streaks", VALS), ("damage", "damage", VALS), ("grime", "soiling", ["0.1", "0.2", "0.3", "0.4", "0.5", "0.6"]),
          ("stain_fields", "stains", VALS), ("growth", "bio", VALS), ("edges", "wear", VALS)]
PRESETS = [("typical_s1", ["typical", "--seed", "1"]), ("typical_s2", ["typical", "--seed", "2"]), ("kept", ["kept"]),
           ("worn", ["worn"]), ("neglected", ["neglected"]), ("new", ["new"]), ("typical_s3", ["typical", "--seed", "3"])]


def run_jobs(jobs, n):
    lock = threading.Lock()
    pending, active = list(jobs), []
    while pending or active:
        active = [t for t in active if t.is_alive()]
        while pending and len(active) < n:
            t = threading.Thread(target=batch.run, args=(pending.pop(0), lock))
            t.start()
            active.append(t)
        time.sleep(2)


def accepted(d):
    try:
        g = json.load(open(os.path.join(HERE, d, "gate.json"), encoding="utf-8"))
        return g["summary"]["accepted"], g["summary"]["fail"] + g["summary"]["na"]
    except Exception as e:  # noqa: BLE001
        return False, ["no gate: %s" % e]


def main():
    tag = sys.argv[1]
    n = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 4
    sweeps_only = "--sweeps-only" in sys.argv
    if not sweeps_only:
        run_jobs([{"out": "real/R%s_%s" % (tag, k), "args": a} for k, a in PRESETS], n)
    m = json.load(open(os.path.join(HERE, "real/R%s_typical_s1" % tag, "meta.json"), encoding="utf-8"))
    g = m["gains"]
    gains = "%.4f,%.4f,%.4f" % (g["soiling"], g["accent"], g["film_k"])
    print("Typical gains", gains, flush=True)
    jobs = []
    for key, layer, vals in SWEEPS:
        for v in vals:
            jobs.append({"out": "real/S%s_%s_%s" % (tag, key, v), "args": ["typical", "--override", "%s=%s" % (layer, v), "--gains", gains],
                         "sweep": True})
    run_jobs(jobs, n)
    pres = ["real/R%s_%s" % (tag, k) for k in ("new", "kept", "typical_s1", "worn", "neglected")]
    ser = "real/%s_presets_series.json" % tag
    r = subprocess.run([PY, "-I", os.path.join("..", "..", "..", "scripts", "weathering", "weather_gate.py"), "series", "presets"] + pres + ["--json", ser], cwd=HERE, capture_output=True, text=True)
    print("presets series:", (r.stdout.strip().splitlines() or ["?"])[-1], flush=True)
    spec = {"tag": tag, "gains": gains, "presets": {k: "real/R%s_%s" % (tag, k2) for k, k2 in
                                                     (("new", "new"), ("kept", "kept"), ("typical", "typical_s1"), ("worn", "worn"), ("neglected", "neglected"))},
            "presets_series": ser, "seeds": ["real/R%s_typical_s%d" % (tag, i) for i in (1, 2, 3)], "sweeps": {}, "rejected": {}}
    for k, d in list(spec["presets"].items()) + [("seed%d" % i, s) for i, s in enumerate(spec["seeds"], 1)]:
        ok, f = accepted(d)
        if not ok:
            spec["rejected"][k] = f
    for key, layer, vals in SWEEPS:
        ok_dirs, ok_vals, bad = [], [], []
        for v in vals:
            d = "real/S%s_%s_%s" % (tag, key, v)
            ok, f = accepted(d)
            (ok_dirs.append(d), ok_vals.append(float(v))) if ok else bad.append((v, f))
        sser = "real/S%s_%s_series.json" % (tag, key)
        r = subprocess.run([PY, "-I", os.path.join("..", "..", "..", "scripts", "weathering", "weather_gate.py"), "series", "sweep:" + layer] + ok_dirs + ["--json", sser],
                           cwd=HERE, capture_output=True, text=True)
        line = (r.stdout.strip().splitlines() or ["?"])[-1]
        print("%s steps %s rejected %s series: %s" % (key, ok_vals, bad, line), flush=True)
        spec["sweeps"][key] = {"layer": layer, "values": ok_vals, "dirs": ok_dirs, "series": sser, "rejected_steps": bad}
    json.dump(spec, open(os.path.join(HERE, "real/%s_spec.json" % tag), "w"), indent=1)
    print("wrote real/%s_spec.json" % tag, flush=True)


if __name__ == "__main__":
    main()
