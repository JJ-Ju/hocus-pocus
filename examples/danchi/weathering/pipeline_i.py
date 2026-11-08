"""Round-I pipeline: the presets (New, Kept, Typical, Worn, Derelict), then the rust, streak and
growth sweeps at Typical's solved gains, then the series rules over the accepted steps and the page
spec. Every build is gated as it finishes. The generator is in scripts/weathering.

    python -I pipeline_i.py <tag> [N] [--sweeps-only] [--presets-only]

Seeds are not rebuilt this round (round H: "same state"). Edges, stain fields and grime keep round H's
picks (they match Typical's amounts). Writes real/<tag>_spec.json; a line per build on stdout."""
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
SWEEPS = [("rust", "rust", VALS), ("streaks", "streaks", VALS), ("growth", "bio", VALS)]
ORDER = ("new", "kept", "typical", "worn", "derelict")


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


def series(kind, dirs, out):
    r = subprocess.run([PY, "-I", os.path.join("..", "..", "..", "scripts", "weathering", "weather_gate.py"), "series", kind] + dirs + ["--json", out], cwd=HERE,
                       capture_output=True, text=True)
    return (r.stdout.strip().splitlines() or ["?"])[-1]


def main():
    tag = sys.argv[1]
    n = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 4
    sweeps_only, presets_only = "--sweeps-only" in sys.argv, "--presets-only" in sys.argv
    R = lambda k: "real/R%s_%s" % (tag, k)  # noqa: E731
    if not sweeps_only:
        first = [{"out": R("typical"), "args": ["typical", "--seed", "1"]}, {"out": R("kept"), "args": ["kept"]},
                 {"out": R("worn"), "args": ["worn"]}, {"out": R("derelict"), "args": ["derelict"]},
                 {"out": R("new"), "args": ["new"]}]
        run_jobs(first, n)
    spec = {"tag": tag, "presets": {k: R(k) for k in ORDER}, "sweeps": {}, "rejected": {}}
    ser = "real/%s_presets_series.json" % tag
    print("presets series:", series("presets", [spec["presets"][k] for k in ORDER], ser), flush=True)
    spec["presets_series"] = ser
    for k, d in spec["presets"].items():
        ok, f = accepted(d)
        if not ok:
            spec["rejected"][k] = f
    json.dump(spec, open(os.path.join(HERE, "real/%s_spec.json" % tag), "w"), indent=1)
    if presets_only:
        return
    m = json.load(open(os.path.join(HERE, R("typical"), "meta.json"), encoding="utf-8"))
    g = m["gains"]
    gains = "%.4f,%.4f,%.4f" % (g["soiling"], g["accent"], g["film_k"])
    spec["gains"] = gains
    print("Typical gains", gains, flush=True)
    jobs = []
    for key, layer, vals in SWEEPS:
        for v in vals:
            jobs.append({"out": "real/S%s_%s_%s" % (tag, key, v), "args": ["typical", "--override", "%s=%s" % (layer, v), "--gains", gains],
                         "sweep": True})
    run_jobs(jobs, n)
    for key, layer, vals in SWEEPS:
        ok_dirs, ok_vals, bad = [], [], []
        for v in vals:
            d = "real/S%s_%s_%s" % (tag, key, v)
            ok, f = accepted(d)
            (ok_dirs.append(d), ok_vals.append(float(v))) if ok else bad.append((v, f))
        sj = "real/S%s_%s_series.json" % (tag, key)
        print("%s steps %s rejected %s series: %s" % (key, ok_vals, bad, series("sweep:" + layer, ok_dirs, sj)), flush=True)
        spec["sweeps"][key] = {"layer": layer, "values": ok_vals, "dirs": ok_dirs, "series": sj, "rejected_steps": bad}
    json.dump(spec, open(os.path.join(HERE, "real/%s_spec.json" % tag), "w"), indent=1)
    print("wrote real/%s_spec.json" % tag, flush=True)


if __name__ == "__main__":
    main()
