"""Round-K pipeline (pipeline_j's, with the round-K generator in scripts/weathering): the presets (New, Kept, Typical, Worn, Derelict)
and the rust sweep at Typical's solved gains, which starts as soon as Typical is built instead of after every preset.
Every build is gated as it finishes and its texture checks run; a build is accepted only when both pass. Then the
series rules over the accepted steps and the page spec.

    python -I pipeline_k.py <tag> [N]     N builds at once (default 3; real/<tag>_slots.txt, if present, overrides it live)

Writes real/<tag>_spec.json; a line per build on stdout."""
import json
import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import batch_j as batch  # noqa: E402
import pipeline_j as pj  # noqa: E402

VALS = ["0", "0.25", "0.5", "0.75", "1.0"]


def main():
    tag = sys.argv[1]
    n0 = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    slots = os.path.join(HERE, "real", "%s_slots.txt" % tag)
    R = lambda k: "real/R%s_%s" % (tag, k)  # noqa: E731
    S = lambda v: "real/S%s_rust_%s" % (tag, v)  # noqa: E731
    pending = [{"out": R("typical"), "args": ["typical", "--seed", "1"]}, {"out": R("derelict"), "args": ["derelict"]},
               {"out": R("worn"), "args": ["worn"]}, {"out": R("kept"), "args": ["kept"]}, {"out": R("new"), "args": ["new"]}]
    lock = threading.Lock()
    active, sweeps_added, gains = [], False, None
    t0 = time.time()
    while pending or active:
        active = [(t, j) for t, j in active if t.is_alive()]
        m = None
        if not sweeps_added and not any(j["out"] == R("typical") for j in pending):
            try:                                  # Typical's meta is written once its gains are solved and its planes saved
                m = json.load(open(os.path.join(HERE, R("typical"), "meta.json"), encoding="utf-8"))
            except (OSError, ValueError):
                m = None
        if m is not None and "gains" in m:
            g = m["gains"]
            gains = "%.4f,%.4f,%.4f" % (g["soiling"], g["accent"], g["film_k"])
            with lock:
                print("Typical gains %s (%.0f s): the rust sweep joins the queue" % (gains, time.time() - t0), flush=True)
            pending += [{"out": S(v), "args": ["typical", "--override", "rust=%s" % v, "--gains", gains], "sweep": True}
                        for v in VALS]
            sweeps_added = True
        try:
            n = int(open(slots).read().strip()) if os.path.exists(slots) else n0
        except ValueError:
            n = n0
        while pending and len(active) < n:
            j = pending.pop(0)
            t = threading.Thread(target=batch.run, args=(j, lock))
            t.start()
            active.append((t, j))
        time.sleep(3)
    spec = {"tag": tag, "presets": {k: R(k) for k in pj.ORDER}, "sweeps": {}, "rejected": {}, "gains": gains}
    ser = "real/%s_presets_series.json" % tag
    print("presets series:", pj.series("presets", [spec["presets"][k] for k in pj.ORDER], ser), flush=True)
    spec["presets_series"] = ser
    for k, d in spec["presets"].items():
        ok, f = pj.accepted(d)
        if not ok:
            spec["rejected"][k] = f
    ok_dirs, ok_vals, bad = [], [], []
    for v in VALS:
        ok, f = pj.accepted(S(v))
        (ok_dirs.append(S(v)), ok_vals.append(float(v))) if ok else bad.append((v, f))
    sj = "real/S%s_rust_series.json" % tag
    print("rust steps %s rejected %s series: %s" % (ok_vals, bad, pj.series("sweep:rust", ok_dirs, sj)), flush=True)
    spec["sweeps"]["rust"] = {"layer": "rust", "values": ok_vals, "dirs": ok_dirs, "series": sj, "rejected_steps": bad}
    json.dump(spec, open(os.path.join(HERE, "real/%s_spec.json" % tag), "w"), indent=1)
    print("wrote real/%s_spec.json (%.0f s)" % (tag, time.time() - t0), flush=True)


if __name__ == "__main__":
    main()
