"""Fail when skill text repeats a value that a later rule or measurement replaced.

Each entry names the stale wording, the value that replaced it and where the evidence is. Add an
entry whenever a research round or a rule revision corrects a number the skills state, so the old
number cannot come back through a copied passage.

python scripts/skill_lint.py [repo_root]      exit 1 when anything is found
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS = os.path.join(".claude", "skills")
EXTS = (".md", ".py", ".vfl", ".gdshader", ".hlsl")

# (pattern, what replaced it, evidence). Patterns see one line plus the next, so a phrase broken
# across a line wrap still matches. Mentions that name the old value as old or biased are allowed
# by writing them differently (for example "the older estimate (70–80 % within ±3 %)").
STALE = [
    (r"(p90|percentile spread|local amplitude|local contrast)[^\n]{0,60}\n?[^\n]{0,30}(target\s*\n?\s*)?\b3[–-]6\b",
     "p90/p10 of local grain std: photographed walls run 3-30, median 12.5",
     "docs/redesign/research/rR-reference-photos.md §3.8"),
    (r"\|\s*about 1\.1\s*\|\s*3[–-]6\s*\|",
     "p90/p10 of local grain std: 3-30, median 12.5",
     "docs/redesign/research/rR-reference-photos.md §3.8"),
    (r"70[–-]80 % (of the facade )?within ±3 %(?! within)(?!\))",
     "local-contrast tiers of rule A1 (ordinary walls: median 52 % at 5 % or darker)",
     "danchi rulebook A1 coverage bands"),
    (r"exaggerat\w* (by )?1\.5[–-]3",
     "normal strength x1.0-1.5 at most",
     "docs/redesign/research/rE-concrete.md (Normal and height)"),
    (r"def normal_scale\([^)]*exaggerate=(2|3)(\.\d+)?\)",
     "normal_scale default x1.25 (range 1.0-1.5)",
     "docs/redesign/research/rE-concrete.md (Normal and height)"),
    (r"\|\s*Fresh concrete\s*\|[^|\n]*\|\s*0\.75[–-]0\.95\s*\|",
     "fresh formed skin roughness 0.55-0.7 (weathered 0.75-0.85)",
     "docs/redesign/research/rE-concrete.md (roughness guidance)"),
    (r"half to two thirds of each\s*\n?\s*edge clean",
     "edge wear: 30-60 % clean at light wear, 0-15 % at heavy wear (rule N2)",
     "danchi rulebook N2"),
    (r"No crack starts mid-face",
     "solid walls crack mid-panel from restrained shrinkage, 2.8-3.6 m apart",
     "docs/redesign/research/weathering-structural-damage.md"),
    (r"low = 1 − a·\(1\+w\)",
     "coverage-preserving reveal: low/high = 1 − a ∓ ŵ, ŵ = min(w/2, a, 1 − a)",
     "docs/redesign/research/tiling-and-distribution-algorithms.md §2"),
    (r"rust (runs?|stains?)[^\n.]{0,50}\bfans? out\b",
     "rust runs keep their width or narrow (head 1.6-2.6x the tail)",
     "docs/redesign/research/weathering-rust-water.md §3; rule R5"),
    (r"Moss and lichen\W{0,4} grow only on damp, shaded tops",
     "moss on damp ledges, joints and wall feet; lichen on copings, bare concrete and sunnier faces",
     "docs/redesign/research/weathering-organic-growth.md"),
    (r"[Mm]edian run\s*\n?\s*0\.05[–-]0\.15 m",
     "runs measured as a share of the bar: median 2-30 / 30-75 / 75-100 / 85-100 % at rust 0.25 / 0.5 / 0.6 / 1.0",
     "danchi rulebook 1.8 R8; docs/redesign/research/member-rust-and-geometry-aware-wear.md §1.3"),
    (r"grey steel with an orange haze of\s*\n?\s*flash rust",
     "exposed metal is tarnished: L* 38-48, a* 0 to +4, b* +2 to +8; flash rust only beside new chips",
     "danchi rulebook 1.8 R7; docs/redesign/research/member-rust-and-geometry-aware-wear.md §1.5"),
]


def scan(root=ROOT):
    """Return [(path, line, stale text, replacement, evidence)]."""
    pats = [(re.compile(p, re.I), fix, src) for p, fix, src in STALE]
    out = []
    base = os.path.join(root, SKILLS)
    for dp, dn, fn in os.walk(base):
        dn[:] = [d for d in dn if d not in ("__pycache__", "worktrees")]
        for f in fn:
            if not f.endswith(EXTS):
                continue
            p = os.path.join(dp, f)
            try:
                lines = open(p, encoding="utf-8").read().split("\n")
            except UnicodeDecodeError:
                continue
            seen = set()
            for i in range(len(lines)):
                win = lines[i] + ("\n" + lines[i + 1] if i + 1 < len(lines) else "")
                for rx, fix, src in pats:
                    m = rx.search(win)
                    if m and m.start() <= len(lines[i]) and (rx.pattern, i) not in seen:
                        seen.add((rx.pattern, i))
                        if (rx.pattern, i - 1) in seen:
                            continue                       # the same match seen from the line above
                        out.append((os.path.relpath(p, root), i + 1, m.group(0).replace("\n", " "), fix, src))
    return out


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    root = sys.argv[1] if len(sys.argv) > 1 else ROOT
    hits = scan(root)
    for path, line, txt, fix, src in hits:
        print("%s:%d: stale %r -> %s (%s)" % (path, line, txt.strip(), fix, src))
    print("%d stale value(s)" % len(hits))
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
