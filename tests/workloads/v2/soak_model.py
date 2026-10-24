"""Review 22's soak: its fixed parameters and the scene model ``test_soak_200_v2.py``
checks at every sample (not a test module). Until 2.1 they lived in the 1.4 workload
``tests/workloads/test_soak_200.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

SEED = 22
TOTAL = 200
FINAL_CALLS = 7
READ_P95_MS = 250.0
MAX_OBJECTS = 8
MAX_NODES = 50
CANARY = "/obj/soak_canary"
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
