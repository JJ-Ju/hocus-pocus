"""The picture a look returns: a PNG under ``<state_dir>/captures`` (the newest
:data:`CAPTURES_KEEP` kept), flattened onto :data:`BACKGROUND` and returned as
``{"image": {"png_base64", "mime_type"}}``, which the bridge turns into MCP image content
(BIBLE §8). No ``hou`` here except :func:`capture_targets`."""

from __future__ import annotations

import base64
import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from hocuspocus.tools.errors import ToolError
from hocuspocus.tools.paths import captures_dir, ensure_private_dir

from ..tools.geo import num
from ..tools.hip import _norm, check_allowed, resolve_path
from ..tools.registry import HostContext

IMAGE_MAX_SIDE = 1024
THUMB_MAX_SIDE = 512
BACKGROUND = (64, 64, 64)
"""Alpha is composited onto mid grey so silhouettes read on light and dark clients."""
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".tga"}
CAPTURES_KEEP = 50
"""``<state_dir>/captures`` keeps the newest this many files."""


def _captures(ctx: HostContext) -> Path:
    base = Path(ctx.config.state_dir) / "captures" if ctx.config.state_dir else captures_dir()
    return ensure_private_dir(base)


def prune_captures(directory: Path, keep: int = CAPTURES_KEEP) -> int:
    """Delete all but the newest ``keep`` files in ``directory``. Returns how many went."""
    try:
        files = [p for p in directory.iterdir() if p.is_file()]
    except OSError:
        return 0
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    removed = 0
    for path in files[keep:]:
        with contextlib.suppress(OSError):
            path.unlink()
            removed += 1
    return removed


def _stamp() -> str:
    now = time.time()
    return (
        time.strftime("%Y%m%d-%H%M%S", time.localtime(now)) + f"-{int(now * 1e6) % 1_000_000:06d}"
    )


def _flatten(im: Any) -> Any:
    """``im`` as RGB, with any alpha composited onto :data:`BACKGROUND`."""
    from PIL import Image

    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        rgba = im.convert("RGBA")
        flat = Image.new("RGB", rgba.size, BACKGROUND)
        flat.paste(rgba, mask=rgba.getchannel("A"))
        return flat
    return im.convert("RGB")


def flatten_png_in_place(path: str) -> None:
    """Rewrite a capture PNG without alpha, on the inline image's grey (review 12): the
    OpenGL ROP has no background-colour parm and writes a transparent background, which
    most image viewers show as white. Captures only; render outputs are never touched."""
    from PIL import Image

    with Image.open(path) as im:
        im.load()
        if im.mode == "RGB":
            return
        flat = _flatten(im)
    flat.save(path, format="PNG")


def encode_png(
    path: str, max_side: int, *, hfs: str | None = None, measure: bool = False
) -> dict[str, Any]:
    """Load an image file, flatten alpha onto grey, downscale, return the image dict.

    Formats PIL cannot read (EXR, .pic, ...) are converted with ``$HFS/bin/iconvert``.
    ``measure`` adds ``mean_luma``: the mean luminance (0..255) of the returned image,
    after alpha is flattened onto grey (review 20 N1: measured on the raw RGBA, the
    transparent pixels of a sparse OpenGL frame counted as black), and, for an image with
    alpha, ``coverage``: the fraction of its pixels with alpha above 0.
    """
    from PIL import Image

    source = path
    tmp_dir = None

    def convert() -> str:
        nonlocal tmp_dir
        tmp_dir = tmp_dir or tempfile.mkdtemp(prefix="hp-thumb-")
        target = os.path.join(tmp_dir, "thumb.png")
        exe = os.path.join(
            hfs or os.environ.get("HFS", ""),
            "bin",
            "iconvert.exe" if sys.platform == "win32" else "iconvert",
        )
        proc = subprocess.run(
            [exe, path, target],
            capture_output=True,
            text=True,
            timeout=120,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if proc.returncode != 0 or not os.path.isfile(target):
            raise ToolError(
                "internal",
                f"iconvert could not convert {path} to PNG.",
                hou_exception=f"iconvert exit {proc.returncode}",
                detail={"stderr": (proc.stderr or proc.stdout)[-2000:]},
            )
        return target

    try:
        if os.path.splitext(path)[1].lower() not in IMAGE_EXTS:
            source = convert()
        try:
            opened = Image.open(source)
        except Exception:
            if source != path:
                raise
            # A TIFF PIL cannot read (float or 16-bit Copernicus output; review 18): let
            # iconvert make a PNG of it.
            source = convert()
            opened = Image.open(source)
        with opened as im:
            im.load()
            coverage = None
            if measure and (
                im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info)
            ):
                alpha = im.convert("RGBA").getchannel("A")
                total = alpha.size[0] * alpha.size[1]
                coverage = (total - alpha.histogram()[0]) / float(total or 1)
            flat = _flatten(im)
            if max(flat.size) > max_side:
                flat.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
            mean_luma = None
            if measure:
                from PIL import ImageStat

                mean_luma = float(ImageStat.Stat(flat.convert("L")).mean[0])
            buf = io.BytesIO()
            flat.save(buf, format="PNG", optimize=True)
            out = {
                "png_base64": base64.b64encode(buf.getvalue()).decode("ascii"),
                "mime_type": "image/png",
                "width": flat.size[0],
                "height": flat.size[1],
            }
            if mean_luma is not None:
                out["mean_luma"] = mean_luma
            if coverage is not None:
                out["coverage"] = coverage
            return out
    finally:
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)


def image_size(path: str) -> tuple[int, int] | None:
    """The pixel size of the image file at ``path``, or None when PIL cannot read it."""
    try:
        from PIL import Image

        with Image.open(path) as im:
            return int(im.size[0]), int(im.size[1])
    except Exception:
        return None


def capture_targets(parsed: dict[str, Any], ctx: HostContext) -> tuple[float, Any, str]:
    """Frame, checked extra path and capture file for one capture. Main thread."""
    import hou

    frame = float(hou.frame() if parsed["frame"] is None else parsed["frame"])
    extra_path = parsed["path"]
    if extra_path is not None:
        extra_path = resolve_path(extra_path)
        check_allowed(extra_path, ctx)
    out_file = _norm(_captures(ctx) / f"capture_{_stamp()}.png")
    return frame, extra_path, out_file


def write_copy(out_file: str, target: str) -> None:
    """Copy the flattened capture to ``target``: the PNG as is, or re-encoded as JPEG for
    a ``.jpg``/``.jpeg`` target (``look {output}``). Parent directories are created."""
    try:
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        if target.lower().endswith((".jpg", ".jpeg")):
            from PIL import Image

            with Image.open(out_file) as im:
                im.convert("RGB").save(target, format="JPEG", quality=92)
        else:
            shutil.copyfile(out_file, target)
    except OSError as exc:
        raise ToolError(
            "invalid_argument",
            f"Cannot write the image to {target}: {exc.strerror or exc}.",
            hint="Pass a writable file path.",
            detail={"path": out_file},
        ) from exc


def finish_capture(
    out_file: str,
    res: tuple[int, int],
    frame: float,
    info: dict[str, Any],
    extra_path: Any,
) -> dict[str, Any]:
    """Flatten the capture onto the inline image's grey, encode it and copy it to
    ``extra_path`` (``look``'s ``output``), reported as ``output``. No ``hou``."""
    flatten_png_in_place(out_file)
    image = encode_png(out_file, IMAGE_MAX_SIDE)
    result: dict[str, Any] = {
        "image": image,
        "path": out_file,
        "width": image["width"],
        "height": image["height"],
        "rendered": list(res),
        "frame": num(frame),
        **info,
    }
    if extra_path is not None:
        write_copy(out_file, extra_path)
        result["output"] = extra_path
    prune_captures(Path(out_file).parent)
    return result
