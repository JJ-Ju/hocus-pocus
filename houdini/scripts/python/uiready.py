# HocusPocus GUI autostart.
#
# Location: <payload>/scripts/python/uiready.py, where <payload> is on HOUDINI_PATH via
# the package JSON's "hpath". Houdini runs every uiready.py it finds on HOUDINI_PATH once
# the UI is ready, in interactive sessions only (never in hython). The SideFX docs
# (hom/locations.html) list pythonX.Ylibs/uiready.py; the legacy scripts/python/ location
# also still runs. Verified empirically on Houdini 22.0.466 (houdinifx, isolated
# HOUDINI_USER_PREF_DIR): uiready.py in BOTH <payload>/python3.13libs/ and
# <payload>/scripts/python/ ran with hou.isUIAvailable() == True, alongside SideFX's own
# $HFS/houdini/python3.13libs/uiready.py. We use scripts/python/ because it does not
# encode the Python version (docs/BIBLE.md §10.1).
#
# Startup never raises into Houdini: failures go to the host log and the status bar.
# autostart() writes <state_dir>/startup/<pid>.json for a launch that waits on this
# Houdini (D60); when hocuspocus.host itself cannot be imported, the record is written
# here, with the stdlib only (the state dir as hocuspocus.tools.paths.state_dir finds it).
try:
    import hocuspocus.host as _hocuspocus_host

    _hocuspocus_host.autostart()
except Exception as _exc:  # pragma: no cover - only runs inside Houdini
    try:
        import json as _json
        import os as _os
        import sys as _sys
        import time as _time

        _state = _os.environ.get("HOCUSPOCUS_STATE_DIR")
        if not _state and _sys.platform == "win32":
            _base = _os.environ.get("LOCALAPPDATA") or _os.path.expanduser("~/AppData/Local")
            _state = _os.path.join(_base, "HocusPocus")
        elif not _state:
            _base = _os.environ.get("XDG_STATE_HOME") or _os.path.expanduser("~/.local/state")
            _state = _os.path.join(_base, "hocuspocus")
        _dir = _os.path.join(_state, "startup")
        _os.makedirs(_dir, exist_ok=True)
        _record = {
            "pid": _os.getpid(),
            "phase": "failed",
            "time": _time.time(),
            "error": f"cannot import hocuspocus.host: {type(_exc).__name__}: {_exc}",
        }
        with open(_os.path.join(_dir, f"{_os.getpid()}.json"), "w", encoding="utf-8") as _f:
            _json.dump(_record, _f)
    except Exception:
        pass
    try:
        import hou

        hou.ui.setStatusMessage(
            f"HocusPocus autostart failed: {_exc}", severity=hou.severityType.Warning
        )
    except Exception:
        pass
