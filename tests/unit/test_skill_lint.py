"""The skills must not repeat values that later rules or measurements replaced (scripts/skill_lint.py)."""
import importlib.util
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _lint():
    spec = importlib.util.spec_from_file_location("skill_lint", os.path.join(ROOT, "scripts", "skill_lint.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_no_stale_values_in_skills():
    hits = _lint().scan(ROOT)
    assert not hits, "\n".join("%s:%d: %s -> %s" % (p, n, t, fix) for p, n, t, fix, _ in hits)


def test_lint_catches_an_old_value(tmp_path):
    d = tmp_path / ".claude" / "skills" / "x"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("Check it with statistics: about 70–80 % of the facade within ±3 % of the base.\n",
                                encoding="utf-8")
    hits = _lint().scan(str(tmp_path))
    assert len(hits) == 1 and hits[0][1] == 1
