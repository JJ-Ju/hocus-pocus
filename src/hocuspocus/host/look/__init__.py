"""``look`` backends (spec-2.0 §2.5, §4): one module per way of making a picture.

* :mod:`.viewer` grabs the GUI Scene Viewer (what the user sees);
* :mod:`.flipbook` renders a temporary Flipbook ROP: in-process in the GUI, headless in a
  kept child hython (the warm child);
* :mod:`.opengl` renders the deprecated OpenGL ROP, the Flipbook ROP's fallback (a fresh
  child, single-threaded for a stage);
* :mod:`.karma` renders a temporary Karma CPU ROP in the host (husk is its own process);
* :mod:`.cop` renders a Cop node through a temporary ``rop_image`` in its network.

:mod:`.select` is the policy that picks the chain of backends for a call (``quality``,
``source``, target kind, GUI or headless), :mod:`.spec` the parsed request
(:class:`~.spec.LookSpec`), :mod:`.run` the orchestration shared by ``look`` and
``viewport_capture``, :mod:`.framing` the targets, cameras and automatic framing,
:mod:`.child` the scene snapshot and child hython, :mod:`.image` the PNG written and
returned. :mod:`.base` has the :class:`~.base.Backend` contract, including what a
headless snapshot carries (parity gap G8).

Stdlib only, ``hou`` imported lazily, like the rest of the host. Importing this package
imports nothing else, so the policy is unit-testable without Houdini.
"""
