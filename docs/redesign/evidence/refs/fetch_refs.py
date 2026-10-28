"""Download the reference photos listed in manifest.json (stdlib only).

python docs/redesign/evidence/refs/fetch_refs.py [OUT_DIR]     (default: docs/redesign/evidence/refs/img/)

Files already present with the right SHA-256 are skipped. Wikimedia asks for a descriptive
User-Agent and a modest request rate, so requests are sequential with a short pause.
The images are freely licensed but not ours: see README.md for authors and licences.
"""
import hashlib
import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
UA = ("HocusPocusRefSet/0.1 (reference photos for a render critique tool; "
      "https://github.com/JJ-Ju/hocus-pocus) python-urllib")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def main(argv):
    out = os.path.abspath(argv[1]) if len(argv) > 1 else os.path.join(HERE, "img")
    os.makedirs(out, exist_ok=True)
    with open(os.path.join(HERE, "manifest.json"), encoding="utf-8") as f:
        photos = json.load(f)["photos"]
    bad = 0
    for p in photos:
        name = os.path.basename(p["file"])  # never write outside OUT_DIR
        path = os.path.join(out, name)
        if os.path.exists(path):
            with open(path, "rb") as f:
                if sha256(f.read()) == p.get("sha256"):
                    print("ok      ", name)
                    continue
        data = None
        for attempt in range(4):
            try:
                req = urllib.request.Request(p["download_url"], headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=120) as r:
                    data = r.read()
                break
            except Exception as e:  # network errors, 429 rate limits
                print("retry   ", name, e)
                time.sleep(5 * (attempt + 1))
        if data is None:
            print("FAILED  ", name)
            bad += 1
            continue
        if p.get("sha256") and sha256(data) != p["sha256"]:
            # Commons can re-render a thumbnail; keep it, but say so
            print("changed ", name, "(sha256 differs from manifest)")
        else:
            print("fetched ", name, len(data))
        with open(path, "wb") as f:
            f.write(data)
        time.sleep(1.0)
    print("%d of %d photos in %s" % (len(photos) - bad, len(photos), out))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
