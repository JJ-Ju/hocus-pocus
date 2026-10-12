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
try:
    import hocuspocus.host as _hocuspocus_host

    _hocuspocus_host.autostart()
except Exception as _exc:  # pragma: no cover - only runs inside Houdini
    try:
        import hou

        hou.ui.setStatusMessage(
            f"HocusPocus autostart failed: {_exc}", severity=hou.severityType.Warning
        )
    except Exception:
        pass
