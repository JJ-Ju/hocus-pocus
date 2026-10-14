"""Routing decisions for roles and ``on`` (spec-2.0 §2.1, §2.5, §3; BIBLE §3.3, §3.6).

Pure functions over registry instances, so they are unit-tested without a bridge:

* ``on: pid | name | role`` on ``cook``, ``render``, ``job`` and ``look`` sends that call
  to the instance it names, whatever is pinned or selected; ``edit`` and ``hip_*`` (every
  other tool) always use the pinned or selected instance.
* A role picks the least busy live instance with that role: fewest ``jobs_running``, then
  not ``busy``, then the bridge's usual preference (GUI first, newest first).
* A pid or name the ledger remembers but that is no longer live is ``instance_lost`` (the
  bridge never runs the call somewhere else); one it never knew is ``houdini_offline`` with
  the live candidates, as ``houdini_connect {pid}`` reports it.
* Job ids: the agent sees ledger ids (``j7f3a9``); :func:`rewrite_job_ids` swaps the
  host's ``<pid>-<hostid>`` for them in a result.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from ..tools.errors import ToolError
from . import instances as registry
from .ledger import ROLES

ROUTABLE: frozenset[str] = frozenset({"cook", "render", "job", "look"})
"""Tools that accept ``on`` (v2 profile)."""

Load = tuple[int, bool]
"""``(jobs_running, busy)`` from an instance's ``/health``."""


@dataclass(frozen=True, slots=True)
class Target:
    """What ``on`` (or ``houdini_connect {role}``) names."""

    kind: str
    """``pid``, ``name`` or ``role``."""
    value: int | str

    def describe(self) -> str:
        if self.kind == "pid":
            return f"pid {self.value}"
        if self.kind == "role":
            return f"a live {self.value}"
        return f"the Houdini named {self.value!r}"


def parse_on(value: Any) -> Target:
    """``on`` as a :class:`Target`: an integer (or digit string) is a pid, ``editor`` or
    ``worker`` a role, any other string a name."""
    if isinstance(value, bool):
        value = None
    if isinstance(value, int) and value > 0:
        return Target("pid", value)
    if isinstance(value, str) and value.strip():
        text = value.strip()
        if text.isdigit():
            return Target("pid", int(text))
        if text in ROLES:
            return Target("role", text)
        return Target("name", text)
    raise ToolError(
        "invalid_argument",
        f"on must be a pid, an instance name or a role ({', '.join(ROLES)}), not {value!r}.",
        hint='on: "worker" runs on the least busy worker; houdini_status lists pids, names '
        "and roles",
    )


def order_by_load(
    candidates: Iterable[registry.Instance], load: Callable[[registry.Instance], Load | None]
) -> list[registry.Instance]:
    """``candidates`` least busy first: ``jobs_running``, then ``busy``, then the usual
    preference order; an instance whose load is unknown (``/health`` failed) goes last."""
    ordered = registry.sort_preferred(candidates)
    keyed = []
    for index, inst in enumerate(ordered):
        known = load(inst)
        keyed.append(((0, known[0], int(known[1]), index) if known else (1, 0, 0, index), inst))
    return [inst for _key, inst in sorted(keyed, key=lambda pair: pair[0])]


def with_role(
    live: Iterable[registry.Instance], role: str, role_of: Callable[[registry.Instance], str]
) -> list[registry.Instance]:
    return [inst for inst in live if role_of(inst) == role]


def pick(
    target: Target,
    live: list[registry.Instance],
    *,
    role_of: Callable[[registry.Instance], str],
    load: Callable[[registry.Instance], Load | None],
    remembered: Callable[[Target], dict[str, Any] | None] = lambda _t: None,
    tool: str = "",
) -> registry.Instance:
    """The live instance ``target`` names, or raise ``instance_lost`` / ``houdini_offline``."""
    if target.kind == "role":
        matches = with_role(live, str(target.value), role_of)
        if matches:
            return order_by_load(matches, load)[0]
        raise no_role_error(str(target.value), live, role_of)
    if target.kind == "pid":
        match = next((inst for inst in live if inst.pid == target.value), None)
    else:
        match = next((inst for inst in live if inst.name and inst.name == target.value), None)
    if match is not None:
        return match
    gone = remembered(target)
    if gone is not None:
        raise target_lost_error(target, gone, live, tool)
    raise no_target_error(target, live)


def candidates_of(
    live: Iterable[registry.Instance], role_of: Callable[[registry.Instance], str] | None = None
) -> list[dict[str, Any]]:
    out = []
    for inst in registry.sort_preferred(live):
        row = inst.candidate()
        if role_of is not None:
            row["role"] = role_of(inst)
        out.append(row)
    return out


def no_role_error(
    role: str, live: list[registry.Instance], role_of: Callable[[registry.Instance], str]
) -> ToolError:
    ordered = registry.sort_preferred(live)
    listed = "; ".join(f"{inst.describe()} {role_of(inst)}" for inst in ordered)
    mode = "headless" if role == "worker" else "gui"
    return ToolError(
        "houdini_offline",
        f"No live Houdini has the role {role}." + (f" Live: {listed}." if listed else ""),
        hint=f"give one the role with houdini_connect {{pid, role: '{role}'}}, or start one "
        f"with houdini_connect {{launch: {{mode: '{mode}'}}, role: '{role}'}}",
        candidates=candidates_of(live, role_of),
        retryable=False,
    )


def no_target_error(target: Target, live: list[registry.Instance]) -> ToolError:
    ordered = registry.sort_preferred(live)
    return ToolError(
        "houdini_offline",
        f"No live HocusPocus instance is {target.describe()}."
        + (f" Live: {'; '.join(i.describe() for i in ordered)}." if ordered else ""),
        hint="pass on as a pid, name or role from the candidates (houdini_status lists them)",
        candidates=[inst.candidate() for inst in ordered],
        retryable=False,
    )


def target_lost_error(
    target: Target, gone: dict[str, Any], live: list[registry.Instance], tool: str = ""
) -> ToolError:
    """``instance_lost`` for an ``on`` target that has exited (1.3 semantics: the bridge
    names it and the live candidates, and never runs the call elsewhere)."""
    pid, label = gone.get("pid"), gone.get("label") or "houdini"
    ordered = registry.sort_preferred(live)
    choices = "; ".join(inst.describe() for inst in ordered) or "none is running"
    what = f"{tool} " if tool else ""
    return ToolError(
        "instance_lost",
        f"The Houdini {target.describe()} (pid {pid}, {label}) has exited; not running "
        f"{what}on another Houdini on its own. Live: {choices}.",
        hint="pass on as one of the candidates, or start a Houdini with houdini_connect {launch}",
        candidates=[inst.candidate() for inst in ordered],
        retryable=False,
        detail={"pid": pid, "label": label, "hip": gone.get("hip") or None},
    )


def rewrite_job_ids(payload: Any, to_ledger: Callable[[str], str | None]) -> Any:
    """``payload`` with every host job id the ledger knows replaced by its ledger id: the
    top-level ``job_id``, each ``jobs[]`` row's, and an error's ``detail.job_id`` and
    ``detail.last_status.job_id``. Returns a copy; unknown ids are left as they are."""
    if not isinstance(payload, dict):
        return payload

    def swap(row: dict[str, Any]) -> dict[str, Any]:
        job_id = row.get("job_id")
        if isinstance(job_id, str):
            mapped = to_ledger(job_id)
            if mapped:
                return dict(row, job_id=mapped)
        return row

    out = swap(payload)
    if isinstance(out.get("jobs"), list):
        out = dict(out, jobs=[swap(r) if isinstance(r, dict) else r for r in out["jobs"]])
    detail = out.get("detail")
    if isinstance(detail, dict):
        detail = swap(detail)
        if isinstance(detail.get("last_status"), dict):
            detail = dict(detail, last_status=swap(detail["last_status"]))
        out = dict(out, detail=detail)
    return out
