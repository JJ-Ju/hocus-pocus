"""rules_to_md.py - render weather_rules.json as the skill's reference page (weathering-rules.md).
python -I rules_to_md.py <weather_rules.json> <out.md>"""
import json
import os
import sys

R = json.load(open(sys.argv[1], encoding="utf-8"))


def _check_paths(R, start):
    """Round J (audit rank 28): every cited docs/... path must exist in the repo. Skipped when the
    rulebook is not inside a repo (no docs/redesign/research above it)."""
    import re
    d = os.path.dirname(os.path.abspath(start))
    for _ in range(6):
        if os.path.isdir(os.path.join(d, "docs", "redesign", "research")):
            break
        d = os.path.dirname(d)
    else:
        return
    txt = json.dumps(R, ensure_ascii=False)
    missing = sorted({m for m in re.findall(r"docs/[A-Za-z0-9_./-]+\.md", txt) if not os.path.exists(os.path.join(d, m))})
    if missing:
        raise SystemExit("rules cite paths that do not exist: %s" % ", ".join(missing))


_check_paths(R, sys.argv[1])
D = R["definitions"]
L = []
w = L.append
w("# Weathering rules")
w("")
w("Numeric rules for building weathering, checked by `scripts/weathering/weather_gate.py`. A weathered "
  "building is accepted only when every binding rule passes; nothing is shown before that. Version: %s." % R["version"])
w("")
w(R["about"])
w("")
w("## Measures")
w("")
w("- **D**: %s" % D["D"])
w("- **D_local**: %s" % D["D_local"])
t = D["tiers"]
w("- **Opacity tiers** (lower bounds of D or D_local): " + ", ".join("%s >= %.2f" % (n, e) for n, e in zip(t["names"], t["edges"])) + ". " + t["note"])
lv = D["levels"]
w("- **Scale levels**: " + ", ".join("%s %g-%g m" % (n, a, b) for n, (a, b) in zip(lv["names"], lv["metres"])) +
  ". Groups: macro S1-S3, mid S4-S5, micro S6-S8. " + lv["below"])
c = D["clock"]
w("- **Soiling clock E**: repaint cycle %s years; years since repaint %s; E = %s. %s" % (
    c["repaint_cycle_years"], c["years_since_repaint"], c["soiling_clock_E"], c["note"]))
w("- **Planes**: %s" % D["planes"])
w("- **Layers**: %s" % ", ".join(D["layers"]))
w("")
w("## Presets")
w("")
w("| Preset | Age | Upkeep | E | Anchor |")
w("|---|---|---|---|---|")
for k, p in R["presets"].items():
    w("| %s | %g | %g | %g | %s |" % (p["label"], p["age"], p["upkeep"], p["E"], p.get("anchor", "")))
w("")
w("## Amount tables")
w("")
tone = R["tone"]
w("Tone (A0), mean D on the exposed painted walls, by E: " + "; ".join("E %g: %.2f-%.2f" % (e, a, b) for e, (a, b) in zip(tone["E"], tone["mean_D"])) + ".")
w("")
cov = R["coverage"]
w("Coverage (A1), share of the exposed painted wall at or above each tier of D_local, by E:")
w("")
w("| Tier | " + " | ".join("E %g" % e for e in cov["E"]) + " |")
w("|---|" + "---|" * len(cov["E"]))
for tier in ("T2+", "T3+", "T4+", "T5+", "T6+"):
    w("| %s | " % tier + " | ".join("%.3g-%.3g" % (a, b) for a, b in cov[tier]) + " |")
w("")
w(cov["about"])
w("")
w("## Rules")
w("")
w("Origins: U the user's review notes, P measured on the reference photos, L building physics and the "
  "soiling literature, C a craft estimate (recalibrate with picks).")
fam = None
for r in R["rules"]:
    if r["family"] != fam:
        fam = r["family"]
        w("")
        w("### %s" % fam.capitalize())
        w("")
    w("**%s. %s**%s" % (r["id"], r["title"], "" if r.get("binding", True) else " (advisory)"))
    w("")
    w("- Measure: %s" % r["measure"])
    w("- Pass: %s" % r["pass"])
    w("- Origin: %s" % r["origin"])
    w("")
w("## Revisions")
w("")
w("Each change to a rule after it was first written, with the evidence for it.")
w("")
for v in R.get("revisions", []):
    w("- **%s**: %s. %s" % (v["rule"], v["change"], v["why"][0].upper() + v["why"][1:] + ("" if v["why"].endswith(".") else ".")))
w("")
w("## Running the gate")
w("")
w("```")
w("python -I weather_gate.py check <config_dir> [--json out.json] [--sweep] [--allow-na]")
w("python -I weather_gate.py series presets <dir_new> <dir_kept> <dir_typical> <dir_worn> <dir_neglected>")
w("python -I weather_gate.py series sweep:<layer> <dir_0> <dir_0.25> <dir_0.5> <dir_0.75> <dir_1>")
w("```")
w("")
w("A config folder holds one `<plane>.npz` per facade plane in facade space (row 0 at the top, 50 px/m) "
  "with `D`, the `L_<layer>` maps, `cls`, `src`, `edge`, optional `Yc`, `labw`/`labc`, the damage chip list "
  "(`dmg_y`, `dmg_x`, `dmg_r`, `dmg_d`), and a `meta.json` with the config (preset, age, upkeep, E, amounts) "
  "and each plane's frame (ppm, orient, kind, ground and top rows, storey rows, bay columns and kinds). Exit "
  "code 0 only when accepted. `--sweep` judges one step of a control sweep: the amount budgets A0, A1 and B1 "
  "are set by the control there, so they are not applied.")
open(sys.argv[2], "w", encoding="utf-8", newline="\n").write("\n".join(L) + "\n")
print("wrote", sys.argv[2], len(L), "lines")
