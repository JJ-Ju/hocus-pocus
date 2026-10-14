"""Review 22's soak on the 2.0 tools (the 1.4 version: ``../test_soak_200.py``).

The same seeded script: the same 193 steps of work as the 1.4 soak, counted in 1.4 calls
(``Soak.units``), so the random choices, the scheduled actions (a sample every 50, a save
every 100, a look every 40, a canary cook every 25, the cancelled job at 120, the frame-range
job at 150, the ``hip_open`` at 170) and the scene model are those of the 1.4 run. The 2.0
tools do that work in fewer calls and bytes:

* consecutive mutations (create, delete, parm set, node edit, connect, copy) go out as one
  ``edit`` transaction, flushed before the next read, mistake, undo or scheduled action;
* repeated reads (``geo``, ``network``, ``type``, ``problems``, ``jobs``, ``status``) are
  ``houdini://`` resources revalidated with ``_meta["If-None-Match"]``: an unchanged one
  answers ``not_modified`` with no bytes;
* the frame-range cook is one ``cook`` with a progress token that waits for its end (1.4:
  cook + job status + job result); the cancelled job's result carries its last status.

Every 9th mix slot is a read through a one-shot bridge; about 5 % of the slots are
deliberate mistakes. The model checks, the leak checks and the read p95 are 1.4's.
"""

from __future__ import annotations

import copy
import json
import math
import random
import time
from typing import Any
from urllib.parse import quote, urlencode

import pytest
from wl2 import load_1x

pytestmark = pytest.mark.timeout(420)

w1 = load_1x("test_soak_200")
SEED, TOTAL, FINAL_CALLS, READ_P95_MS = w1.SEED, w1.TOTAL, w1.FINAL_CALLS, w1.READ_P95_MS
MAX_OBJECTS, MAX_NODES, CANARY = w1.MAX_OBJECTS, w1.MAX_NODES, w1.CANARY
TYPE_INFO, TYPE_SEARCH, PYTHON = w1.TYPE_INFO, w1.TYPE_SEARCH, w1.PYTHON
Obj, Model = w1.Obj, w1.Model
READS = {"search", "inspect", "time", "houdini_status"}
"""Read tools (plus every ``resource:`` read) for the p95."""


def _uri(kind: str, path: str = "", **query: Any) -> str:
    q = {k: ",".join(v) if isinstance(v, list) else v for k, v in query.items() if v is not None}
    tail = quote(path) if path else ""
    return f"houdini://{kind}{tail}" + (f"?{urlencode(q)}" if q else "")


def _type_uri(args: dict[str, Any]) -> str:
    category, name = args["type"].split("/", 1)
    query = {k: v for k, v in args.items() if k != "type"}
    return _uri("type", f"/{category}/{name}", **query)


class Soak:
    def __init__(self, rec: Any, host_pid: int) -> None:
        self.rec = rec
        self.rng = random.Random(SEED)
        self.model = Model()
        self.saved: dict[str, Any] = {}
        self.first_save: str | None = None
        self.events_since: Any = 0
        self.host_pid = host_pid
        self.mix_slots = 0
        self.next = {"sample": 50, "save": 100, "capture": 40, "canary": 25}
        self.done: set[str] = set()
        self.units = 0
        """The work done so far, in 1.4 calls (the 1.4 soak's ``len(rec.calls)``)."""
        self.ops: list[dict[str, Any]] = []
        self.checks: list[Any] = []
        self.batches: list[int] = []

    def pick(self) -> Any:
        return self.rng.choice(self.model.objs)

    # -- calling ----------------------------------------------------------------------

    def ok(self, tool: str, args: dict[str, Any] | None = None, units: int = 1, **kw: Any) -> Any:
        self.flush()
        self.units += units
        return self.rec.ok(tool, args, **kw)

    def read(self, uri: str, units: int = 1) -> Any:
        self.flush()
        self.units += units
        data, meta = self.rec.read(uri)
        assert data is not None or meta.get("not_modified"), (uri, meta)
        return data

    def queue(self, op: dict[str, Any], check: Any = None) -> None:
        """A mutation: one 1.4 call, one op of the next ``edit``."""
        self.units += 1
        self.ops.append(op)
        if check is not None:
            self.checks.append((len(self.ops) - 1, check))

    def flush(self) -> None:
        if not self.ops:
            return
        ops, checks = self.ops, self.checks
        self.ops, self.checks = [], []
        result = self.rec.ok("edit", {"ops": ops})
        self.batches.append(len(ops))
        assert [n for n in result.get("nodes", []) if n.get("errors")] == [], result.data
        for _index, check in checks:  # the summary echo: node rows, ids, deleted
            check(result.data, result)

    # -- setup and scheduled actions ----------------------------------------------------

    def setup(self) -> None:
        self.ok("houdini_status")
        self.units += 1
        self.rec.ok(
            "edit",
            {
                "ops": [
                    {"op": "create", "id": "g", "parent": "/obj", "type": "geo",
                     "name": "soak_canary"},
                    {"op": "create", "id": "b", "parent": "$g", "type": "box", "name": "box"},
                    {"op": "create", "parent": "$g", "type": "mountain", "name": "mtn",
                     "inputs": [{"index": 0, "from": "$b"}],
                     "parms": {"offsetx": {"expression": "$F*0.1"}},
                     "flags": {"display": True}},
                ]
            },
        )  # fmt: skip
        self.events_since = self.ok("inspect", {"what": "events", "limit": 5})["next_since"]
        for _ in range(3):
            self.create()

    def scheduled(self) -> None:
        if self.units >= self.next["sample"]:
            self.next["sample"] += 50
            self.read("houdini://status")
            self.check_count()
        if self.units >= self.next["canary"]:
            self.next["canary"] += 25
            canary = self.ok("cook", {"paths": [f"{CANARY}/mtn"], "force": True})
            assert canary["ok"] is True, canary.data
        if self.units >= self.next["capture"]:
            self.next["capture"] += 40
            look = self.ok("look", {"resolution": [320, 240]}, timeout=180)
            assert look.images == 1, look.data
        if self.units >= self.next["save"]:
            self.next["save"] += 100
            path = self.rec.path(f"soak_{self.units:03d}.hip")
            assert self.ok("hip_save", {"path": path})["dirty"] is False
            self.saved[path] = copy.deepcopy(self.model)
            self.first_save = self.first_save or path
        if self.units >= 120 and "cancel" not in self.done:
            self.done.add("cancel")
            self.cancelled_job()
        if self.units >= 150 and "range" not in self.done:
            self.done.add("range")
            self.frame_range_job()
        if self.units >= 170 and "reopen" not in self.done and self.first_save:
            self.done.add("reopen")
            opened = self.ok("hip_open", {"path": self.first_save, "on_unsaved": "discard"})
            assert opened["path"] == self.first_save
            self.model = copy.deepcopy(self.saved[self.first_save])

    def check_count(self) -> None:
        found = self.ok("search", {"kind": "nodes", "root": "/obj", "limit": 1})
        assert found["total"] == self.model.count, (found.data, self.model)

    def cancelled_job(self) -> None:
        started = self.ok(
            "cook", {"paths": [f"{CANARY}/mtn"], "frame_range": [1, 10000], "wait_s": 0}
        )
        job_id = started["job_id"]
        cancelled = self.ok("job", {"action": "cancel", "job_id": job_id})
        assert cancelled.get("cancelled") is True, cancelled.data
        _settle(self.rec, job_id)
        # 1.4 recorded a job status here; the cancelled error carries the last status.
        self.units += 2
        result = self.rec.error("job", {"action": "result", "job_id": job_id}, code="cancelled")
        assert result["detail"]["last_status"]["state"] == "cancelled", result.data

    def frame_range_job(self) -> None:
        obj = self.pick()
        done = self.ok(
            "cook",
            {"paths": [obj.out], "frame_range": [1, 24], "summary": "bbox", "wait_s": 120},
            units=3,  # 1.4: cook, job status, job result
            progress=True,
            timeout=180,
        )
        assert done.get("state", "done") == "done" and "job_id" not in done.data, done.data
        assert done.get("frames"), done.data

    # -- the mix ------------------------------------------------------------------------

    def step(self) -> None:
        self.scheduled()
        if self.units >= TOTAL - FINAL_CALLS:
            return
        self.mix_slots += 1
        if self.mix_slots % 9 == 0:
            self.one_shot()
            return
        if self.rng.random() < 0.05:
            self.mistake()
            return
        action = self.rng.choices(MIX, weights=[w for _, w in MIX_WEIGHTS])[0]
        action(self)

    def one_shot(self) -> None:
        obj = self.pick()
        tool, args = self.rng.choice(
            [
                ("houdini_status", {}),
                ("search", {"kind": "nodes", "root": obj.path, "limit": 10}),
                ("inspect", {"what": "node", "paths": [obj.out]}),
                ("inspect", {"what": "parms", "paths": [f"{obj.path}/{obj.xf}/ry"]}),
                ("time", {}),
            ]
        )
        result = self.ok(tool, args, one_shot=True)
        if tool == "houdini_status":
            assert result["connected"]["pid"] == self.host_pid

    def mistake(self) -> None:
        obj = self.pick()
        tool, args, code = self.rng.choice(
            [
                ("inspect", {"what": "node", "paths": [f"{obj.path}/nope"]}, "node_not_found"),
                ("edit", {"ops": [{"op": "set", "path": f"{obj.path}/mtn/heightt", "value": 1}]},
                 "parm_not_found"),
                ("edit", {"ops": [{"op": "set", "path": f"{obj.path}/mtn/height",
                                   "value": "tall"}]}, "invalid_value"),
                ("edit", {"ops": [{"op": "create", "parent": obj.path, "type": "mountian"}]},
                 "node_type_not_found"),
                ("inspect", {"what": "geo", "node_path": obj.out}, "invalid_argument"),
                ("cook", {"paths": [obj.out], "bogus": 1}, "invalid_argument"),
                ("job", {"action": "status", "job_id": f"{self.host_pid}-zzzzzzzzzzzz"},
                 "job_not_found"),
                ("undo", {"action": "sideways"}, "invalid_argument"),
                ("edit", {"ops": [{"op": "node", "path": f"{obj.path}/ghost", "comment": "x"}]},
                 "node_not_found"),
            ]
        )  # fmt: skip
        self.flush()
        self.units += 1
        self.rec.error(tool, args, code=code)

    # mutations: queued, one edit per run of them

    def create(self) -> None:
        while self.model.objs and (
            len(self.model.objs) >= MAX_OBJECTS or self.model.count + 7 > MAX_NODES + 3
        ):
            self.delete(force=True)
        self.model.serial += 1
        obj = Obj(
            name=f"soak_{self.model.serial:03d}",
            prim=self.rng.choice(["box", "sphere", "grid"]),
            copies=self.rng.random() < 0.5,
        )
        p, i = obj.path, obj.name
        ops: list[dict[str, Any]] = [
            {"op": "create", "id": i, "parent": "/obj", "type": "geo", "name": obj.name},
            {"op": "create", "id": f"{i}_src", "parent": f"${i}", "type": obj.prim, "name": "src"},
            {"op": "create", "id": f"{i}_xf", "parent": f"${i}", "type": "xform", "name": "xf",
             "inputs": [{"index": 0, "from": f"${i}_src"}],
             "parms": {"ry": {"expression": "$F*3"}}},
            {"op": "create", "id": f"{i}_mtn", "parent": f"${i}", "type": "mountain", "name": "mtn",
             "inputs": [{"index": 0, "from": f"${i}_xf"}],
             "parms": {"height": round(self.rng.uniform(0.1, 1.0), 2)},
             "flags": {"display": not obj.copies, "render": not obj.copies}},
        ]  # fmt: skip
        if obj.copies:
            ops += [
                {"op": "create", "id": f"{i}_sc", "parent": f"${i}", "type": "scatter",
                 "name": "scatter", "inputs": [{"index": 0, "from": f"${i}_mtn"}],
                 "parms": {"npts": self.rng.choice([20, 50, 100])}},
                {"op": "create", "id": f"{i}_dot", "parent": f"${i}", "type": "sphere",
                 "name": "dot", "parms": {"scale": 0.05}},
                {"op": "create", "parent": f"${i}", "type": "copytopoints", "name": "copy",
                 "inputs": [{"index": 0, "from": f"${i}_dot"}, {"index": 1, "from": f"${i}_sc"}],
                 "flags": {"display": True, "render": True}},
            ]  # fmt: skip
        self.units += 1  # 1.4: one node_create
        self.ops += ops
        expected = obj.path

        def check(summary: dict[str, Any], _result: Any) -> None:
            assert summary["ids"][i] == expected or _gone(expected, summary), summary

        self.checks.append((len(self.ops) - len(ops), check))
        assert p == expected
        self.model.objs.append(obj)

    def delete(self, force: bool = False) -> None:
        if len(self.model.objs) <= 2 and not force:
            return self.create()
        obj = self.model.objs.pop(0)
        self.queue(
            {"op": "delete", "paths": [obj.path]},
            lambda row, _r, p=obj.path: _assert_in(p, row),
        )

    def parm_set(self) -> None:
        obj = self.pick()
        xf = f"{obj.path}/{obj.xf}"
        frame = self.rng.randint(1, 48)
        item = self.rng.choice(
            [
                {"path": f"{xf}/ty", "value": round(self.rng.uniform(-1, 1), 3)},
                {"path": f"{xf}/ry", "expression": f"$F*{self.rng.randint(1, 6)}"},
                {"path": f"{xf}/rz", "expression": "sin($F*10)*5"},
                {"path": f"{xf}/tx", "keyframes": [{"frame": 1, "value": 0},
                                                   {"frame": 24, "value": 2}]},
                {"path": f"{xf}/sx", "keyframe": {"frame": frame, "value": 1.2},
                 "animation": "key"},
                {"path": f"{obj.path}/mtn/height", "value": round(self.rng.uniform(0.1, 1), 2)},
            ]
        )  # fmt: skip
        node = item["path"].rpartition("/")[0]
        self.queue({"op": "set", **item}, lambda row, _r, p=node: _assert_in(p, row))

    def node_edit(self) -> None:
        obj = self.pick()
        kind = self.rng.choice(["comment", "color", "bypass", "rename", "template"])
        if kind == "rename":
            new = f"xf{self.model.serial}{self.rng.randint(10, 99)}"
            if new == obj.xf:
                return
            old = f"{obj.path}/{obj.xf}"
            obj.xf = new
            self.queue(
                {"op": "node", "path": old, "name": new},
                lambda row, _r, p=f"{obj.path}/{new}": _assert_in(p, row),
            )
            return
        target = self.rng.choice(obj.nodes)
        op: dict[str, Any] = {"op": "node", "path": target}
        if kind == "comment":
            op["comment"] = f"soak {self.units}"
        elif kind == "color":
            op["color"] = [round(self.rng.random(), 2) for _ in range(3)]
        elif kind == "bypass":
            obj.bypassed = not obj.bypassed
            op = {"op": "node", "path": f"{obj.path}/{obj.xf}", "flags": {"bypass": obj.bypassed}}
        else:
            op = {"op": "node", "path": f"{obj.path}/src",
                  "flags": {"template": self.rng.random() < 0.5}}  # fmt: skip
        self.queue(op)

    def node_connect(self) -> None:
        obj = self.pick()
        self.queue(
            {"op": "connect", "from": f"{obj.path}/{obj.xf}", "to": f"{obj.path}/mtn",
             "to_input": 0}
        )  # fmt: skip

    def node_copy(self) -> None:
        obj = self.pick()
        if self.model.count + 1 > MAX_NODES + 3:
            return self.delete()
        self.model.serial += 1
        name = f"mtn_c{self.model.serial}"
        self.queue(
            {"op": "copy", "paths": [f"{obj.path}/mtn"], "to_parent": obj.path, "names": [name],
             "position_offset": [2, 0]},
            lambda row, _r, p=f"{obj.path}/{name}": _assert_in(p, row),
        )  # fmt: skip
        obj.extra.append(name)

    def undo_redo(self) -> None:
        undone = self.ok("undo", {"action": "undo"})
        if undone.get("performed"):
            redone = self.ok("undo", {"action": "redo"})
            assert redone.get("performed") == undone["performed"], (undone.data, redone.data)

    # reads

    def node_find(self) -> None:
        obj = self.pick()
        args = self.rng.choice(
            [
                {"root": "/obj", "limit": self.rng.choice([5, 10, 20])},
                {"root": obj.path, "query": self.rng.choice(["*mountain*", "xform", "*"])},
                {"root": "/obj", "query": "geo", "limit": 3},
                {"root": "/obj", "flags": {"display": True}, "limit": 10},
            ]
        )
        found = self.ok("search", {"kind": "nodes", **args})
        if found.get("next_cursor") and self.rng.random() < 0.5:
            self.ok("search", {"kind": "nodes", **args, "cursor": found["next_cursor"]})

    def node_info(self) -> None:
        obj = self.pick()
        paths = self.rng.sample(obj.nodes, k=min(2, len(obj.nodes)))
        include = self.rng.choice([None, ["parms", "inputs"], ["flags", "errors", "position"]])
        args: dict[str, Any] = {"what": "node", "paths": paths}
        if include:
            args["include"] = include
        info = self.ok("inspect", args)
        assert [n["path"] for n in info["nodes"]] == paths, info.data

    def parm_get(self) -> None:
        obj = self.pick()
        xf = f"{obj.path}/{obj.xf}"
        args = self.rng.choice(
            [
                {"paths": [f"{xf}/ry"], "frame": self.rng.randint(1, 48)},
                {"paths": [f"{xf}/t"], "include": ["keys"]},
                {"paths": [f"{obj.path}/mtn/height", f"{xf}/r"]},
            ]
        )
        self.ok("inspect", {"what": "parms", **args})

    def cook(self) -> None:
        obj = self.pick()
        args: dict[str, Any] = {"paths": [obj.out]}
        if self.rng.random() < 0.3:
            args["profile"] = True
        elif self.rng.random() < 0.3:
            args["force"] = True
        cooked = self.ok("cook", args)
        assert cooked.get("ok", True) is True, cooked.data

    def time_(self) -> None:
        args = {} if self.rng.random() < 0.4 else {"frame": self.rng.randint(1, 48)}
        self.ok("time", args)

    def geo_info(self) -> None:
        geo = self.read(_uri("geo", self.pick().out))
        assert geo is None or geo["point_count"] > 0, geo

    def geo_read(self) -> None:
        out = self.pick().out
        self.read(_uri("geo", out, attribs="P", count=self.rng.choice([5, 10, 20])))

    def network_describe(self) -> None:
        fmt = self.rng.choice(["data", "outline"])
        self.read(_uri("network", self.pick().path, format=fmt))

    def events(self) -> None:
        page = self.ok("inspect", {"what": "events", "since": self.events_since, "limit": 20})
        self.events_since = page["next_since"]

    def python(self) -> None:
        self.ok("houdini_python", {"code": self.rng.choice(PYTHON)})

    def type_info(self) -> None:
        args = dict(self.rng.choice(TYPE_INFO))
        if "include_parms" in args:  # not a template variable: the tool reads it
            target = args.pop("type")
            self.ok("inspect", {"what": "type", "target": target, **args})
        else:
            self.read(_type_uri(args))

    def type_search(self) -> None:
        query = self.rng.choice(TYPE_SEARCH)
        self.ok("search", {"kind": "types", "query": query, "category": "Sop", "limit": 5})

    def problems(self) -> None:
        self.read(_uri("problems", root="/obj"))

    def job_list(self) -> None:
        self.read("houdini://jobs")

    # -- the end ------------------------------------------------------------------------

    def final_checks(self) -> None:
        self.flush()
        jobs = self.rec.ok("job", {"action": "list", "all": True})
        running = [j for j in jobs.get("jobs", []) if j.get("state") == "running"]
        assert running == [], jobs.data
        hocus = self.rec.ok("search", {"kind": "nodes", "root": "/", "pattern": "*hocus*"})
        assert hocus["nodes"] == [], hocus.data
        for root in ("/out", "/stage", "/img"):
            found = self.rec.ok("search", {"kind": "nodes", "root": root, "limit": 5})
            assert found["nodes"] == [], root
        self.check_count()
        self.rec.ok("houdini_status")


def _gone(path: str, summary: dict[str, Any]) -> bool:
    """``path`` or an ancestor was deleted, or renamed, by a later op of the same edit."""
    deleted = [*summary.get("deleted", []), *(r.get("old_path", "") for r in summary["nodes"])]
    return any(d and (path == d or path.startswith(f"{d}/")) for d in deleted)


def _assert_in(path: str, summary: dict[str, Any]) -> None:
    """The summary echo names ``path`` (a node row, an id, a deleted path), or a later op
    of the same edit took it away."""
    assert path in json.dumps(summary) or _gone(path, summary), (path, summary)


def _settle(rec: Any, job_id: str, timeout_s: float = 60.0) -> None:
    """Wait (unrecorded, as ``Recorder.wait_job`` does) for a job to leave ``running``."""
    deadline = time.monotonic() + timeout_s
    while True:
        raw = rec.session.call("job", {"action": "status", "job_id": job_id})
        if json.loads(raw.content[0].text).get("state") != "running":
            return
        assert time.monotonic() < deadline, f"job {job_id} still running"
        time.sleep(0.25)


MIX_WEIGHTS = [
    (Soak.node_find, 13),
    (Soak.cook, 6),
    (Soak.parm_set, 8),
    (Soak.node_info, 6),
    (Soak.parm_get, 6),
    (Soak.create, 7),
    (Soak.time_, 4),
    (Soak.node_edit, 7),
    (Soak.job_list, 2),
    (Soak.delete, 5),
    (Soak.node_connect, 4),
    (Soak.events, 4),
    (Soak.undo_redo, 3),
    (Soak.node_copy, 3),
    (Soak.network_describe, 3),
    (Soak.geo_info, 3),
    (Soak.python, 2),
    (Soak.type_info, 2),
    (Soak.geo_read, 2),
    (Soak.type_search, 1),
    (Soak.problems, 1),
]
MIX = [fn for fn, _ in MIX_WEIGHTS]
assert [w for _, w in MIX_WEIGHTS] == [w for _, w in w1.MIX_WEIGHTS]  # the 1.4 mix


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


def test_soak_200(workload, wl_host):
    rec = workload
    soak = Soak(rec, wl_host.pid)
    soak.setup()
    while soak.units < TOTAL - FINAL_CALLS:
        soak.step()
    soak.final_checks()

    reads = [
        c.elapsed_s * 1000
        for c in rec.calls
        if (c.tool in READS or c.tool.startswith("resource:")) and not c.one_shot
    ]
    p95 = _p95(reads)
    half = len(reads) // 2
    stats = {
        "work_units": soak.units + FINAL_CALLS,
        "edit_batches": len(soak.batches),
        "ops_per_edit": round(sum(soak.batches) / max(1, len(soak.batches)), 2),
        "not_modified": sum(
            1 for c in rec.calls if c.tool.startswith("resource:") and c.text_bytes == 0
        ),
        "reads": len(reads),
        "read_p95_ms": round(p95, 1),
        "read_p95_first_half_ms": round(_p95(reads[:half]), 1),
        "read_p95_second_half_ms": round(_p95(reads[half:]), 1),
        "one_shot_calls": sum(c.one_shot for c in rec.calls),
        "deliberate_errors": sum(c.expected_error for c in rec.calls),
        "objects_at_end": len(soak.model.objs),
        "nodes_at_end": soak.model.count,
    }
    assert TOTAL - 5 <= soak.units + FINAL_CALLS <= TOTAL + 10, soak.units
    assert p95 < READ_P95_MS, f"read p95 {p95:.1f} ms >= {READ_P95_MS} ms"
    rec.finish(stats)
