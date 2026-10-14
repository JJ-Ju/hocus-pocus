"""Review 22 (soak of 1.3) as a deterministic 200-call workload.

One persistent session drives a weighted mix of reads and mutations from a fixed seed,
with review 22's scheduled actions: a sample every 50 calls (``houdini_status`` and an
``/obj`` node count checked against the script's model of the scene), ``hip_save`` every
100, a 320×240 ``viewport_capture`` every 40, a forced canary ``cook`` every 25, a
frame-range cook job, a cook job cancelled at once, and a ``hip_open`` of the first save.
Every 9th mix slot is a read through a one-shot bridge. About 5 % of the mix slots are
deliberate mistakes, each checked for its error code.

The script keeps an exact model of the scene (an ``undo`` is always followed by a
``redo``), so it can assert at every sample and at the end that no node leaked, that no
job is left running, and that the HocusPocus helpers (capture cameras, ROPs) are gone.
Read latency (persistent session, read tools only) must stay under ``READ_P95_MS`` at the
95th percentile. Job waits poll without recording (``Recorder.wait_job``), so the call
count is the same on every run.
"""

from __future__ import annotations

import copy
import math
import random
from dataclasses import dataclass, field
from typing import Any

import pytest

pytestmark = pytest.mark.timeout(420)

SEED = 22
TOTAL = 200
FINAL_CALLS = 7
READ_P95_MS = 250.0
MAX_OBJECTS = 8
MAX_NODES = 50
CANARY = "/obj/soak_canary"
READS = {
    "node_find", "node_info", "parm_get", "geo_info", "geo_read", "time", "houdini_status",
    "events", "network_describe", "problems", "node_type_info",
}  # fmt: skip
TYPE_INFO = [
    {"type": "Sop/box", "parms": "size*|t*"},
    {"type": "Sop/mountain", "parms": "*height*|*offset*"},
    {"type": "Sop/scatter", "parms": "*count*|npts"},
    {"type": "Sop/xform", "detail": "folders"},
    {"type": "Sop/copytopoints", "include_parms": False},
]
TYPE_SEARCH = ["scatter", "noise", "copy to points", "transform", "subdivide"]
PYTHON = [
    "len(hou.node('/obj').children())",
    "hou.frame()",
    "hou.hipFile.basename()",
    "[n.name() for n in hou.node('/obj').children()][:5]",
]


@dataclass
class Obj:
    name: str
    prim: str
    copies: bool
    xf: str = "xf"
    extra: list[str] = field(default_factory=list)
    bypassed: bool = False

    @property
    def path(self) -> str:
        return f"/obj/{self.name}"

    @property
    def out(self) -> str:
        return f"{self.path}/{'copy' if self.copies else 'mtn'}"

    @property
    def nodes(self) -> list[str]:
        names = ["src", self.xf, "mtn"] + (["scatter", "dot", "copy"] if self.copies else [])
        return [f"{self.path}/{n}" for n in names + self.extra]

    @property
    def count(self) -> int:
        return 1 + len(self.nodes)


@dataclass
class Model:
    objs: list[Obj] = field(default_factory=list)
    serial: int = 0

    @property
    def count(self) -> int:
        return 3 + sum(o.count for o in self.objs)  # the canary is geo + box + mountain


class Soak:
    def __init__(self, rec: Any, host_pid: int) -> None:
        self.rec = rec
        self.rng = random.Random(SEED)
        self.model = Model()
        self.saved: dict[str, Model] = {}
        self.first_save: str | None = None
        self.events_since: Any = 0
        self.host_pid = host_pid
        self.mix_slots = 0
        self.next = {"sample": 50, "save": 100, "capture": 40, "canary": 25}
        self.done: set[str] = set()

    # -- helpers ------------------------------------------------------------------------

    @property
    def n(self) -> int:
        return len(self.rec.calls)

    def pick(self) -> Obj:
        return self.rng.choice(self.model.objs)

    # -- setup and scheduled actions ------------------------------------------------------

    def setup(self) -> None:
        self.rec.ok("houdini_status")
        self.rec.ok(
            "node_create",
            {
                "items": [
                    {"parent": "/obj", "type": "geo", "name": "soak_canary"},
                    {"parent": CANARY, "type": "box", "name": "box"},
                    {
                        "parent": CANARY,
                        "type": "mountain",
                        "name": "mtn",
                        "inputs": [{"index": 0, "from": f"{CANARY}/box"}],
                        "parms": {"offsetx": {"expression": "$F*0.1"}},
                        "flags": {"display": True},
                    },
                ]
            },
        )
        self.events_since = self.rec.ok("events", {"limit": 5})["next_since"]
        for _ in range(3):
            self.create()

    def scheduled(self) -> None:
        if self.n >= self.next["sample"]:
            self.next["sample"] += 50
            self.rec.ok("houdini_status")
            self.check_count()
        if self.n >= self.next["canary"]:
            self.next["canary"] += 25
            canary = self.rec.ok("cook", {"paths": [f"{CANARY}/mtn"], "force": True})
            assert canary["ok"] is True, canary.data
        if self.n >= self.next["capture"]:
            self.next["capture"] += 40
            look = self.rec.ok("viewport_capture", {"resolution": [320, 240]}, timeout=180)
            assert look.images == 1, look.data
        if self.n >= self.next["save"]:
            self.next["save"] += 100
            path = self.rec.path(f"soak_{self.n:03d}.hip")
            assert self.rec.ok("hip_save", {"path": path})["dirty"] is False
            self.saved[path] = copy.deepcopy(self.model)
            self.first_save = self.first_save or path
        if self.n >= 120 and "cancel" not in self.done:
            self.done.add("cancel")
            self.cancelled_job()
        if self.n >= 150 and "range" not in self.done:
            self.done.add("range")
            self.frame_range_job()
        if self.n >= 170 and "reopen" not in self.done and self.first_save:
            self.done.add("reopen")
            opened = self.rec.ok("hip_open", {"path": self.first_save, "on_unsaved": "discard"})
            assert opened["path"] == self.first_save
            self.model = copy.deepcopy(self.saved[self.first_save])

    def check_count(self) -> None:
        found = self.rec.ok("node_find", {"root": "/obj", "limit": 1})
        assert found["total"] == self.model.count, (found.data, self.model)

    def cancelled_job(self) -> None:
        started = self.rec.ok(
            "cook", {"paths": [f"{CANARY}/mtn"], "frame_range": [1, 10000], "wait_s": 0}
        )
        job_id = started["job_id"]
        cancelled = self.rec.ok("job", {"action": "cancel", "job_id": job_id})
        assert cancelled.get("cancelled") is True, cancelled.data
        assert self.rec.wait_job(job_id)["state"] == "cancelled"
        self.rec.error("job", {"action": "result", "job_id": job_id}, code="cancelled")

    def frame_range_job(self) -> None:
        obj = self.pick()
        started = self.rec.ok(
            "cook",
            {"paths": [obj.out], "frame_range": [1, 24], "summary": "bbox", "wait_s": 0},
        )
        assert self.rec.wait_job(started["job_id"])["state"] == "done"
        result = self.rec.ok("job", {"action": "result", "job_id": started["job_id"]})
        assert result["state"] == "done", result.data

    # -- the mix --------------------------------------------------------------------------

    def step(self) -> None:
        self.scheduled()
        if self.n >= TOTAL - FINAL_CALLS:
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
                ("node_find", {"root": obj.path, "limit": 10}),
                ("node_info", {"paths": [obj.out]}),
                ("parm_get", {"paths": [f"{obj.path}/{obj.xf}/ry"]}),
                ("time", {}),
            ]
        )
        result = self.rec.ok(tool, args, one_shot=True)
        if tool == "houdini_status":
            assert result["connected"]["pid"] == self.host_pid

    def mistake(self) -> None:
        obj = self.pick()
        tool, args, code = self.rng.choice(
            [
                ("node_info", {"paths": [f"{obj.path}/nope"]}, "node_not_found"),
                ("parm_set", {"items": [{"path": f"{obj.path}/mtn/heightt", "value": 1}]},
                 "parm_not_found"),
                ("parm_set", {"items": [{"path": f"{obj.path}/mtn/height", "value": "tall"}]},
                 "invalid_value"),
                ("node_create", {"items": [{"parent": obj.path, "type": "mountian"}]},
                 "node_type_not_found"),
                ("geo_info", {"node_path": obj.out}, "invalid_argument"),
                ("cook", {"paths": [obj.out], "bogus": 1}, "invalid_argument"),
                ("job", {"action": "status", "job_id": f"{self.host_pid}-zzzzzzzzzzzz"},
                 "job_not_found"),
                ("undo", {"action": "sideways"}, "invalid_argument"),
                ("node_edit", {"items": [{"path": f"{obj.path}/ghost", "comment": "x"}]},
                 "node_not_found"),
            ]
        )  # fmt: skip
        self.rec.error(tool, args, code=code)

    # mutations

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
        p = obj.path
        items: list[dict[str, Any]] = [
            {"parent": "/obj", "type": "geo", "name": obj.name},
            {"parent": p, "type": obj.prim, "name": "src"},
            {
                "parent": p,
                "type": "xform",
                "name": "xf",
                "inputs": [{"index": 0, "from": f"{p}/src"}],
                "parms": {"ry": {"expression": "$F*3"}},
            },
            {
                "parent": p,
                "type": "mountain",
                "name": "mtn",
                "inputs": [{"index": 0, "from": f"{p}/xf"}],
                "parms": {"height": round(self.rng.uniform(0.1, 1.0), 2)},
                "flags": {"display": not obj.copies, "render": not obj.copies},
            },
        ]
        if obj.copies:
            items += [
                {
                    "parent": p,
                    "type": "scatter",
                    "name": "scatter",
                    "inputs": [{"index": 0, "from": f"{p}/mtn"}],
                    "parms": {"npts": self.rng.choice([20, 50, 100])},
                },
                {"parent": p, "type": "sphere", "name": "dot", "parms": {"scale": 0.05}},
                {
                    "parent": p,
                    "type": "copytopoints",
                    "name": "copy",
                    "inputs": [
                        {"index": 0, "from": f"{p}/dot"},
                        {"index": 1, "from": f"{p}/scatter"},
                    ],
                    "flags": {"display": True, "render": True},
                },
            ]
        made = self.rec.ok("node_create", {"items": items})
        assert all(not row.get("errors") for row in made["results"]), made.data
        self.model.objs.append(obj)

    def delete(self, force: bool = False) -> None:
        if len(self.model.objs) <= 2 and not force:
            return self.create()
        obj = self.model.objs.pop(0)
        deleted = self.rec.ok("node_delete", {"paths": [obj.path]})
        assert obj.path in str(deleted.data), deleted.data

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
        result = self.rec.ok("parm_set", {"items": [item]})
        assert result["results"][0]["path"] == item["path"], result.data

    def node_edit(self) -> None:
        obj = self.pick()
        kind = self.rng.choice(["comment", "color", "bypass", "rename", "template"])
        if kind == "rename":
            new = f"xf{self.model.serial}{self.rng.randint(10, 99)}"
            if new == obj.xf:
                return
            edited = self.rec.ok(
                "node_edit", {"items": [{"path": f"{obj.path}/{obj.xf}", "name": new}]}
            )
            obj.xf = new
            assert f"{obj.path}/{new}" in str(edited.data), edited.data
            return
        target = self.rng.choice(obj.nodes)
        item: dict[str, Any] = {"path": target}
        if kind == "comment":
            item["comment"] = f"soak {self.n}"
        elif kind == "color":
            item["color"] = [round(self.rng.random(), 2) for _ in range(3)]
        elif kind == "bypass":
            target = f"{obj.path}/{obj.xf}"
            obj.bypassed = not obj.bypassed
            item = {"path": target, "flags": {"bypass": obj.bypassed}}
        else:
            item = {"path": f"{obj.path}/src", "flags": {"template": self.rng.random() < 0.5}}
        self.rec.ok("node_edit", {"items": [item]})

    def node_connect(self) -> None:
        obj = self.pick()
        self.rec.ok(
            "node_connect",
            {"items": [{"from": f"{obj.path}/{obj.xf}", "to": f"{obj.path}/mtn", "to_input": 0}]},
        )

    def node_copy(self) -> None:
        obj = self.pick()
        if self.model.count + 1 > MAX_NODES + 3:
            return self.delete()
        self.model.serial += 1
        name = f"mtn_c{self.model.serial}"
        copied = self.rec.ok(
            "node_copy",
            {"paths": [f"{obj.path}/mtn"], "to_parent": obj.path, "names": [name],
             "position_offset": [2, 0]},
        )  # fmt: skip
        assert f"{obj.path}/{name}" in str(copied.data), copied.data
        obj.extra.append(name)

    def undo_redo(self) -> None:
        undone = self.rec.ok("undo", {"action": "undo"})
        if undone.get("performed"):
            redone = self.rec.ok("undo", {"action": "redo"})
            assert redone.get("performed") == undone["performed"], (undone.data, redone.data)

    # reads

    def node_find(self) -> None:
        obj = self.pick()
        args = self.rng.choice(
            [
                {"root": "/obj", "limit": self.rng.choice([5, 10, 20])},
                {"root": obj.path, "type": self.rng.choice(["*mountain*", "xform", "*"])},
                {"root": "/obj", "type": "geo", "limit": 3},
                {"root": "/obj", "flags": {"display": True}, "limit": 10},
            ]
        )
        found = self.rec.ok("node_find", args)
        if found.get("next_cursor") and self.rng.random() < 0.5:
            self.rec.ok("node_find", {**args, "cursor": found["next_cursor"]})

    def node_info(self) -> None:
        obj = self.pick()
        paths = self.rng.sample(obj.nodes, k=min(2, len(obj.nodes)))
        include = self.rng.choice([None, ["parms", "inputs"], ["flags", "errors", "position"]])
        args: dict[str, Any] = {"paths": paths}
        if include:
            args["include"] = include
        info = self.rec.ok("node_info", args)
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
        self.rec.ok("parm_get", args)

    def cook(self) -> None:
        obj = self.pick()
        args: dict[str, Any] = {"paths": [obj.out]}
        if self.rng.random() < 0.3:
            args["profile"] = True
        elif self.rng.random() < 0.3:
            args["force"] = True
        cooked = self.rec.ok("cook", args)
        assert cooked.get("ok", True) is True, cooked.data

    def time_(self) -> None:
        args = {} if self.rng.random() < 0.4 else {"frame": self.rng.randint(1, 48)}
        self.rec.ok("time", args)

    def geo_info(self) -> None:
        geo = self.rec.ok("geo_info", {"path": self.pick().out})
        assert geo["point_count"] > 0, geo.data

    def geo_read(self) -> None:
        self.rec.ok(
            "geo_read",
            {"path": self.pick().out, "attribs": ["P"], "count": self.rng.choice([5, 10, 20])},
        )

    def network_describe(self) -> None:
        fmt = self.rng.choice(["data", "outline"])
        self.rec.ok("network_describe", {"root": self.pick().path, "format": fmt})

    def events(self) -> None:
        page = self.rec.ok("events", {"since": self.events_since, "limit": 20})
        self.events_since = page["next_since"]

    def python(self) -> None:
        self.rec.ok("houdini_python", {"code": self.rng.choice(PYTHON)})

    def type_info(self) -> None:
        self.rec.ok("node_type_info", dict(self.rng.choice(TYPE_INFO)))

    def type_search(self) -> None:
        query = self.rng.choice(TYPE_SEARCH)
        self.rec.ok("node_type_search", {"query": query, "category": "Sop", "limit": 5})

    def problems(self) -> None:
        self.rec.ok("problems", {"root": "/obj"})

    def job_list(self) -> None:
        self.rec.ok("job", {"action": "list"})

    # -- the end --------------------------------------------------------------------------

    def final_checks(self) -> None:
        jobs = self.rec.ok("job", {"action": "list", "all": True})
        running = [j for j in jobs.get("jobs", []) if j.get("state") == "running"]
        assert running == [], jobs.data
        hocus = self.rec.ok("node_find", {"root": "/", "pattern": "*hocus*"})
        assert hocus["nodes"] == [], hocus.data
        for root in ("/out", "/stage", "/img"):
            assert self.rec.ok("node_find", {"root": root, "limit": 5})["nodes"] == [], root
        self.check_count()
        self.rec.ok("houdini_status")


MIX: list[Any] = []
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
MIX[:] = [fn for fn, _ in MIX_WEIGHTS]


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


def test_soak_200(workload, wl_host):
    rec = workload
    soak = Soak(rec, wl_host.pid)
    soak.setup()
    while rec.calls and len(rec.calls) < TOTAL - FINAL_CALLS:
        soak.step()
    soak.final_checks()

    reads = [c.elapsed_s * 1000 for c in rec.calls if c.tool in READS and not c.one_shot]
    p95 = _p95(reads)
    half = len(reads) // 2
    stats = {
        "reads": len(reads),
        "read_p95_ms": round(p95, 1),
        "read_p95_first_half_ms": round(_p95(reads[:half]), 1),
        "read_p95_second_half_ms": round(_p95(reads[half:]), 1),
        "one_shot_calls": sum(c.one_shot for c in rec.calls),
        "deliberate_errors": sum(c.expected_error for c in rec.calls),
        "objects_at_end": len(soak.model.objs),
        "nodes_at_end": soak.model.count,
    }
    assert TOTAL - 5 <= len(rec.calls) <= TOTAL + 10, len(rec.calls)
    assert p95 < READ_P95_MS, f"read p95 {p95:.1f} ms >= {READ_P95_MS} ms"
    rec.finish(stats)
