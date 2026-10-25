"""The headless side of docs/parity.md G8 (a mode): a headless look renders a snapshot of
the scene in a child hython (host/look/base.py, the snapshot contract). What the snapshot
cannot carry is said in a note (a DOP simulation's in-memory frames); what it does carry
is checked end to end (an asset whose definition is embedded in the hip file)."""

from __future__ import annotations

import base64
import io
import os

import pytest

hou = pytest.importorskip("hou")
Image = pytest.importorskip("PIL.Image")

pytestmark = pytest.mark.slow  # each look starts or reuses the capture child

RES = [160, 120]


def _changed_pixels(a: dict, b: dict) -> int:
    from PIL import ImageChops

    def gray(result: dict):
        data = base64.b64decode(result["image"]["png_base64"])
        return Image.open(io.BytesIO(data)).convert("L")

    changed = ImageChops.difference(gray(a), gray(b)).point(lambda p: 255 if p > 12 else 0)
    return changed.histogram()[255]


def _camera() -> str:
    cam = hou.node("/obj").createNode("cam", "fixed_cam")
    cam.parmTuple("t").set((0, 0.5, 6))
    return cam.path()


def test_look_notes_simulation_frames_the_snapshot_cannot_carry(v2_client):
    from hocuspocus.host.look.child import cached_simulations

    geo = hou.node("/obj").createNode("geo", "sim_geo")
    box = geo.createNode("box")
    box.setDisplayFlag(True)
    dop = hou.node("/obj").createNode("dopnet", "sim")
    hou.setFrame(1)
    assert cached_simulations() == []
    quiet = v2_client.ok("look", {"camera": _camera(), "resolution": RES})
    assert not any("simulation frames" in n for n in quiet.get("notes", []))

    hou.setFrame(6)
    dop.cook(force=True)  # steps the empty simulation to frame 6: frames 1-6 in memory
    sims = cached_simulations()
    assert [s["path"] for s in sims] == [dop.path()]
    noted = v2_client.ok("look", {"camera": "/obj/fixed_cam", "resolution": RES})
    note = next(n for n in noted["notes"] if "simulation frames" in n)
    assert dop.path() in note and "File Cache" in note


def test_an_embedded_asset_renders_in_the_child(v2_client):
    """An asset whose definition lives in the hip file (library ``Embedded``) is not in
    the snapshot's library list; ``saveChildrenToFile`` carries its definition, so the
    child renders its contents (checked against the same look with the asset hidden)."""
    geo = hou.node("/obj").createNode("geo", "asset_geo")
    subnet = geo.createNode("subnet", "rock")
    inner = subnet.createNode("sphere", "inner")
    inner.parm("scale").set(1.5)
    inner.setDisplayFlag(True)
    asset = subnet.createDigitalAsset(
        name="hp_parity::embedded_rock::1.0", hda_file_name="Embedded", description="Rock"
    )
    asset.setDisplayFlag(True)
    definition = asset.type().definition()
    assert definition is not None and definition.libraryFilePath() == "Embedded"
    camera = _camera()

    shown = v2_client.ok("look", {"camera": camera, "resolution": RES})
    assert shown["backend_used"] == "flipbook", shown
    geo.setDisplayFlag(False)  # the object, so neither its display nor its render SOP shows
    empty = v2_client.ok("look", {"camera": camera, "resolution": RES})
    # A 1.5-unit sphere at 6 units covers well over a tenth of a 160x120 picture.
    assert _changed_pixels(shown, empty) > 2000, _changed_pixels(shown, empty)


def _locked_object_asset(name: str, scale: float):
    """An object-level asset (a subnet holding a sphere's object) defined in the hip file
    and locked: nothing outside the definition says what is inside it."""
    subnet = hou.node("/obj").createNode("subnet", "rock_obj")
    inner = subnet.createNode("geo", "inner")
    sphere = inner.createNode("sphere", "ball")
    sphere.parm("scale").set(scale)
    asset = subnet.createDigitalAsset(name=name, hda_file_name="Embedded", description="Rock")
    asset.matchCurrentDefinition()
    assert asset.isLockedHDA() and asset.type().definition().libraryFilePath() == "Embedded"
    return asset


def test_a_locked_embedded_asset_renders_in_the_child(v2_client):
    """D61: ``saveChildrenToFile`` writes an embedded definition as a stub (no contents),
    so a locked instance drew nothing in the render process. The snapshot now carries the
    hip's embedded definitions as a library file: the asset draws, a second look keeps the
    warm child (same file), and a changed definition is drawn as changed."""
    from hocuspocus.host.look import child
    from hocuspocus.host.tools import visual

    asset = _locked_object_asset("hp_parity::locked_rock::1.0", 1.5)
    camera = _camera()
    asset.setDisplayFlag(False)
    empty = v2_client.ok("look", {"camera": camera, "resolution": RES})
    asset.setDisplayFlag(True)
    shown = v2_client.ok("look", {"camera": camera, "resolution": RES})
    assert shown["backend_used"] == "flipbook", shown
    assert _changed_pixels(shown, empty) > 2000, _changed_pixels(shown, empty)
    library = child._embedded_lib["path"]
    assert library and os.path.isfile(library)
    pid = visual._warm["child"].proc.pid
    again = v2_client.ok("look", {"camera": camera, "resolution": RES})
    assert visual._warm["child"].proc.pid == pid and child._embedded_lib["path"] == library
    assert _changed_pixels(shown, again) < 50

    # The user changes the asset: a smaller sphere, saved into the definition.
    asset.allowEditingOfContents()
    hou.node(f"{asset.path()}/inner/ball").parm("scale").set(0.4)
    asset.type().definition().updateFromNode(asset)
    asset.matchCurrentDefinition()
    smaller = v2_client.ok("look", {"camera": camera, "resolution": RES})
    assert child._embedded_lib["path"] != library
    assert _changed_pixels(shown, smaller) > 2000, _changed_pixels(shown, smaller)
    assert _changed_pixels(smaller, empty) > 200, _changed_pixels(smaller, empty)
