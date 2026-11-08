"""research_actions.py - list the open rows of the research notes' action tables.

Every note in docs/redesign/research/ ends in an action table (notes written before round J have
theirs in that folder's README.md). An action table is any Markdown table whose header has a
"Status" column. A row's status is one of:
  open                      not yet a check, rule, step or skill section that runs
  done (<commit or file>)   applied: a check or rule with a number, run by the pipeline, on what ships
  parked (<reason>; revisit when <trigger>)
A round closes only when this script reports no open row (exit code 0).

    python -I scripts/research_actions.py [--all]
"""
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "redesign", "research")


def tables(text):
    """Yield (header cells, [row cells]) for each Markdown table."""
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        if lines[i].lstrip().startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[i + 1]):
            head = [c.strip() for c in lines[i].strip().strip("|").split("|")]
            rows = []
            j = i + 2
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                rows.append([c.strip() for c in lines[j].strip().strip("|").split("|")])
                j += 1
            yield head, rows, i + 1
            i = j
        else:
            i += 1


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    show_all = "--all" in sys.argv
    n_open = n_rows = 0
    bad = []
    for fn in sorted(os.listdir(ROOT)):
        if not fn.endswith(".md"):
            continue
        text = open(os.path.join(ROOT, fn), encoding="utf-8").read()
        for head, rows, line in tables(text):
            low = [h.lower() for h in head]
            if "status" not in low:
                continue
            k = low.index("status")
            idk = low.index("id") if "id" in low else 0
            for r in rows:
                if len(r) <= k:
                    continue
                st = r[k].lower()
                n_rows += 1
                if st.startswith("open"):
                    n_open += 1
                    print("OPEN  %s:%d  %s  %s" % (fn, line, r[idk], r[1][:110] if len(r) > 1 else ""))
                elif not (st.startswith("done") or st.startswith("parked")):
                    bad.append("%s:%d %s: status %r" % (fn, line, r[idk], r[k]))
                elif show_all:
                    print("%-6s %s:%d  %s" % (st.split()[0].upper(), fn, line, r[idk]))
    for b in bad:
        print("BAD   " + b)
    print("%d action rows, %d open, %d with an unknown status" % (n_rows, n_open, len(bad)))
    sys.exit(0 if n_open == 0 and not bad else 1)


if __name__ == "__main__":
    main()
