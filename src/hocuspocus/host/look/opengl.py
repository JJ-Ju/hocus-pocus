"""The OpenGL backend: the deprecated OpenGL ROP (``Driver/opengl``, "Replaced by the
Flipbook ROP." in 22.0), the Flipbook ROP's fallback where it fails, and the only viewport
ROP of builds without the Flipbook ROP. Removed once Houdini 22.5 is the floor
(spec-2.0 §2.5).

The same temporary camera and ROP as :mod:`.flipbook` (one builder, ``rop_type:
opengl``). Headless it renders in a *fresh* child hython every time (never the kept one:
the second ``render()`` of an OpenGL ROP in a process segfaults), and a child that renders
a stage runs single-threaded (``HOUDINI_MAXTHREADS=1``, review 16 N1:
:class:`~.child.ChildRender` sets it for ``lop`` captures of ``rop_type: opengl``). No
deprecation note is added for this temporary ROP; ``node_create`` of ``Driver/opengl``
keeps its note.
"""

from __future__ import annotations

from .flipbook import ViewportRopBackend


class OpenGLBackend(ViewportRopBackend):
    """The OpenGL ROP: after the Flipbook ROP in every viewport ROP chain."""

    name = "opengl"


OPENGL = OpenGLBackend()
