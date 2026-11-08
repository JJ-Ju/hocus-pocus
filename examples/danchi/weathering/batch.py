"""batch.py: run builds N at a time and gate each one (Python waits on its children; the shell's
wait returned early under the tool runner).

    python -I batch.py <jobs.json> [N]

jobs.json is a list of {"out": "real/NAME", "args": [preset, ...run_real args], "sweep": bool}.
Each build writes real/NAME.log, then the gate writes real/NAME.gate.txt and real/NAME/gate.json.
Prints one line per job when it finishes."""
import json
import os
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable


def run(job, lock):
    out = job["out"]
    t0 = time.time()
    if os.path.isdir(os.path.join(HERE, out)):
        import shutil
        shutil.rmtree(os.path.join(HERE, out))
    with open(os.path.join(HERE, out + ".log"), "w") as lf:
        rc = subprocess.call([PY, "-I", "run_real.py", out] + job["args"], cwd=HERE, stdout=lf, stderr=subprocess.STDOUT)
    line = ""
    if rc == 0:
        g = [PY, "-I", os.path.join("..", "..", "..", "scripts", "weathering", "weather_gate.py"), "check", out, "--json", os.path.join(out, "gate.json")]
        if job.get("sweep"):
            g.insert(5, "--sweep")
        with open(os.path.join(HERE, out + ".gate.txt"), "w") as gf:
            subprocess.call(g, cwd=HERE, stdout=gf, stderr=subprocess.STDOUT)
        try:
            line = open(os.path.join(HERE, out + ".gate.txt"), encoding="utf-8", errors="replace").read().strip().splitlines()[-1]
        except Exception as e:  # noqa: BLE001
            line = "gate output missing: %s" % e
    else:
        tail = open(os.path.join(HERE, out + ".log"), encoding="utf-8", errors="replace").read()[-400:]
        line = "BUILD FAILED rc=%d: %s" % (rc, tail.replace("\n", " | "))
    with lock:
        print("%s (%.0f s): %s" % (out, time.time() - t0, line), flush=True)


def main():
    jobs = json.load(open(sys.argv[1], encoding="utf-8"))
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    lock = threading.Lock()
    pending = list(jobs)
    active = []
    while pending or active:
        active = [t for t in active if t.is_alive()]
        while pending and len(active) < n:
            t = threading.Thread(target=run, args=(pending.pop(0), lock))
            t.start()
            active.append(t)
        time.sleep(2)
    print("batch done", flush=True)


if __name__ == "__main__":
    main()
